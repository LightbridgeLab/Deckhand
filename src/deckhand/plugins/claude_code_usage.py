"""Built-in plugin: derive Claude Code usage metrics from local session logs.

Claude Code records every assistant message to a per-session JSONL file under
``~/.claude/projects/<encoded-cwd>/<session-uuid>.jsonl``. Each assistant
record carries ``message.usage`` (``input_tokens``, ``cache_creation_input_tokens``,
``cache_read_input_tokens``, ``output_tokens``), ``message.model``, and a top-
level ``timestamp``. This plugin polls those files and writes three normalized
metrics to the state store so a Data Widget button can display them.

What we found in the on-disk data:

* ``~/.claude/stats-cache.json`` is daily message / session / tool-call counts
  only — no token data, no caps. Not useful here.
* The JSONL session logs are the only place authoritative token counts live.
* **No cap information is anywhere on disk.** Claude's UI shows percentages
  because Anthropic's server tells it the cap. So ``percent`` and ``max`` in
  the published state are ``null`` unless the user configures expected caps
  in ``[plugins.claude_code_usage]``.

Heuristics (intentionally documented so a future maintainer can revisit):

* **Token counting:** ``input_tokens + cache_creation_input_tokens +
  output_tokens``. ``cache_read_input_tokens`` is excluded because cache
  reads are not billed at full rate.
* **Session window:** a rolling N hours from now (default 5). This is an
  approximation of Claude's own session concept. It agrees with ``/usage``
  during active use; it will diverge if you've been idle.
* **Week window:** the last 7 calendar days, not "this calendar week" —
  simpler, matches the rolling-window pattern, and lines up better with
  Anthropic's Sonnet weekly cap which also rolls.
* **Sonnet filter:** case-insensitive ``"sonnet" in model_id``. Catches
  ``claude-sonnet-4-6``, ``claude-3-5-sonnet``, etc.

Configuration block (all keys optional)::

    [plugins.claude_code_usage]
    poll_interval_seconds = 30
    session_window_hours  = 5
    data_dir              = "~/.claude"
    session_token_cap     = 500000
    week_token_cap        = 10000000
    week_sonnet_token_cap = 5000000

Known limitation: the polling task is spawned at ``register()`` time and is
never cancelled. On plugin reload it leaks until the service exits. This is
intentional for v1 and will be cleaned up alongside the broader plugin
shutdown hook tracked in #29.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from deckhand.config.loader import load_config
from deckhand.plugins.registry import PluginRegistry

logger = logging.getLogger(__name__)

_DEFAULT_POLL_INTERVAL_SEC = 30.0
_DEFAULT_SESSION_WINDOW_HOURS = 5.0
_DEFAULT_DATA_DIR = "~/.claude"
_WEEK_SECONDS = 7 * 24 * 3600
_SOURCE = {"kind": "plugin", "id": "claude_code_usage"}


def register(registry: PluginRegistry) -> None:
    """Plugin entry point. Reads its own config and starts the poller."""
    config = _load_plugin_config()

    poll_interval = float(
        config.get("poll_interval_seconds", _DEFAULT_POLL_INTERVAL_SEC)
    )
    session_window_hours = float(
        config.get("session_window_hours", _DEFAULT_SESSION_WINDOW_HOURS)
    )
    data_dir = Path(str(config.get("data_dir", _DEFAULT_DATA_DIR))).expanduser()

    caps = {
        "session_tokens": _optional_int(config.get("session_token_cap")),
        "week_tokens": _optional_int(config.get("week_token_cap")),
        "week_sonnet_tokens": _optional_int(config.get("week_sonnet_token_cap")),
    }

    poller = UsagePoller(
        registry=registry,
        data_dir=data_dir,
        poll_interval=poll_interval,
        session_window_hours=session_window_hours,
        caps=caps,
    )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # Plugin loaded outside a running loop (e.g. test setup). The caller
        # is responsible for invoking ``poller.poll_once()`` directly.
        logger.debug("no running loop; claude_code_usage poller not scheduled")
        return

    asyncio.create_task(poller.run())


# ---------------------------------------------------------------- poller --


class UsagePoller:
    """Periodically scans Claude Code session logs and publishes usage state."""

    METRIC_SESSION = "session_tokens"
    METRIC_WEEK = "week_tokens"
    METRIC_WEEK_SONNET = "week_sonnet_tokens"

    def __init__(
        self,
        registry: PluginRegistry,
        data_dir: Path,
        poll_interval: float,
        session_window_hours: float,
        caps: dict[str, int | None],
    ) -> None:
        self._registry = registry
        self._data_dir = data_dir
        self._poll_interval = max(1.0, poll_interval)
        self._session_window_sec = max(60.0, session_window_hours * 3600.0)
        self._caps = caps

    async def run(self) -> None:
        while True:
            try:
                await self.poll_once()
            except Exception:
                logger.exception("claude_code_usage poll failed")
            await asyncio.sleep(self._poll_interval)

    async def poll_once(self) -> None:
        now = time.time()
        session_cutoff = now - self._session_window_sec
        week_cutoff = now - _WEEK_SECONDS

        session_tokens = 0
        week_tokens = 0
        week_sonnet_tokens = 0

        for record in _iter_usage_records(self._data_dir, week_cutoff):
            ts = record.timestamp
            tokens = record.tokens
            if ts >= week_cutoff:
                week_tokens += tokens
                if _is_sonnet(record.model):
                    week_sonnet_tokens += tokens
            if ts >= session_cutoff:
                session_tokens += tokens

        updated_at = now
        await self._publish(
            self.METRIC_SESSION,
            label="Session tokens (rolling)",
            current=session_tokens,
            updated_at=updated_at,
        )
        await self._publish(
            self.METRIC_WEEK,
            label="Tokens (7d)",
            current=week_tokens,
            updated_at=updated_at,
        )
        await self._publish(
            self.METRIC_WEEK_SONNET,
            label="Sonnet tokens (7d)",
            current=week_sonnet_tokens,
            updated_at=updated_at,
        )

    async def _publish(
        self, metric_id: str, *, label: str, current: int, updated_at: float
    ) -> None:
        cap = self._caps.get(metric_id)
        percent = (current / cap * 100.0) if (cap and cap > 0) else None
        value = {
            "label": label,
            "current": current,
            "max": cap,
            "percent": percent,
            "unit": "tokens",
            "updated_at": updated_at,
        }
        await self._registry.state.set_state(
            f"usage.claude_code.{metric_id}",
            value,
            source=_SOURCE,
        )


# ---------------------------------------------------------------- parsing --


class _UsageRecord:
    """Lightweight value type for a single (timestamp, model, tokens) row."""

    __slots__ = ("timestamp", "model", "tokens")

    def __init__(self, timestamp: float, model: str, tokens: int) -> None:
        self.timestamp = timestamp
        self.model = model
        self.tokens = tokens


def _iter_usage_records(data_dir: Path, week_cutoff: float) -> Iterable[_UsageRecord]:
    """Walk session JSONL files and yield one record per assistant message.

    Files whose mtime is older than the week cutoff are skipped entirely;
    we never need older data for any of the published metrics. Within a
    file we parse line by line and skip anything that isn't a usage-bearing
    assistant record.
    """
    projects_dir = data_dir / "projects"
    if not projects_dir.is_dir():
        return

    for path in projects_dir.rglob("*.jsonl"):
        try:
            if path.stat().st_mtime < week_cutoff:
                continue
        except OSError:
            continue
        yield from _iter_file(path)


def _iter_file(path: Path) -> Iterable[_UsageRecord]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line_no, raw in enumerate(fh, 1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    record = _parse_line(raw)
                except (json.JSONDecodeError, ValueError, TypeError) as exc:
                    logger.debug(
                        "skipping malformed line %d in %s: %s", line_no, path, exc
                    )
                    continue
                if record is not None:
                    yield record
    except OSError as exc:
        logger.debug("could not read %s: %s", path, exc)


def _parse_line(raw: str) -> _UsageRecord | None:
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        return None
    message = obj.get("message")
    if not isinstance(message, dict):
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None

    model = str(message.get("model") or "")
    tokens = _token_total(usage)
    if tokens <= 0:
        return None

    ts = _parse_timestamp(obj.get("timestamp"))
    if ts is None:
        return None

    return _UsageRecord(timestamp=ts, model=model, tokens=tokens)


def _token_total(usage: dict[str, Any]) -> int:
    # Heuristic: input + cache_creation + output. cache_read is excluded
    # because cache reads are not billed at full rate.
    def _int(key: str) -> int:
        try:
            return int(usage.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    return (
        _int("input_tokens")
        + _int("cache_creation_input_tokens")
        + _int("output_tokens")
    )


def _parse_timestamp(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    try:
        # Python's fromisoformat in 3.11+ accepts the trailing 'Z' suffix
        # via replace, the explicit conversion below keeps it portable.
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def _is_sonnet(model: str) -> bool:
    return "sonnet" in model.lower()


# ------------------------------------------------------------- config ----


def _load_plugin_config() -> dict[str, Any]:
    """Read the plugin's own ``[plugins.claude_code_usage]`` block from config.toml."""
    config_file = os.getenv("DECKHAND_CONFIG_FILE")
    if not config_file and Path("config.toml").exists():
        config_file = "config.toml"
    if not config_file:
        return {}
    full = load_config(config_file)
    plugins = full.get("plugins", {})
    section = plugins.get("claude_code_usage", {}) if isinstance(plugins, dict) else {}
    return section if isinstance(section, dict) else {}


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None
