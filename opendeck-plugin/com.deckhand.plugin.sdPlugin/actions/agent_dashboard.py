"""Agent Dashboard action handler for the Deckhand OpenDeck plugin.

Shows a summary of agents on one button. Press focuses the highest-priority
agent when attention is needed; otherwise refreshes the summary.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import websockets.asyncio.client

from actions.agent_ranking import (
    needs_attention,
    top_attention_agent,
)
from bridge import DeckhandBridge

logger = logging.getLogger("deckhand-action-dashboard")

_STATUS_EMOJI = {
    "idle": "-",
    "running": ">",
    "awaiting_input": "?",
    "error": "!",
}


def _dashboard_title(agents: list[dict[str, Any]], agent_filter: str) -> str:
    filtered = [a for a in agents if agent_filter in ("", "*") or a.get("type") == agent_filter]
    if not filtered:
        return "No Agents"

    counts: dict[str, int] = {}
    for agent in filtered:
        status = agent.get("status", "idle")
        counts[status] = counts.get(status, 0) + 1

    parts: list[str] = []
    for status in ("running", "awaiting_input", "error", "idle"):
        count = counts.get(status, 0)
        if count > 0:
            parts.append(f"{count}{_STATUS_EMOJI.get(status, '')}")

    return " ".join(parts) if parts else f"{len(filtered)} agents"


class AgentDashboardHandler:
    """Handles com.deckhand.agent.dashboard action instances."""

    def __init__(self, bridge: DeckhandBridge) -> None:
        self.bridge = bridge
        self._contexts: dict[str, dict[str, Any]] = {}

    async def on_will_appear(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        settings: dict[str, Any],
    ) -> None:
        self._contexts[context] = {"settings": dict(settings)}
        await self._refresh(ws, context, settings)

    async def on_will_disappear(self, context: str) -> None:
        self._contexts.pop(context, None)

    async def on_key_down(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        settings: dict[str, Any],
    ) -> None:
        agent_filter = settings.get("agent_filter") or "*"
        try:
            agents = await self.bridge.list_agents()
        except Exception:
            logger.exception("Dashboard: failed to fetch agents on press")
            return

        if needs_attention(agents, agent_filter):
            top = top_attention_agent(agents, agent_filter)
            if top is None:
                await self._refresh(ws, context, settings)
                return
            agent_id = top.get("id", "")
            agent_type = top.get("type", "")
            try:
                if agent_type in ("cursor", "cursor_cloud"):
                    await self.bridge.execute_action(
                        "ui.focus_cursor_agent",
                        {"agent_id": agent_id},
                    )
                elif top.get("status") == "awaiting_input":
                    default_input = settings.get("default_input", "")
                    await self.bridge.provide_input(agent_id, default_input)
                elif top.get("status") == "error":
                    await self.bridge.start_agent(agent_id)
                else:
                    await self.bridge.start_agent(agent_id)
            except Exception:
                logger.exception("Dashboard focus action failed for %s", agent_id)
            return

        await self._refresh(ws, context, settings)

    async def on_did_receive_settings(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        settings: dict[str, Any],
    ) -> None:
        self._contexts[context] = {"settings": dict(settings)}
        await self._refresh(ws, context, settings)

    async def on_send_to_plugin(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        payload: dict[str, Any],
    ) -> None:
        pass

    async def on_deckhand_event(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        event_type: str,
        event: dict[str, Any],
        all_contexts: dict[str, dict[str, Any]],
    ) -> None:
        if event_type not in (
            "agent.status_changed",
            "agent.context_changed",
            "agent.registered",
            "agent.unregistered",
        ):
            return

        for context, info in list(self._contexts.items()):
            settings = info.get("settings", {})
            try:
                await self._refresh(ws, context, settings)
            except Exception:
                logger.exception("Failed to refresh dashboard %s", context)

    async def _refresh(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        settings: dict[str, Any],
    ) -> None:
        agent_filter = settings.get("agent_filter") or "*"
        try:
            agents = await self.bridge.list_agents()
        except Exception:
            logger.exception("Dashboard: failed to fetch agents")
            await _set_title(ws, context, "Offline")
            return

        title = _dashboard_title(agents, agent_filter)
        await _set_title(ws, context, title)


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
