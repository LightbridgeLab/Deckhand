"""Derived state: which agents are currently ``awaiting_input``.

Subscribes to the event bus and maintains two state keys:

- ``agents.pending_input`` → ``{"agent_ids": [...]}`` in insertion order
  (the agent who entered ``awaiting_input`` first appears first).
- ``agents.pending_input_count`` → ``{"count": N}`` — the same length,
  exposed as a separate key so a Stream Deck button can bind a simple
  numeric formatter without parsing the list.

The tracker observes ``agent.status_changed`` (to add / remove agents)
and ``agent.unregistered`` (to drop sessions that ended mid-wait). State
is rebuilt in-memory from scratch on each Deckhand restart; the first
relevant event after restart re-populates the keys.
"""

from __future__ import annotations

import logging
from typing import Any

from deckhand.orchestrator.state import StateStore

logger = logging.getLogger(__name__)

_AWAITING_INPUT = "awaiting_input"


class PendingInputTracker:
    """EventBus listener that derives the pending-input state keys."""

    STATE_LIST_KEY = "agents.pending_input"
    STATE_COUNT_KEY = "agents.pending_input_count"

    def __init__(self, state_store: StateStore) -> None:
        self._state_store = state_store
        # Insertion-ordered: first agent to enter awaiting_input is first out.
        self._pending: list[str] = []

    @property
    def pending_ids(self) -> list[str]:
        """Snapshot of the current pending list (oldest first)."""
        return list(self._pending)

    async def __call__(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "agent.status_changed":
            await self._handle_status(event)
        elif event_type == "agent.unregistered":
            await self._handle_unregistered(event)

    async def _handle_status(self, event: dict[str, Any]) -> None:
        payload = event.get("payload") or {}
        agent = payload.get("agent") or {}
        agent_id = agent.get("id")
        status = agent.get("status")
        if not agent_id or not status:
            return

        if status == _AWAITING_INPUT:
            if agent_id in self._pending:
                return  # already tracked
            self._pending.append(agent_id)
        else:
            if agent_id not in self._pending:
                return
            self._pending.remove(agent_id)

        await self._publish()

    async def _handle_unregistered(self, event: dict[str, Any]) -> None:
        payload = event.get("payload") or {}
        agent_id = payload.get("agent_id")
        if not agent_id or agent_id not in self._pending:
            return
        self._pending.remove(agent_id)
        await self._publish()

    async def _publish(self) -> None:
        source = {"kind": "tracker", "id": "agents.pending_input"}
        await self._state_store.set_state(
            self.STATE_LIST_KEY,
            {"agent_ids": list(self._pending)},
            source=source,
        )
        await self._state_store.set_state(
            self.STATE_COUNT_KEY,
            {"count": len(self._pending)},
            source=source,
        )
