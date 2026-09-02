"""Data Widget action handler for the Deckhand OpenDeck plugin.

Maps a Stream Deck button to a Deckhand state key, displaying its
current value and optionally peeking reset time and/or executing an
action on press.

Usage bars that publish ``resets_at`` can briefly flash time-until-reset
on press (``Xd Yh`` or ``Xh Ym``). Duration comes from
``[client].usage_reset_flash_seconds`` (default 5; 0 disables). Press
behavior is controlled by ``press_mode`` (peek | action | both | none).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

import websockets.asyncio.client
from bridge import DeckhandBridge
from client_config import load_state_key_catalog, load_usage_reset_flash_seconds
from widget_images import (
    catalog_image_for_key,
    image_data_uri,
    resolve_image_path,
)

logger = logging.getLogger("deckhand-action-widget")

_VALID_PRESS_MODES = frozenset({"peek", "action", "both", "none"})
_VALID_FORMATS = frozenset(
    {"raw", "currency", "percentage", "boolean", "number", "summary"}
)


def _normalize_press_mode(raw: Any) -> str:
    """Return a valid press mode; missing/unknown defaults to peek."""
    if isinstance(raw, str) and raw.strip().lower() in _VALID_PRESS_MODES:
        return raw.strip().lower()
    return "peek"


def _sort_catalog_by_label(entries: list[dict[str, str]]) -> list[dict[str, str]]:
    """Sort catalog rows by dropdown_label (case-insensitive) for the PI."""
    return sorted(
        entries,
        key=lambda e: (e.get("dropdown_label") or e.get("key") or "").casefold(),
    )


def _catalog_row_from_item(item: Any) -> dict[str, str] | None:
    """Normalize a Core/local catalog item into a PI row dict."""
    if isinstance(item, str) and item.strip():
        key = item.strip()
        return {"key": key, "dropdown_label": key}
    if not isinstance(item, dict) or not isinstance(item.get("key"), str):
        return None
    key = item["key"].strip()
    if not key:
        return None
    dropdown = item.get("dropdown_label")
    if not isinstance(dropdown, str) or not dropdown.strip():
        dropdown = key
    row: dict[str, str] = {"key": key, "dropdown_label": dropdown.strip()}
    if isinstance(item.get("image"), str) and item["image"].strip():
        row["image"] = item["image"].strip()
    fmt = item.get("format")
    if isinstance(fmt, str) and fmt.strip().lower() in _VALID_FORMATS:
        row["format"] = fmt.strip().lower()
    title = item.get("button_title")
    if isinstance(title, str) and title.strip():
        row["button_title"] = title.strip()
    return row


class WidgetHandler:
    """Handles com.deckhand.widget action instances."""

    def __init__(self, bridge: DeckhandBridge) -> None:
        self.bridge = bridge
        # context → settings snapshot + cached value
        self._watched: dict[str, dict[str, Any]] = {}
        # context → flash restore task
        self._flash_tasks: dict[str, asyncio.Task[Any]] = {}

    async def on_will_appear(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        settings: dict[str, Any],
    ) -> None:
        await self._cancel_flash(context)
        state_key = settings.get("state_key", "")
        action_on_press = settings.get("action_on_press", "")
        action_payload = settings.get("action_payload", "")
        display_format = settings.get("display_format", "raw")
        button_title = settings.get("button_title", "") or ""
        press_mode = _normalize_press_mode(settings.get("press_mode"))
        self._watched[context] = {
            "state_key": state_key,
            "action_on_press": action_on_press,
            "action_payload": action_payload,
            "display_format": display_format,
            "button_title": button_title,
            "press_mode": press_mode,
            "value": None,
        }

        await self._apply_catalog_image(ws, context, state_key)

        if not state_key:
            await _set_title(ws, context, "No Key")
            return

        # Fetch current value from Deckhand Core
        try:
            entry = await self.bridge.get_state(state_key)
            if entry:
                value = entry.get("value", {})
                self._watched[context]["value"] = value
                title = _format_value(value, display_format, button_title)
                await _set_title(ws, context, title)
            else:
                await _set_title(ws, context, "—")
        except Exception:
            logger.exception("Failed to fetch state %s", state_key)
            await _set_title(ws, context, "Offline")

    async def on_deckhand_connected(
        self, ws: websockets.asyncio.client.ClientConnection
    ) -> None:
        """Re-sync all active widget instances when Deckhand Core connects."""
        for context, watched in list(self._watched.items()):
            state_key = watched.get("state_key", "")
            if not state_key:
                continue
            display_format = watched.get("display_format", "raw")
            button_title = watched.get("button_title", "") or ""
            await self._apply_catalog_image(ws, context, state_key)
            try:
                entry = await self.bridge.get_state(state_key)
                if entry:
                    value = entry.get("value", {})
                    watched["value"] = value
                    title = _format_value(value, display_format, button_title)
                    await _set_title(ws, context, title)
                else:
                    await _set_title(ws, context, "—")
            except Exception:
                logger.exception("Failed to re-sync state %s on connect", state_key)
                await _set_title(ws, context, "Offline")

    async def _apply_catalog_image(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        state_key: str,
    ) -> None:
        """Set the button face from catalog ``image`` (provider mark or path)."""
        try:
            entries = await self._catalog_entries()
            image_name = (
                catalog_image_for_key(state_key, entries) if state_key else "blank"
            )
            path = resolve_image_path(image_name)
            await _set_image(ws, context, image_data_uri(path))
        except Exception:
            logger.exception("Failed to set widget image for %s", state_key)

    async def _catalog_entries(self) -> list[dict[str, str]]:
        local_entries, _ = load_state_key_catalog()
        if local_entries:
            return local_entries
        try:
            payload = await self.bridge.list_state_key_catalog()
            raw = payload.get("entries") if isinstance(payload, dict) else []
            if not isinstance(raw, list):
                return []
            entries: list[dict[str, str]] = []
            for item in raw:
                row = _catalog_row_from_item(item)
                if row:
                    entries.append(row)
            return entries
        except Exception:
            logger.exception("Failed to load catalog for widget image")
            return []

    async def on_will_disappear(self, context: str) -> None:
        await self._cancel_flash(context)
        self._watched.pop(context, None)

    async def on_key_down(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        settings: dict[str, Any],
    ) -> None:
        press_mode = _normalize_press_mode(
            settings.get("press_mode")
            or (self._watched.get(context) or {}).get("press_mode")
        )

        if press_mode in ("action", "both"):
            await self._run_configured_action(ws, context, settings)

        if press_mode in ("peek", "both"):
            await self._maybe_flash_reset(ws, context, settings)

    async def _run_configured_action(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        settings: dict[str, Any],
    ) -> None:
        action_name = settings.get("action_on_press", "")
        if not action_name:
            return

        payload_str = settings.get("action_payload", "")
        if not payload_str and context in self._watched:
            payload_str = self._watched[context].get("action_payload", "") or ""
        try:
            payload = json.loads(payload_str) if payload_str else {}
            if not isinstance(payload, dict):
                payload = {}
        except json.JSONDecodeError:
            payload = {}
            logger.warning(
                "Invalid JSON payload for widget action %s: %s",
                action_name,
                payload_str,
            )

        try:
            await self.bridge.execute_action(action_name, payload)
        except Exception:
            logger.exception("Widget key action failed: %s", action_name)
            try:
                await _set_title(ws, context, "Error")
                await asyncio.sleep(0.8)
                info = self._watched.get(context)
                if info is not None:
                    value = info.get("value")
                    fmt = info.get("display_format", "raw")
                    title = (
                        "—"
                        if value is None
                        else _format_value(value, fmt, info.get("button_title", ""))
                    )
                    await _set_title(ws, context, title)
            except Exception:
                logger.exception("Failed to show action error on widget %s", context)

    async def _maybe_flash_reset(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        settings: dict[str, Any],
    ) -> None:
        flash_seconds = load_usage_reset_flash_seconds()
        if flash_seconds <= 0:
            return

        info = self._watched.get(context)
        state_key = (info or {}).get("state_key") or settings.get("state_key", "")
        display_format = (info or {}).get("display_format") or settings.get(
            "display_format", "raw"
        )
        button_title = (info or {}).get("button_title") or settings.get(
            "button_title", ""
        )
        value = (info or {}).get("value") if info else None

        if value is None and state_key:
            try:
                entry = await self.bridge.get_state(state_key)
                if entry:
                    value = entry.get("value", {})
                    if info is not None:
                        info["value"] = value
            except Exception:
                logger.exception("Failed to fetch state for reset flash: %s", state_key)
                return

        if not isinstance(value, dict):
            return
        flash_title = format_reset_flash_title(value, button_title)
        if flash_title is None:
            return

        await self._cancel_flash(context)
        try:
            await _set_title(ws, context, flash_title)
        except Exception:
            logger.exception("Failed to set reset flash title for %s", context)
            return

        async def _restore() -> None:
            try:
                await asyncio.sleep(flash_seconds)
                latest = self._watched.get(context)
                if latest is None:
                    return
                restore_value = latest.get("value")
                restore_fmt = latest.get("display_format", display_format)
                if restore_value is None:
                    title = "—"
                else:
                    title = _format_value(
                        restore_value,
                        restore_fmt,
                        latest.get("button_title", ""),
                    )
                await _set_title(ws, context, title)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Failed to restore widget title after flash")
            finally:
                self._flash_tasks.pop(context, None)

        self._flash_tasks[context] = asyncio.create_task(_restore())

    async def _cancel_flash(self, context: str) -> None:
        task = self._flash_tasks.pop(context, None)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def on_did_receive_settings(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        settings: dict[str, Any],
    ) -> None:
        """Settings changed from Property Inspector — re-initialize."""
        await self.on_will_appear(ws, context, settings)

    async def on_send_to_plugin(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        payload: dict[str, Any],
    ) -> None:
        """Handle Property Inspector requests (e.g., fetch state keys / actions)."""
        request_type = payload.get("type", "")
        if request_type == "getActions":
            try:
                actions = await self.bridge.list_actions()
                await _send_to_property_inspector(
                    ws,
                    context,
                    {"type": "actionList", "actions": actions},
                )
            except Exception as exc:
                logger.exception("Failed to fetch actions for widget PI")
                await _send_to_property_inspector(
                    ws,
                    context,
                    {
                        "type": "actionList",
                        "actions": [],
                        "error": str(exc),
                    },
                )
            return

        if request_type == "getStateKeys":
            local_entries, local_path = load_state_key_catalog()
            if local_entries:
                await _send_to_property_inspector(
                    ws,
                    context,
                    {
                        "type": "stateKeyList",
                        "keys": _sort_catalog_by_label(local_entries),
                        "source": "local",
                        "config": local_path,
                    },
                )
                return

            # OpenDeck's cwd is usually the Plugins folder, so project-local
            # config.toml is invisible. Fall back to Core, which loaded the
            # same catalog from its own config path.
            try:
                catalog_payload = await self.bridge.list_state_key_catalog()
                raw = (
                    catalog_payload.get("entries")
                    if isinstance(catalog_payload, dict)
                    else []
                )
                entries: list[dict[str, str]] = []
                if isinstance(raw, list):
                    for item in raw:
                        row = _catalog_row_from_item(item)
                        if row:
                            entries.append(row)
                message: dict[str, Any] = {
                    "type": "stateKeyList",
                    "keys": _sort_catalog_by_label(entries),
                    "source": "core",
                    "config": catalog_payload.get("config")
                    if isinstance(catalog_payload, dict)
                    else None,
                    "local_config": local_path,
                }
                if not entries:
                    message["hint"] = (
                        "Core returned an empty [catalog.state_keys]. "
                        "Run: uv run deckhand catalog sync"
                    )
                await _send_to_property_inspector(ws, context, message)
            except Exception as exc:
                logger.exception("Failed to load state key catalog for PI")
                await _send_to_property_inspector(
                    ws,
                    context,
                    {
                        "type": "stateKeyList",
                        "keys": [],
                        "error": str(exc),
                        "local_config": local_path,
                        "hint": (
                            "No local [catalog.state_keys] visible to the plugin "
                            "(OpenDeck cwd often cannot see project config.toml). "
                            "Put the catalog in ~/.config/deckhand/config.toml, "
                            "set DECKHAND_CONFIG_FILE, or ensure Deckhand Core is "
                            "running with the catalog loaded."
                        ),
                    },
                )

    async def on_deckhand_event(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        event_type: str,
        event: dict[str, Any],
        all_contexts: dict[str, dict[str, Any]],
    ) -> None:
        """Handle events from Deckhand Core."""
        if event_type != "state.changed":
            return

        payload = event.get("payload", {})
        changed_key = payload.get("key", "")

        for context, info in list(self._watched.items()):
            if info.get("state_key") != changed_key:
                continue

            value = payload.get("value", {})
            info["value"] = value
            # Keep flashing title until the timer restores.
            if context in self._flash_tasks:
                continue

            display_format = info.get("display_format", "raw")
            title = _format_value(value, display_format, info.get("button_title", ""))

            try:
                await _set_title(ws, context, title)
            except Exception:
                logger.exception("Failed to update widget context %s", context)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def format_reset_remaining(
    resets_at: str, *, now: datetime | None = None
) -> str | None:
    """Format time until ``resets_at`` as ``Xd Yh`` (>=1 day) or ``Xh Ym``."""
    text = resets_at.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        target = datetime.fromisoformat(text)
    except ValueError:
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=UTC)
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    delta = target - current
    total_seconds = int(delta.total_seconds())
    if total_seconds <= 0:
        return None
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days >= 1:
        return f"{days}d {hours}h"
    return f"{hours}h {minutes}m"


def _first_line(value: dict[str, Any], button_title: str = "") -> str | None:
    """Button first line: configured title, else live ``short_label``."""
    if isinstance(button_title, str) and button_title.strip():
        return button_title.strip()[:8]
    short = value.get("short_label")
    if isinstance(short, str) and short.strip():
        return short.strip()[:8]
    return None


def format_reset_flash_title(
    value: dict[str, Any], button_title: str = ""
) -> str | None:
    """Build ``{first_line}\\n{Xd Yh|Xh Ym}`` when ``resets_at`` is usable."""
    resets_at = value.get("resets_at")
    if not isinstance(resets_at, str) or not resets_at.strip():
        return None
    remaining = format_reset_remaining(resets_at)
    if remaining is None:
        return None
    first = _first_line(value, button_title)
    if first:
        return f"{first}\n{remaining}"
    return remaining


def _format_value(value: Any, fmt: str, button_title: str = "") -> str:
    """Format a state value for display on a button."""
    if fmt == "summary" and isinstance(value, dict) and "title" in value:
        return str(value["title"])[:16]

    # Normalized metric shape (e.g. usage.claude_code.*):
    # { label, short_label?, current, max, percent, unit, updated_at, title? }
    if isinstance(value, dict) and ("current" in value or "percent" in value):
        if fmt == "percentage":
            first = _first_line(value, button_title)
            pct = value.get("percent")
            if pct is None:
                return f"{first}\n—" if first else "—"
            if first:
                try:
                    return f"{first}\n{float(pct):.0f}%"
                except (TypeError, ValueError):
                    return f"{first}\n—"
            try:
                return f"{float(pct):.0f}%"
            except (TypeError, ValueError):
                return "—"
        if fmt == "summary":
            title = value.get("title")
            if title is not None:
                return str(title)[:16]
            first = _first_line(value, button_title)
            if first:
                return first[:12]
            label = value.get("label")
            if label is not None:
                return str(label)[:12]
            if value.get("current") is not None:
                value = value["current"]
            else:
                return "—"
        elif "current" in value and value.get("current") is not None:
            # number, raw, currency, boolean → use current
            value = value["current"]
        else:
            return "—"
    elif isinstance(value, dict):
        # For other dicts, try to find a single scalar value
        if len(value) == 1:
            value = next(iter(value.values()))
        else:
            return json.dumps(value)[:12]

    if fmt == "currency" and isinstance(value, (int, float)):
        return f"${value:,.2f}"

    if fmt == "percentage":
        try:
            num = float(value)
            return f"{num:.0f}%"
        except (TypeError, ValueError):
            pass

    if fmt == "boolean":
        truthy = value in (True, 1, "true", "True", "1", "yes", "on")
        return "\u2713" if truthy else "\u2717"

    if fmt == "number":
        try:
            num = float(value)
            if num == int(num):
                return f"{int(num):,}"
            return f"{num:,.2f}"
        except (TypeError, ValueError):
            pass

    return str(value)[:12]


async def _set_title(
    ws: websockets.asyncio.client.ClientConnection, context: str, title: str
) -> None:
    await ws.send(
        json.dumps(
            {
                "event": "setTitle",
                "context": context,
                "payload": {"title": title},
            }
        )
    )


async def _set_image(
    ws: websockets.asyncio.client.ClientConnection, context: str, image: str
) -> None:
    await ws.send(
        json.dumps(
            {
                "event": "setImage",
                "context": context,
                "payload": {"image": image, "target": 0},
            }
        )
    )


async def _send_to_property_inspector(
    ws: websockets.asyncio.client.ClientConnection,
    context: str,
    payload: dict[str, Any],
) -> None:
    await ws.send(
        json.dumps(
            {
                "event": "sendToPropertyInspector",
                "context": context,
                "payload": payload,
            }
        )
    )
