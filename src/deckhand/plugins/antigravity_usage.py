"""Built-in plugin: Antigravity Gemini quota for Data Widget buttons.

Reads the ``agy`` Keychain OAuth token and polls Google Cloud Code
``retrieveUserQuotaSummary`` (same source as ``agy``'s ``/usage`` panel).
Publishes Claude-shaped plan-bar keys:

* ``usage.antigravity.session`` — Gemini five-hour limit (used %)
* ``usage.antigravity.week`` — Gemini weekly limit (used %)

Requires ``agy`` signed in on this Mac (Keychain service ``gemini`` /
account ``antigravity``).

Configuration block (all keys optional)::

    [plugins.antigravity_usage]
    poll_interval_seconds = 60
    enabled = true

The plugin registers a shutdown hook via :meth:`PluginRegistry.on_shutdown`
so polling tasks are cancelled cleanly when the service stops.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any

from deckhand.config.loader import load_config
from deckhand.integrations.antigravity_quota import (
    AntigravityQuotaError,
    fetch_plan_bars,
)
from deckhand.integrations.usage_metrics import clamp_poll_interval, plan_bar_value
from deckhand.plugins.registry import PluginRegistry

logger = logging.getLogger(__name__)

_DEFAULT_POLL_INTERVAL_SEC = 60.0
_MIN_POLL_INTERVAL_SEC = 1.0
_SOURCE = {"kind": "plugin", "id": "antigravity_usage"}
_PLUGIN_ID = "antigravity_usage"
_SEEDED_KEYS = ("usage.antigravity.session", "usage.antigravity.week")

_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


def register(registry: PluginRegistry) -> None:
    """Plugin entry point. Reads its own config and starts the quota poller."""
    config = _load_plugin_config()

    enabled = _optional_bool(config.get("enabled"), default=True)
    poll_interval = float(
        config.get("poll_interval_seconds", _DEFAULT_POLL_INTERVAL_SEC)
    )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("no running loop; antigravity_usage poller not scheduled")
        return

    if not enabled:
        logger.warning("antigravity_usage: enabled is false; nothing to poll")
        return

    poller = AntigravityUsagePoller(
        registry=registry,
        poll_interval=poll_interval,
    )
    task = asyncio.create_task(poller.run())
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)

    async def _shutdown() -> None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    registry.on_shutdown(_shutdown)


class AntigravityUsagePoller:
    """Poll Cloud Code quota and publish Gemini plan-bar percentages."""

    def __init__(
        self,
        registry: PluginRegistry,
        poll_interval: float,
    ) -> None:
        self._registry = registry
        self._poll_interval = clamp_poll_interval(
            "poll_interval_seconds",
            poll_interval,
            minimum=_MIN_POLL_INTERVAL_SEC,
            log=logger,
            plugin_id=_PLUGIN_ID,
        )
        self._published_keys: set[str] = set()

    async def run(self) -> None:
        while True:
            try:
                await self.poll_once()
            except AntigravityQuotaError as exc:
                logger.warning("antigravity_usage: %s", exc)
                await self._publish_unavailable()
            except Exception:
                logger.exception("antigravity_usage poll failed")
                await self._publish_unavailable()
            await asyncio.sleep(self._poll_interval)

    async def poll_once(self) -> None:
        bars = await fetch_plan_bars()
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
            await self._registry.state.set_state(bar.key, value, source=_SOURCE)

        for stale in self._published_keys - seen:
            await self._registry.state.set_state(
                stale,
                plan_bar_value(
                    label=stale.rsplit(".", 1)[-1],
                    short_label=stale.rsplit(".", 1)[-1],
                    percent=None,
                    resets_at=None,
                    updated_at=updated_at,
                    available=False,
                ),
                source=_SOURCE,
            )
        self._published_keys = seen

    async def _publish_unavailable(self) -> None:
        """Mark previously published bars unavailable after a fetch failure."""
        if not self._published_keys:
            self._published_keys = set(_SEEDED_KEYS)
        updated_at = time.time()
        for key in self._published_keys:
            short = "Session" if key.endswith(".session") else "Week"
            if key.endswith(".session"):
                label = "Current session"
            elif key.endswith(".week"):
                label = "Current week"
            else:
                label = short
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
                source=_SOURCE,
            )


def _load_plugin_config() -> dict[str, Any]:
    """Read the plugin's own ``[plugins.antigravity_usage]`` block."""
    config_file = os.getenv("DECKHAND_CONFIG_FILE")
    if not config_file and Path("config.toml").exists():
        config_file = "config.toml"
    if not config_file:
        return {}
    full = load_config(config_file)
    plugins = full.get("plugins", {})
    section = plugins.get("antigravity_usage", {}) if isinstance(plugins, dict) else {}
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
