"""Data Widget action handler for the Deckhand OpenDeck plugin.

Maps a Stream Deck button to a Deckhand state key, displaying its
current value and optionally executing an action on press.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import websockets.asyncio.client

from bridge import DeckhandBridge

logger = logging.getLogger("deckhand-action-widget")


class WidgetHandler:
    """Handles com.deckhand.widget action instances."""

    def __init__(self, bridge: DeckhandBridge) -> None:
        self.bridge = bridge
        # context → {"state_key": str, "action_on_press": str, "display_format": str}
        self._watched: dict[str, dict[str, Any]] = {}

    async def on_will_appear(self, ws: websockets.asyncio.client.ClientConnection, context: str, settings: dict[str, Any]) -> None:
        state_key = settings.get("state_key", "")
        action_on_press = settings.get("action_on_press", "")
        display_format = settings.get("display_format", "raw")
        self._watched[context] = {
            "state_key": state_key,
            "action_on_press": action_on_press,
            "display_format": display_format,
        }

        if not state_key:
            await _set_title(ws, context, "No Key")
            return

        # Fetch current value from Deckhand Core
        try:
            entry = await self.bridge.get_state(state_key)
            if entry:
                value = entry.get("value", {})
                title = _format_value(value, display_format)
                await _set_title(ws, context, title)
            else:
                await _set_title(ws, context, "—")
        except Exception:
            logger.exception("Failed to fetch state %s", state_key)
            await _set_title(ws, context, "Offline")

    async def on_will_disappear(self, context: str) -> None:
        self._watched.pop(context, None)

    async def on_key_down(self, ws: websockets.asyncio.client.ClientConnection, context: str, settings: dict[str, Any]) -> None:
        action_name = settings.get("action_on_press", "")
        if not action_name:
            return

        try:
            await self.bridge.execute_action(action_name, {})
        except Exception:
            logger.exception("Widget key action failed: %s", action_name)

    async def on_did_receive_settings(self, ws: websockets.asyncio.client.ClientConnection, context: str, settings: dict[str, Any]) -> None:
        """Settings changed from Property Inspector — re-initialize."""
        await self.on_will_appear(ws, context, settings)

    async def on_send_to_plugin(self, ws: websockets.asyncio.client.ClientConnection, context: str, payload: dict[str, Any]) -> None:
        """Handle Property Inspector requests (e.g., fetch state keys)."""
        request_type = payload.get("type", "")
        if request_type == "getStateKeys":
            try:
                entries = await self.bridge.list_state()
                keys = [e.get("key", "") for e in entries if e.get("key")]
                await _send_to_property_inspector(ws, context, {
                    "type": "stateKeyList",
                    "keys": keys,
                })
            except Exception:
                logger.exception("Failed to fetch state keys for PI")

    async def on_deckhand_event(self, ws: websockets.asyncio.client.ClientConnection, event_type: str, event: dict[str, Any], all_contexts: dict[str, dict[str, Any]]) -> None:
        """Handle events from Deckhand Core."""
        if event_type != "state.changed":
            return

        payload = event.get("payload", {})
        changed_key = payload.get("key", "")

        for context, info in list(self._watched.items()):
            if info.get("state_key") != changed_key:
                continue

            value = payload.get("value", {})
            display_format = info.get("display_format", "raw")
            title = _format_value(value, display_format)

            try:
                await _set_title(ws, context, title)
            except Exception:
                logger.exception("Failed to update widget context %s", context)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_value(value: Any, fmt: str) -> str:
    """Format a state value for display on a button."""
    if fmt == "summary" and isinstance(value, dict) and "title" in value:
        return str(value["title"])[:12]

    if isinstance(value, dict):
        # For dicts, try to find a single scalar value
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


async def _set_title(ws: websockets.asyncio.client.ClientConnection, context: str, title: str) -> None:
    await ws.send(json.dumps({
        "event": "setTitle",
        "context": context,
        "payload": {"title": title},
    }))


async def _send_to_property_inspector(ws: websockets.asyncio.client.ClientConnection, context: str, payload: dict[str, Any]) -> None:
    await ws.send(json.dumps({
        "event": "sendToPropertyInspector",
        "context": context,
        "payload": payload,
    }))
