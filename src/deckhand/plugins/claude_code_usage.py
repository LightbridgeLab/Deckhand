"""Built-in plugin: Claude Code plan-usage metrics for Data Widget buttons.

Polls Anthropic ``GET /api/oauth/usage`` using the Claude Code Keychain OAuth
token and publishes the same percentages Claude's ``/usage`` UI shows:

* ``usage.claude_code.session`` — current 5h session
* ``usage.claude_code.week`` — current week (all models)
* ``usage.claude_code.week_fable`` — current week (Fable), when present
* ``usage.claude_code.credits`` — usage credits, when enabled

Requires ``claude auth login`` on this machine.

Configuration block (all keys optional)::

    [plugins.claude_code_usage]
    oauth_poll_interval_seconds = 60
    oauth_enabled = true

The plugin registers a shutdown hook via :meth:`PluginRegistry.on_shutdown`
so polling tasks are cancelled cleanly when the service stops.

A 429 from Anthropic backs off (Retry-After, then exponential up to 15
minutes) instead of polling every interval. Failed polls seed placeholder
keys so widgets do not 404; later failures keep last-known percentages.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

from deckhand.config.loader import load_config
from deckhand.integrations.claude_oauth import (
    ClaudeOAuthError,
    fetch_plan_bars,
)
from deckhand.integrations.usage_metrics import (
    backoff_poll_delay,
    clamp_poll_interval,
    plan_bar_value,
)
from deckhand.plugins.registry import PluginRegistry

logger = logging.getLogger(__name__)

_DEFAULT_OAUTH_POLL_INTERVAL_SEC = 60.0
_MIN_POLL_INTERVAL_SEC = 1.0
_SOURCE_OAUTH = {"kind": "plugin", "id": "claude_code_plan_usage"}
_PLUGIN_ID = "claude_code_usage"
_SEEDED_KEYS: tuple[tuple[str, str, str], ...] = (
    ("usage.claude_code.session", "Current session", "Session"),
    ("usage.claude_code.week", "Current week (all models)", "Week"),
    ("usage.claude_code.week_fable", "Current week (Fable)", "Fable"),
    ("usage.claude_code.credits", "Usage credits", "Credits"),
)

# Hold a strong reference to every scheduled poller task. asyncio.create_task
# only keeps a weak reference, so without this the task can be garbage-
# collected mid-run. Tasks self-deregister on completion.
_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


def register(registry: PluginRegistry) -> None:
    """Plugin entry point. Reads its own config and starts the plan poller."""
    config = _load_plugin_config()

    oauth_poll_interval = float(
        config.get("oauth_poll_interval_seconds", _DEFAULT_OAUTH_POLL_INTERVAL_SEC)
    )
    oauth_enabled = _optional_bool(config.get("oauth_enabled"), default=True)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # Plugin loaded outside a running loop (e.g. test setup). The caller
        # is responsible for invoking pollers directly.
        logger.debug("no running loop; claude_code_usage pollers not scheduled")
        return

    if not oauth_enabled:
        logger.warning("claude_code_usage: oauth_enabled is false; nothing to poll")
        return

    plan_poller = PlanUsagePoller(
        registry=registry,
        poll_interval=oauth_poll_interval,
    )
    task = asyncio.create_task(plan_poller.run())
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)

    async def _shutdown() -> None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    registry.on_shutdown(_shutdown)


# ---------------------------------------------------------------- poller --


class PlanUsagePoller:
    """Poll Anthropic OAuth usage and publish plan-bar percentages."""

    def __init__(self, registry: PluginRegistry, poll_interval: float) -> None:
        self._registry = registry
        self._poll_interval = clamp_poll_interval(
            "oauth_poll_interval_seconds",
            poll_interval,
            minimum=_MIN_POLL_INTERVAL_SEC,
            log=logger,
            plugin_id=_PLUGIN_ID,
        )
        self._published_keys: set[str] = set()

    async def run(self) -> None:
        consecutive_failures = 0
        async with httpx.AsyncClient(timeout=15.0) as client:
            while True:
                retry_after: float | None = None
                try:
                    await self.poll_once(client)
                    consecutive_failures = 0
                except ClaudeOAuthError as exc:
                    consecutive_failures += 1
                    retry_after = exc.retry_after
                    logger.warning("claude_code_plan_usage: %s", exc)
                    await self._publish_placeholders_if_empty()
                except Exception:
                    consecutive_failures += 1
                    logger.exception("claude_code_plan_usage poll failed")
                    await self._publish_placeholders_if_empty()
                delay = (
                    self._poll_interval
                    if consecutive_failures == 0
                    else backoff_poll_delay(
                        consecutive_failures,
                        self._poll_interval,
                        retry_after,
                    )
                )
                if consecutive_failures:
                    logger.info(
                        "claude_code_plan_usage: backing off %.0fs after %s failure(s)",
                        delay,
                        consecutive_failures,
                    )
                await asyncio.sleep(delay)

    async def poll_once(self, client: httpx.AsyncClient | None = None) -> None:
        bars = await fetch_plan_bars(client)
        updated_at = time.time()
        seen: set[str] = set()
        for bar in bars:
            seen.add(bar.key)
            value = plan_bar_value(
                label=bar.label,
                short_label=bar.short_label,
                percent=bar.percent,
                resets_at=bar.resets_at,
                updated_at=updated_at,
                available=bar.available,
            )
            await self._registry.state.set_state(
                bar.key,
                value,
                source=_SOURCE_OAUTH,
            )
        self._published_keys = seen

    async def _publish_placeholders_if_empty(self) -> None:
        """Seed widget keys on first failure so GET /state does not 404.

        Later failures keep last-known percentages (a 429 should not blank
        a working button).
        """
        if self._published_keys:
            return
        updated_at = time.time()
        for key, label, short in _SEEDED_KEYS:
            await self._registry.state.set_state(
                key,
                plan_bar_value(
                    label=label,
                    short_label=short,
                    percent=None,
                    resets_at=None,
                    updated_at=updated_at,
                    available=False,
                ),
                source=_SOURCE_OAUTH,
            )
        self._published_keys = {key for key, _, _ in _SEEDED_KEYS}


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


def _optional_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("1", "true", "yes", "on"):
            return True
        if normalized in ("0", "false", "no", "off"):
            return False
    return bool(value)
