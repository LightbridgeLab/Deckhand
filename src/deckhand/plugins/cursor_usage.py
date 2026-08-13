"""Built-in plugin: Cursor plan/spend bars for Data Widget buttons.

Reads the Cursor IDE JWT from ``state.vscdb`` and polls
``GetCurrentPeriodUsage`` on ``api2.cursor.sh`` (same source as
https://cursor.com/dashboard/spending). Publishes Claude-shaped plan-bar
keys:

* ``usage.cursor.models`` — Cursor Models pool (used %)
* ``usage.cursor.other`` — Other Models pool (used %)
* ``usage.cursor.on_demand`` — On-demand spend vs hard limit (used %)

Requires Cursor signed in on this machine (local ``state.vscdb`` auth).

Configuration block (all keys optional)::

    [plugins.cursor_usage]
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
from deckhand.integrations.cursor_usage import (
    CursorUsageError,
    fetch_plan_bars,
)
from deckhand.integrations.usage_metrics import clamp_poll_interval, plan_bar_value
from deckhand.plugins.registry import PluginRegistry

logger = logging.getLogger(__name__)

_DEFAULT_POLL_INTERVAL_SEC = 60.0
_MIN_POLL_INTERVAL_SEC = 1.0
_SOURCE = {"kind": "plugin", "id": "cursor_usage"}
_PLUGIN_ID = "cursor_usage"
_SEEDED_KEYS = (
    "usage.cursor.models",
    "usage.cursor.other",
    "usage.cursor.on_demand",
)
_KEY_META: dict[str, tuple[str, str]] = {
    "usage.cursor.models": ("Cursor Models", "Models"),
    "usage.cursor.other": ("Other Models", "Other"),
    "usage.cursor.on_demand": ("On-demand", "On-demand"),
}

_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


def register(registry: PluginRegistry) -> None:
    """Plugin entry point. Reads its own config and starts the usage poller."""
    config = _load_plugin_config()

    enabled = _optional_bool(config.get("enabled"), default=True)
    poll_interval = float(
        config.get("poll_interval_seconds", _DEFAULT_POLL_INTERVAL_SEC)
    )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("no running loop; cursor_usage poller not scheduled")
        return

    if not enabled:
        logger.warning("cursor_usage: enabled is false; nothing to poll")
        return

    poller = CursorUsagePoller(
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


class CursorUsagePoller:
    """Poll Cursor spending API and publish plan-bar percentages."""

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
            except CursorUsageError as exc:
                logger.warning("cursor_usage: %s", exc)
                await self._publish_unavailable()
            except Exception:
                logger.exception("cursor_usage poll failed")
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
            label, short = _KEY_META.get(
                stale, (stale.rsplit(".", 1)[-1], stale.rsplit(".", 1)[-1])
            )
            await self._registry.state.set_state(
                stale,
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
        self._published_keys = seen

    async def _publish_unavailable(self) -> None:
        """Mark previously published bars unavailable after a fetch failure."""
        if not self._published_keys:
            self._published_keys = set(_SEEDED_KEYS)
        updated_at = time.time()
        for key in self._published_keys:
            label, short = _KEY_META.get(
                key, (key.rsplit(".", 1)[-1], key.rsplit(".", 1)[-1])
            )
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
    """Read the plugin's own ``[plugins.cursor_usage]`` block."""
    config_file = os.getenv("DECKHAND_CONFIG_FILE")
    if not config_file and Path("config.toml").exists():
        config_file = "config.toml"
    if not config_file:
        return {}
    full = load_config(config_file)
    plugins = full.get("plugins", {})
    section = plugins.get("cursor_usage", {}) if isinstance(plugins, dict) else {}
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
