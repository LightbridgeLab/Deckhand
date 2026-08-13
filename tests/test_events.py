"""Tests for event bus subscription and emission."""

from __future__ import annotations

import asyncio

import pytest

from deckhand.orchestrator.events import EventBus, build_error_event, build_event


async def test_websocket_subscription() -> None:
    """Test WebSocket subscription/unsubscription."""
    bus = EventBus()
    received = []

    class MockWebSocket:
        async def accept(self) -> None:
            pass

        async def send_json(self, data: dict) -> None:
            received.append(data)

    ws1 = MockWebSocket()
    ws2 = MockWebSocket()

    await bus.subscribe(ws1)
    await bus.subscribe(ws2)

    event = build_event("test.event", {"kind": "test", "id": "1"}, {"data": "value"})
    await bus.emit(event)

    await asyncio.sleep(0.01)
    assert len(received) == 2

    bus.unsubscribe(ws1)
    event2 = build_event("test.event2", {"kind": "test", "id": "2"}, {})
    await bus.emit(event2)

    await asyncio.sleep(0.01)
    assert len(received) == 3  # Only ws2 received the second event


async def test_event_emission_multiple_subscribers() -> None:
    """Test event emission to multiple subscribers."""
    bus = EventBus()
    received_ws1 = []
    received_ws2 = []

    class MockWebSocket:
        def __init__(self, received_list: list) -> None:
            self.received_list = received_list

        async def accept(self) -> None:
            pass

        async def send_json(self, data: dict) -> None:
            self.received_list.append(data)

    ws1 = MockWebSocket(received_ws1)
    ws2 = MockWebSocket(received_ws2)

    await bus.subscribe(ws1)
    await bus.subscribe(ws2)

    event = build_event("test.event", {"kind": "test", "id": "1"}, {"data": "value"})
    await bus.emit(event)

    await asyncio.sleep(0.01)
    assert len(received_ws1) == 1
    assert len(received_ws2) == 1
    assert received_ws1[0] == received_ws2[0]


async def test_dead_subscriber_cleanup() -> None:
    """Test dead subscriber cleanup."""
    bus = EventBus()
    received = []

    class MockWebSocket:
        def __init__(self, should_fail: bool = False) -> None:
            self.should_fail = should_fail

        async def accept(self) -> None:
            pass

        async def send_json(self, data: dict) -> None:
            if self.should_fail:
                raise RuntimeError("Connection closed")
            received.append(data)

    ws1 = MockWebSocket(should_fail=True)
    ws2 = MockWebSocket(should_fail=False)

    await bus.subscribe(ws1)
    await bus.subscribe(ws2)

    event = build_event("test.event", {"kind": "test", "id": "1"}, {})
    await bus.emit(event)

    await asyncio.sleep(0.01)
    assert len(received) == 1  # Only ws2 received it
    assert len(bus._subscribers) == 1  # ws1 was removed


async def test_event_envelope_validation() -> None:
    """Test event envelope structure validation."""
    bus = EventBus()

    class MockWebSocket:
        async def accept(self) -> None:
            pass

        async def send_json(self, data: dict) -> None:
            pass

    ws = MockWebSocket()
    await bus.subscribe(ws)

    # Missing required fields
    with pytest.raises(ValueError, match="missing required fields"):
        await bus.emit({"type": "test"})

    # Invalid source structure
    with pytest.raises(ValueError, match="source must have"):
        await bus.emit(
            {
                "type": "test",
                "source": {},
                "payload": {},
                "ts": 123.0,
                "version": "1.0",
            }
        )


async def test_build_error_event() -> None:
    """Test error event building."""
    error_event = build_error_event(
        "ValidationError",
        "Missing required field",
        {"kind": "action", "id": "test.action"},
        {"field": "test_field"},
    )

    assert error_event["type"] == "error"
    assert error_event["version"] == "1.0"
    assert error_event["payload"]["error_type"] == "ValidationError"
    assert error_event["payload"]["message"] == "Missing required field"
    assert error_event["payload"]["details"]["field"] == "test_field"
