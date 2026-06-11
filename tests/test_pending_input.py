"""Tests for the PendingInputTracker derived-state aggregator."""

from __future__ import annotations

import pytest

from deckhand.agents.base import AgentStatus
from deckhand.agents.mock import MockAgent
from deckhand.agents.pending_input import PendingInputTracker
from deckhand.orchestrator.events import EventBus, build_event
from deckhand.orchestrator.state import StateStore


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def store(bus: EventBus) -> StateStore:
    return StateStore(bus)


@pytest.fixture
def tracker(bus: EventBus, store: StateStore) -> PendingInputTracker:
    t = PendingInputTracker(store)
    bus.add_listener(t)
    return t


def _status_event(agent_id: str, status: str) -> dict:
    return build_event(
        "agent.status_changed",
        {"kind": "agent", "id": agent_id},
        {"agent": {"id": agent_id, "status": status}},
    )


def _unregistered_event(agent_id: str) -> dict:
    return build_event(
        "agent.unregistered",
        {"kind": "agent", "id": agent_id},
        {"agent_id": agent_id, "reason": "session_end"},
    )


async def test_initial_state_empty(
    tracker: PendingInputTracker, store: StateStore
) -> None:
    assert store.get_state(tracker.STATE_LIST_KEY) is None
    assert store.get_state(tracker.STATE_COUNT_KEY) is None
    assert tracker.pending_ids == []


async def test_single_agent_awaiting_appears_in_state(
    bus: EventBus, tracker: PendingInputTracker, store: StateStore
) -> None:
    await bus.emit(_status_event("claude-code-aaa", "awaiting_input"))

    entry = store.get_state(tracker.STATE_LIST_KEY)
    assert entry is not None
    assert entry["value"] == {"agent_ids": ["claude-code-aaa"]}

    count_entry = store.get_state(tracker.STATE_COUNT_KEY)
    assert count_entry is not None
    assert count_entry["value"] == {"count": 1}


async def test_insertion_order_preserved_oldest_first(
    bus: EventBus, tracker: PendingInputTracker, store: StateStore
) -> None:
    await bus.emit(_status_event("agent-a", "awaiting_input"))
    await bus.emit(_status_event("agent-b", "awaiting_input"))
    await bus.emit(_status_event("agent-c", "awaiting_input"))

    entry = store.get_state(tracker.STATE_LIST_KEY)
    assert entry["value"]["agent_ids"] == ["agent-a", "agent-b", "agent-c"]
    assert tracker.pending_ids == ["agent-a", "agent-b", "agent-c"]


async def test_status_transition_away_removes_agent(
    bus: EventBus, tracker: PendingInputTracker, store: StateStore
) -> None:
    await bus.emit(_status_event("agent-a", "awaiting_input"))
    await bus.emit(_status_event("agent-b", "awaiting_input"))
    await bus.emit(_status_event("agent-a", "running"))

    entry = store.get_state(tracker.STATE_LIST_KEY)
    assert entry["value"]["agent_ids"] == ["agent-b"]
    assert store.get_state(tracker.STATE_COUNT_KEY)["value"] == {"count": 1}


async def test_double_awaiting_does_not_duplicate(
    bus: EventBus, tracker: PendingInputTracker, store: StateStore
) -> None:
    await bus.emit(_status_event("agent-a", "awaiting_input"))
    await bus.emit(_status_event("agent-a", "awaiting_input"))

    assert tracker.pending_ids == ["agent-a"]
    assert store.get_state(tracker.STATE_COUNT_KEY)["value"] == {"count": 1}


async def test_unregistration_drops_pending_agent(
    bus: EventBus, tracker: PendingInputTracker, store: StateStore
) -> None:
    await bus.emit(_status_event("agent-a", "awaiting_input"))
    await bus.emit(_status_event("agent-b", "awaiting_input"))
    await bus.emit(_unregistered_event("agent-a"))

    assert tracker.pending_ids == ["agent-b"]
    assert store.get_state(tracker.STATE_LIST_KEY)["value"] == {
        "agent_ids": ["agent-b"]
    }


async def test_unregister_of_unknown_agent_is_noop(
    bus: EventBus, tracker: PendingInputTracker, store: StateStore
) -> None:
    await bus.emit(_status_event("agent-a", "awaiting_input"))
    await bus.emit(_unregistered_event("agent-zzz-unknown"))

    assert tracker.pending_ids == ["agent-a"]


async def test_mid_cycle_resolution_keeps_remaining_pending(
    bus: EventBus, tracker: PendingInputTracker
) -> None:
    """Acceptance scenario: agent resolves while another is still pending."""
    await bus.emit(_status_event("agent-a", "awaiting_input"))
    await bus.emit(_status_event("agent-b", "awaiting_input"))
    # 'agent-a' resolves before we focus it (e.g. user typed in the terminal).
    await bus.emit(_status_event("agent-a", "idle"))
    # Now head should be 'agent-b'.
    assert tracker.pending_ids == ["agent-b"]


async def test_drives_off_real_agent_status_changes(
    bus: EventBus, tracker: PendingInputTracker, store: StateStore
) -> None:
    """Whole-bus integration: a real AgentBase emits via bus → tracker reacts."""
    agent = MockAgent(agent_id="mock-input")
    agent.on_event = bus.emit
    await agent._set_status(AgentStatus.AWAITING_INPUT)
    assert tracker.pending_ids == ["mock-input"]
    await agent._set_status(AgentStatus.IDLE)
    assert tracker.pending_ids == []
