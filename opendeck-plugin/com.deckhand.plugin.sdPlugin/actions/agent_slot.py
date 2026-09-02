"""Agent Slot action — dynamically binds a fixed slot to a priority-ranked agent."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import websockets.asyncio.client
from audio import DEFAULT_SOUND, play_sound
from bridge import DeckhandBridge

from actions.agent_ranking import agent_for_slot
from actions.agent_status import (
    STATUS_INDEX,
    STATUS_TITLES,
    _set_state,
    _set_title,
    handle_awaiting_input_press,
)

logger = logging.getLogger("deckhand-action-slot")

_SPINNER_FRAMES = ("Running", "Running.", "Running..", "Running...")
_SPINNER_INTERVAL = 0.45


class AgentSlotHandler:
    """Handles com.deckhand.agent.slot action instances."""

    def __init__(self, bridge: DeckhandBridge) -> None:
        self.bridge = bridge
        self._contexts: dict[str, dict[str, Any]] = {}
        self._spinner_tasks: dict[str, asyncio.Task[None]] = {}

    async def on_will_appear(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        settings: dict[str, Any],
    ) -> None:
        self._contexts[context] = {"settings": dict(settings)}
        await self._refresh(ws, context, settings)

    async def on_deckhand_connected(
        self, ws: websockets.asyncio.client.ClientConnection
    ) -> None:
        """Re-sync all active slot instances when Deckhand Core connects."""
        for context, info in list(self._contexts.items()):
            settings = info.get("settings", {})
            try:
                await self._refresh(ws, context, settings)
            except Exception:
                logger.exception("Failed to refresh agent slot %s on connect", context)

    async def on_will_disappear(self, context: str) -> None:
        self._stop_spinner(context)
        self._contexts.pop(context, None)

    async def on_key_down(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        settings: dict[str, Any],
    ) -> None:
        agent = await self._bound_agent(settings)
        if agent is None:
            return

        agent_id = agent.get("id", "")
        agent_type = agent.get("type", "")
        status = agent.get("status", "idle")

        try:
            if agent_type in ("cursor", "cursor_cloud"):
                await self.bridge.execute_action(
                    "ui.focus_cursor_agent",
                    {"agent_id": agent_id},
                )
                return

            if status == "idle":
                await self.bridge.start_agent(agent_id)
            elif status == "running":
                await self.bridge.cancel_agent(agent_id)
            elif status == "awaiting_input":
                default_input = settings.get("default_input", "")
                await handle_awaiting_input_press(self.bridge, agent, default_input)
            elif status == "error":
                await self.bridge.start_agent(agent_id)
        except Exception:
            logger.exception("Slot key action failed for agent %s", agent_id)

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
        if payload.get("type") == "previewSound":
            name = str(payload.get("sound_name") or DEFAULT_SOUND)
            await play_sound(name)

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
                logger.exception("Failed to refresh slot %s", context)

    async def _bound_agent(self, settings: dict[str, Any]) -> dict[str, Any] | None:
        slot_index = int(settings.get("slot_index") or 1)
        page = int(settings.get("page") or 1)
        agent_filter = settings.get("agent_filter") or "cursor"
        try:
            agents = await self.bridge.list_agents()
        except Exception:
            logger.exception("Slot: failed to fetch agents")
            return None
        return agent_for_slot(
            agents,
            slot_index,
            page=page,
            agent_filter=agent_filter,
        )

    async def _refresh(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        settings: dict[str, Any],
    ) -> None:
        agent = await self._bound_agent(settings)

        if agent is None:
            self._stop_spinner(context)
            if context in self._contexts:
                self._contexts[context]["last_status"] = None
            await _set_state(ws, context, STATUS_INDEX["idle"])
            await _set_title(ws, context, "—")
            return

        status = agent.get("status", "idle")
        label = agent.get("display_label", agent.get("id", ""))
        title = STATUS_TITLES.get(status, "") or label
        state_idx = STATUS_INDEX.get(status, 0)

        info = self._contexts.get(context)
        previous = info.get("last_status") if info else None
        if info is not None and "last_status" not in info:
            info["last_status"] = status
        else:
            if (
                status == "awaiting_input"
                and previous != "awaiting_input"
                and settings.get("sounds_enabled", True)
            ):
                sound = settings.get("sound_name") or DEFAULT_SOUND
                if sound:
                    await play_sound(sound)
            if info is not None:
                info["last_status"] = status

        await _set_state(ws, context, state_idx)
        await _set_title(ws, context, title)

        if status == "running":
            self._start_spinner(ws, context, label)
        else:
            self._stop_spinner(context)

    def _start_spinner(
        self,
        ws: websockets.asyncio.client.ClientConnection,
        context: str,
        label: str,
    ) -> None:
        self._stop_spinner(context)

        async def _spin() -> None:
            frame = 0
            while context in self._contexts:
                title = _SPINNER_FRAMES[frame % len(_SPINNER_FRAMES)]
                try:
                    await _set_title(ws, context, title)
                except Exception:
                    logger.exception("Spinner title update failed for %s", context)
                    break
                frame += 1
                await asyncio.sleep(_SPINNER_INTERVAL)

        self._spinner_tasks[context] = asyncio.create_task(_spin())

    def _stop_spinner(self, context: str) -> None:
        task = self._spinner_tasks.pop(context, None)
        if task and not task.done():
            task.cancel()
