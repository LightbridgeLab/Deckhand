"""Agent Status action handler for the Deckhand OpenDeck plugin.

Maps a Stream Deck button to a Deckhand agent, showing its status
and allowing interaction (start / cancel / provide input).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import websockets.asyncio.client
from audio import DEFAULT_SOUND, play_sound
from bridge import DeckhandBridge

logger = logging.getLogger("deckhand-action-agent")

# Agent status → OpenDeck state index (matches manifest States array order)
STATUS_INDEX = {
    "idle": 0,
    "running": 1,
    "awaiting_input": 2,
    "error": 3,
}

STATUS_TITLES = {
    "idle": "",  # Show agent name when idle
    "running": "Running",
    "awaiting_input": "Input!",
    "error": "Error",
}

# Auto-retry defaults
_RETRY_DELAY = 5.0  # seconds before retry
_RETRY_MAX_ATTEMPTS = 3


class AgentStatusHandler:
    """Handles com.deckhand.agent.status action instances."""

    def __init__(self, bridge: DeckhandBridge) -> None:
        self.bridge = bridge
        # context → {"agent_id": str, "sounds_enabled": bool, ...}
        self._watched: dict[str, dict[str, Any]] = {}
        # context → asyncio.Task for pending retry
        self._retry_tasks: dict[str, asyncio.Task[None]] = {}

    async def on_will_appear(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        settings: dict[str, Any],
    ) -> None:
        agent_id = settings.get("agent_id", "")
        sounds_enabled = settings.get("sounds_enabled", True)
        sound_name = settings.get("sound_name") or DEFAULT_SOUND
        auto_retry = settings.get("auto_retry", False)
        retry_max = settings.get("retry_max", _RETRY_MAX_ATTEMPTS)
        self._watched[context] = {
            "agent_id": agent_id,
            "sounds_enabled": sounds_enabled,
            "sound_name": sound_name,
            "auto_retry": auto_retry,
            "retry_max": retry_max,
            "retry_count": 0,
            "last_status": None,
        }

        if not agent_id:
            await _set_title(ws, context, "No Agent")
            return

        # Fetch current status from Deckhand Core
        try:
            agents = await self.bridge.list_agents()
            agent = next((a for a in agents if a.get("id") == agent_id), None)
            if agent:
                status = agent.get("status", "idle")
                self._watched[context]["last_status"] = status
                label = agent.get("display_label", agent.get("id", agent_id))
                title = STATUS_TITLES.get(status, "") or label
                await _set_state(ws, context, STATUS_INDEX.get(status, 0))
                await _set_title(ws, context, title)
            else:
                await _set_title(ws, context, "Not Found")
        except Exception:
            logger.exception("Failed to fetch agent %s", agent_id)
            await _set_title(ws, context, "Offline")

    async def on_deckhand_connected(
        self, ws: websockets.asyncio.client.ClientConnection
    ) -> None:
        """Re-sync all active agent status instances when Deckhand Core connects."""
        if not self._watched:
            return
        try:
            agents = await self.bridge.list_agents()
        except Exception:
            logger.exception("Failed to fetch agents on connect")
            return

        for context, watched in list(self._watched.items()):
            agent_id = watched.get("agent_id", "")
            if not agent_id:
                continue
            agent = next((a for a in agents if a.get("id") == agent_id), None)
            if agent:
                status = agent.get("status", "idle")
                watched["last_status"] = status
                label = agent.get("display_label", agent.get("id", agent_id))
                title = STATUS_TITLES.get(status, "") or label
                await _set_state(ws, context, STATUS_INDEX.get(status, 0))
                await _set_title(ws, context, title)
            else:
                await _set_title(ws, context, "Not Found")

    async def on_will_disappear(self, context: str) -> None:
        self._watched.pop(context, None)
        self._cancel_retry(context)

    async def on_key_down(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        settings: dict[str, Any],
    ) -> None:
        agent_id = settings.get("agent_id", "")
        if not agent_id:
            return

        # Determine current status and act accordingly
        try:
            agents = await self.bridge.list_agents()
            agent = next((a for a in agents if a.get("id") == agent_id), None)
            if not agent:
                return

            status = agent.get("status", "idle")
            if status == "idle":
                await self.bridge.start_agent(agent_id)
            elif status == "running":
                await self.bridge.cancel_agent(agent_id)
            elif status == "awaiting_input":
                default_input = settings.get("default_input", "")
                await handle_awaiting_input_press(self.bridge, agent, default_input)
            elif status == "error":
                # Manual press on error state resets retry count and starts agent
                if context in self._watched:
                    self._watched[context]["retry_count"] = 0
                self._cancel_retry(context)
                await self.bridge.start_agent(agent_id)
        except Exception:
            logger.exception("Key action failed for agent %s", agent_id)

    async def on_did_receive_settings(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        settings: dict[str, Any],
    ) -> None:
        """Settings changed from Property Inspector — re-initialize."""
        self._cancel_retry(context)
        await self.on_will_appear(ws, context, settings)

    async def on_send_to_plugin(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        payload: dict[str, Any],
    ) -> None:
        """Handle Property Inspector requests (e.g., fetch agent list)."""
        request_type = payload.get("type", "")
        if request_type == "previewSound":
            name = str(payload.get("sound_name") or DEFAULT_SOUND)
            await play_sound(name)
            return
        if request_type == "getAgents":
            try:
                agents = await self.bridge.list_agents()
                await _send_to_property_inspector(
                    ws,
                    context,
                    {
                        "type": "agentList",
                        "agents": agents,
                        "core_url": self.bridge.base_url,
                    },
                )
            except Exception as exc:
                logger.exception("Failed to fetch agents for PI")
                await _send_to_property_inspector(
                    ws,
                    context,
                    {
                        "type": "agentList",
                        "agents": [],
                        "error": str(exc) or "Failed to fetch agents",
                        "core_url": self.bridge.base_url,
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
        if event_type not in ("agent.status_changed", "agent.context_changed"):
            return

        payload = event.get("payload", {})
        agent_data = payload.get("agent", {})
        agent_id = agent_data.get("id", "") or payload.get("agent_id", "")
        new_status = agent_data.get("status", "") or payload.get("status", "")
        display_label = agent_data.get("display_label", agent_id)

        for context, info in list(self._watched.items()):
            if info.get("agent_id") != agent_id:
                continue

            state_idx = STATUS_INDEX.get(new_status, 0)
            title = STATUS_TITLES.get(new_status, "") or display_label

            try:
                await _set_state(ws, context, state_idx)
                await _set_title(ws, context, title)

                previous = info.get("last_status")
                if (
                    new_status == "awaiting_input"
                    and previous != "awaiting_input"
                    and info.get("sounds_enabled", True)
                ):
                    sound = info.get("sound_name") or DEFAULT_SOUND
                    if sound:
                        await play_sound(sound)
                if new_status:
                    info["last_status"] = new_status

                # Auto-retry on error
                if new_status == "error" and info.get("auto_retry", False):
                    self._schedule_retry(ws, context, agent_id, info)
                elif new_status != "error":
                    # Success or other state: reset retry count
                    info["retry_count"] = 0
                    self._cancel_retry(context)

            except Exception:
                logger.exception("Failed to update context %s", context)

    # ----- Auto-retry helpers -----

    def _schedule_retry(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        agent_id: str,
        info: dict[str, Any],
    ) -> None:
        """Schedule an auto-retry for a failed agent."""
        retry_count = info.get("retry_count", 0)
        retry_max = info.get("retry_max", _RETRY_MAX_ATTEMPTS)

        if retry_count >= retry_max:
            logger.info("Agent %s: max retries (%d) reached", agent_id, retry_max)
            return

        self._cancel_retry(context)
        info["retry_count"] = retry_count + 1
        delay = _RETRY_DELAY * info["retry_count"]  # Linear backoff

        async def _do_retry() -> None:
            await asyncio.sleep(delay)
            try:
                logger.info(
                    "Auto-retrying agent %s (attempt %d/%d)",
                    agent_id,
                    info["retry_count"],
                    retry_max,
                )
                await self.bridge.start_agent(agent_id)
                await _set_title(ws, context, f"Retry {info['retry_count']}")
            except Exception:
                logger.exception("Auto-retry failed for agent %s", agent_id)

        self._retry_tasks[context] = asyncio.create_task(_do_retry())

    def _cancel_retry(self, context: str) -> None:
        """Cancel a pending retry task for a context."""
        task = self._retry_tasks.pop(context, None)
        if task and not task.done():
            task.cancel()


def accepts_text(agent: dict[str, Any]) -> bool:
    """True when Core can inject Default Input into this agent (demo/mock)."""
    caps = agent.get("capabilities") or []
    return "accepts_text" in caps


async def handle_awaiting_input_press(
    bridge: DeckhandBridge,
    agent: dict[str, Any],
    default_input: str,
) -> None:
    """Send text to agents that accept it; otherwise focus the session."""
    agent_id = str(agent.get("id") or "")
    if not agent_id:
        return
    if accepts_text(agent):
        await bridge.provide_input(agent_id, default_input)
        return
    await bridge.execute_action("ui.focus_agent", {"agent_id": agent_id})


# ---------------------------------------------------------------------------
# OpenDeck helper functions
# ---------------------------------------------------------------------------


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


async def _set_state(
    ws: websockets.asyncio.client.ClientConnection, context: str, state: int
) -> None:
    await ws.send(
        json.dumps(
            {
                "event": "setState",
                "context": context,
                "payload": {"state": state},
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
