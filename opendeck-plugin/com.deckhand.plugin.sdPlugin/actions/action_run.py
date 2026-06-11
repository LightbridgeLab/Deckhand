"""Action Run handler for the Deckhand OpenDeck plugin.

Executes a configured Deckhand action with a fixed payload when pressed.
Universal button for any registered action.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import websockets.asyncio.client

from bridge import DeckhandBridge

logger = logging.getLogger("deckhand-action-run")


class ActionRunHandler:
    """Handles com.deckhand.action.run action instances."""

    def __init__(self, bridge: DeckhandBridge) -> None:
        self.bridge = bridge

    async def on_will_appear(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        settings: dict[str, Any],
    ) -> None:
        action_name = settings.get("action_name", "")
        if action_name:
            await _set_title(ws, context, action_name.split(".")[-1])
        else:
            await _set_title(ws, context, "No Action")

    async def on_will_disappear(self, context: str) -> None:
        pass

    async def on_key_down(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        settings: dict[str, Any],
    ) -> None:
        action_name = settings.get("action_name", "")
        if not action_name:
            return

        payload_str = settings.get("action_payload", "")
        try:
            payload = json.loads(payload_str) if payload_str else {}
        except json.JSONDecodeError:
            payload = {}
            logger.warning(
                "Invalid JSON payload for action %s: %s", action_name, payload_str
            )

        try:
            await self.bridge.execute_action(action_name, payload)
            await _set_title(ws, context, "OK!")
            import asyncio

            await asyncio.sleep(0.5)
            await _set_title(ws, context, action_name.split(".")[-1])
        except Exception:
            logger.exception("Failed to execute action %s", action_name)
            await _set_title(ws, context, "Error")

    async def on_did_receive_settings(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        settings: dict[str, Any],
    ) -> None:
        await self.on_will_appear(ws, context, settings)

    async def on_send_to_plugin(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        payload: dict[str, Any],
    ) -> None:
        """Handle Property Inspector requests (e.g., fetch action list)."""
        if payload.get("type") == "getActions":
            try:
                session = await self.bridge._get_session()
                async with session.get(f"{self.bridge.base_url}/actions") as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                await _send_to_property_inspector(
                    ws,
                    context,
                    {
                        "type": "actionList",
                        "actions": data.get("actions", []),
                    },
                )
            except Exception:
                logger.exception("Failed to fetch actions for PI")

    async def on_deckhand_event(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        event_type: str,
        event: dict[str, Any],
        all_contexts: dict[str, dict[str, Any]],
    ) -> None:
        pass  # Action run doesn't react to Deckhand events


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
