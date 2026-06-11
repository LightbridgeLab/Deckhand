"""Signal Trigger action handler for the Deckhand OpenDeck plugin.

Fires a configured Deckhand signal when the button is pressed.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import websockets.asyncio.client

from bridge import DeckhandBridge

logger = logging.getLogger("deckhand-action-signal")


class SignalTriggerHandler:
    """Handles com.deckhand.signal.trigger action instances."""

    def __init__(self, bridge: DeckhandBridge) -> None:
        self.bridge = bridge

    async def on_will_appear(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        settings: dict[str, Any],
    ) -> None:
        signal_name = settings.get("signal_name", "")
        if signal_name:
            await _set_title(ws, context, signal_name.split(".")[-1])
        else:
            await _set_title(ws, context, "No Signal")

    async def on_will_disappear(self, context: str) -> None:
        pass

    async def on_key_down(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        settings: dict[str, Any],
    ) -> None:
        signal_name = settings.get("signal_name", "")
        if not signal_name:
            return

        payload_str = settings.get("signal_payload", "")
        try:
            payload = json.loads(payload_str) if payload_str else {}
        except json.JSONDecodeError:
            payload = {}
            logger.warning(
                "Invalid JSON payload for signal %s: %s", signal_name, payload_str
            )

        try:
            await self.bridge.send_signal(signal_name, payload)
            await _set_title(ws, context, "Sent!")
            # Reset title after a short delay
            import asyncio

            await asyncio.sleep(0.5)
            await _set_title(ws, context, signal_name.split(".")[-1])
        except Exception:
            logger.exception("Failed to send signal %s", signal_name)
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
        """Handle Property Inspector requests (e.g., fetch signal list)."""
        if payload.get("type") == "getSignals":
            try:
                session = await self.bridge._get_session()
                async with session.get(f"{self.bridge.base_url}/signals") as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                await _send_to_property_inspector(
                    ws,
                    context,
                    {
                        "type": "signalList",
                        "signals": data.get("signals", []),
                    },
                )
            except Exception:
                logger.exception("Failed to fetch signals for PI")

    async def on_deckhand_event(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        event_type: str,
        event: dict[str, Any],
        all_contexts: dict[str, dict[str, Any]],
    ) -> None:
        pass  # Signal trigger doesn't react to Deckhand events


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
