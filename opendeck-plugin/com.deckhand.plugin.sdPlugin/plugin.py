"""Deckhand OpenDeck plugin — main entry point.

Parses OpenDeck CLI args, connects to the OpenDeck WebSocket,
connects to Deckhand Core, and translates events between them.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import websockets
import websockets.asyncio.client

from actions.action_run import ActionRunHandler
from actions.agent_dashboard import AgentDashboardHandler
from actions.agent_slot import AgentSlotHandler
from actions.agent_status import AgentStatusHandler
from actions.signal_trigger import SignalTriggerHandler
from actions.widget import WidgetHandler
from bridge import DeckhandBridge
from client_config import resolve_connection
from diagnostics import PluginDiagnostics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("deckhand-plugin")

# ---------------------------------------------------------------------------
# Context registry: maps OpenDeck context strings to (action_uuid, settings)
# ---------------------------------------------------------------------------
contexts: dict[str, dict[str, Any]] = {}

# Action handlers keyed by action UUID
ACTION_HANDLERS: dict[str, AgentStatusHandler | WidgetHandler] = {}

# Diagnostics
diag = PluginDiagnostics()


def parse_args() -> argparse.Namespace:
    """Parse OpenDeck CLI arguments."""
    parser = argparse.ArgumentParser(description="Deckhand OpenDeck Plugin")
    parser.add_argument("-port", type=int, required=True, help="WebSocket port")
    parser.add_argument("-pluginUUID", type=str, required=True, help="Plugin UUID")
    parser.add_argument(
        "-registerEvent", type=str, required=True, help="Registration event name"
    )
    parser.add_argument("-info", type=str, required=True, help="JSON info string")
    return parser.parse_args()


async def send_to_opendeck(
    ws: websockets.asyncio.client.ClientConnection,
    event: str,
    context: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Send an event to OpenDeck."""
    msg: dict[str, Any] = {"event": event, "context": context}
    if payload is not None:
        msg["payload"] = payload
    await ws.send(json.dumps(msg))
    diag.record_sent()


async def handle_opendeck_event(
    ws: websockets.asyncio.client.ClientConnection,
    data: dict[str, Any],
    bridge: DeckhandBridge,
) -> None:
    """Dispatch an incoming OpenDeck event to the appropriate handler."""
    diag.record_opendeck_event()

    event = data.get("event", "")
    action = data.get("action", "")
    context = data.get("context", "")
    settings = data.get("payload", {}).get("settings", {})

    try:
        if event == "willAppear":
            contexts[context] = {"action": action, "settings": settings}
            diag.active_contexts = len(contexts)
            handler = ACTION_HANDLERS.get(action)
            if handler:
                await handler.on_will_appear(ws, context, settings)

        elif event == "willDisappear":
            contexts.pop(context, None)
            diag.active_contexts = len(contexts)
            handler = ACTION_HANDLERS.get(action)
            if handler:
                await handler.on_will_disappear(context)

        elif event == "keyDown":
            handler = ACTION_HANDLERS.get(action)
            if handler:
                await handler.on_key_down(ws, context, settings)

        elif event == "keyUp":
            pass  # No action on key up for now

        elif event == "didReceiveSettings":
            contexts[context] = {"action": action, "settings": settings}
            handler = ACTION_HANDLERS.get(action)
            if handler:
                await handler.on_did_receive_settings(ws, context, settings)

        elif event == "sendToPlugin":
            payload = data.get("payload", {})
            # Handle diagnostics request from any PI
            if payload.get("type") == "getDiagnostics":
                diag.deckhand_connected = bridge.connected
                await ws.send(
                    json.dumps(
                        {
                            "event": "sendToPropertyInspector",
                            "context": context,
                            "payload": {"type": "diagnostics", "data": diag.as_dict()},
                        }
                    )
                )
                return

            handler = ACTION_HANDLERS.get(action)
            if handler and hasattr(handler, "on_send_to_plugin"):
                await handler.on_send_to_plugin(ws, context, payload)

    except Exception as exc:
        diag.record_error(str(exc))
        logger.exception("Error handling OpenDeck event %s", event)


async def handle_deckhand_event(
    ws: websockets.asyncio.client.ClientConnection, event: dict[str, Any]
) -> None:
    """Forward a Deckhand Core event to all relevant OpenDeck contexts."""
    diag.record_deckhand_event()
    event_type = event.get("type", "")

    for handler in ACTION_HANDLERS.values():
        try:
            await handler.on_deckhand_event(ws, event_type, event, contexts)
        except Exception as exc:
            diag.record_error(str(exc))
            logger.exception("Error forwarding Deckhand event %s", event_type)


async def deckhand_listener(
    ws: websockets.asyncio.client.ClientConnection, bridge: DeckhandBridge
) -> None:
    """Subscribe to Deckhand Core events and forward them.

    Reconnection is handled inside bridge.subscribe_events with exponential backoff.
    """

    async def on_event(event: dict[str, Any]) -> None:
        diag.deckhand_connected = True
        await handle_deckhand_event(ws, event)

    await bridge.subscribe_events(on_event)


async def main() -> None:
    args = parse_args()

    # Resolve connection settings: env var → [client] in shared config.toml
    # → legacy deckhand.env (deprecated). See client_config.py for details.
    core_url, api_key = resolve_connection(Path(__file__).parent)
    bridge = DeckhandBridge(base_url=core_url, api_key=api_key)
    info = json.loads(args.info) if args.info else {}
    logger.info(
        "Starting Deckhand plugin (port=%d, uuid=%s)", args.port, args.pluginUUID
    )
    logger.info("Deckhand Core URL: %s", core_url)
    logger.info("OpenDeck info: %s", json.dumps(info, indent=2))

    # Initialize action handlers
    ACTION_HANDLERS["com.deckhand.agent.status"] = AgentStatusHandler(bridge)
    ACTION_HANDLERS["com.deckhand.widget"] = WidgetHandler(bridge)
    ACTION_HANDLERS["com.deckhand.signal.trigger"] = SignalTriggerHandler(bridge)
    ACTION_HANDLERS["com.deckhand.action.run"] = ActionRunHandler(bridge)
    ACTION_HANDLERS["com.deckhand.agent.dashboard"] = AgentDashboardHandler(bridge)
    ACTION_HANDLERS["com.deckhand.agent.slot"] = AgentSlotHandler(bridge)

    uri = f"ws://127.0.0.1:{args.port}"
    async with websockets.asyncio.client.connect(uri) as ws:
        # Register with OpenDeck
        registration = json.dumps(
            {
                "event": args.registerEvent,
                "uuid": args.pluginUUID,
            }
        )
        await ws.send(registration)
        logger.info("Registered with OpenDeck")

        # Start Deckhand Core event listener in background
        deckhand_task = asyncio.create_task(deckhand_listener(ws, bridge))

        try:
            async for raw in ws:
                try:
                    data = json.loads(raw)
                    logger.debug("OpenDeck -> %s", data.get("event", "unknown"))
                    await handle_opendeck_event(ws, data, bridge)
                except json.JSONDecodeError:
                    diag.record_error(f"Invalid JSON: {raw[:50]}")
                    logger.warning("Invalid JSON from OpenDeck: %s", raw)
        finally:
            deckhand_task.cancel()
            await bridge.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
