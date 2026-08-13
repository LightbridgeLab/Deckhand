"""Tests for state store operations and TTL behavior."""

from __future__ import annotations

import asyncio

from deckhand.orchestrator.events import EventBus
from deckhand.orchestrator.state import StateStore


# Shared mock WebSocket that implements both accept() and send_json()
class MockWebSocket:
    """Mock WebSocket for testing EventBus subscriptions."""

    def __init__(self) -> None:
        self.received_events: list[dict] = []

    async def accept(self) -> None:
        """No-op accept method for EventBus.subscribe()."""

    async def send_json(self, data: dict) -> None:
        """Capture events sent to the WebSocket."""
        self.received_events.append(data)


async def test_state_set_get(event_bus: EventBus) -> None:
    """Test state set/get operations."""
    store = StateStore(event_bus)
    await store.set_state("test.key", {"value": 42})
    entry = store.get_state("test.key")
    assert entry is not None
    assert entry["key"] == "test.key"
    assert entry["value"] == {"value": 42}


async def test_state_list(event_bus: EventBus) -> None:
    """Test state list operations."""
    store = StateStore(event_bus)
    await store.set_state("key1", {"a": 1})
    await store.set_state("key2", {"b": 2})
    state_list = store.list_state()
    assert len(state_list) == 2
    keys = {entry["key"] for entry in state_list}
    assert "key1" in keys
    assert "key2" in keys


async def test_state_ttl_expiration(event_bus: EventBus) -> None:
    """Test state TTL expiration."""
    store = StateStore(event_bus)
    await store.set_state("test.key", {"value": 42}, ttl_seconds=0.1)
    entry = store.get_state("test.key")
    assert entry is not None

    # Wait for expiration
    await asyncio.sleep(0.15)
    entry = store.get_state("test.key")
    assert entry is None


async def test_state_changed_event(event_bus: EventBus) -> None:
    """Test state.changed event emission on set."""
    store = StateStore(event_bus)

    mock_ws = MockWebSocket()
    await event_bus.subscribe(mock_ws)

    await store.set_state("test.key", {"value": 42})
    await asyncio.sleep(0.01)  # Allow event to be emitted

    assert len(mock_ws.received_events) == 1
    event = mock_ws.received_events[0]
    assert event["type"] == "state.changed"
    assert event["payload"]["key"] == "test.key"
    assert event["version"] == "1.0"


async def test_state_cleared_event(event_bus: EventBus) -> None:
    """Test state.cleared event emission on clear."""
    store = StateStore(event_bus)

    mock_ws = MockWebSocket()
    await event_bus.subscribe(mock_ws)

    await store.set_state("test.key", {"value": 42})
    await store.clear_state("test.key")
    await asyncio.sleep(0.01)

    assert len(mock_ws.received_events) >= 2
    cleared_event = mock_ws.received_events[-1]
    assert cleared_event["type"] == "state.cleared"
    assert cleared_event["payload"]["key"] == "test.key"


async def test_state_expired_purge_on_list(event_bus: EventBus) -> None:
    """Test expired state purging on list operations."""
    store = StateStore(event_bus)
    await store.set_state("key1", {"a": 1}, ttl_seconds=0.1)
    await store.set_state("key2", {"b": 2})  # No TTL

    await asyncio.sleep(0.15)
    state_list = store.list_state()
    assert len(state_list) == 1
    assert state_list[0]["key"] == "key2"


async def test_state_expired_purge_on_get(event_bus: EventBus) -> None:
    """Test expired state purging on get operations."""
    store = StateStore(event_bus)
    await store.set_state("test.key", {"value": 42}, ttl_seconds=0.1)

    await asyncio.sleep(0.15)
    entry = store.get_state("test.key")
    assert entry is None
