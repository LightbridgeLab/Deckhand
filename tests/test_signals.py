"""Tests for signal registry and handling."""

from __future__ import annotations

import pytest

from deckhand.orchestrator.signals import SignalRegistry


async def test_signal_registration(signal_registry: SignalRegistry) -> None:
    """Test signal registration and listing."""

    async def test_handler(payload: dict[str, object]) -> None:
        pass

    signal_registry.register(
        "test.signal",
        test_handler,
        description="Test signal",
        payload_schema={"test": {"type": "string"}},
    )

    signals = signal_registry.list_signals()
    assert len(signals) == 1
    assert signals[0].name == "test.signal"


async def test_signal_handling_valid(signal_registry: SignalRegistry) -> None:
    """Test signal handling with valid payload."""
    handled = []

    async def test_handler(payload: dict[str, object]) -> None:
        handled.append(payload)

    signal_registry.register("test.signal", test_handler)
    await signal_registry.handle("test.signal", {"key": "value"})
    assert len(handled) == 1
    assert handled[0] == {"key": "value"}


async def test_signal_handling_invalid(signal_registry: SignalRegistry) -> None:
    """Test signal handling with invalid payload."""

    async def test_handler(payload: dict[str, object]) -> None:
        if "required_field" not in payload:
            raise ValueError("required_field is required")

    signal_registry.register("test.signal", test_handler)
    with pytest.raises(ValueError, match="required_field is required"):
        await signal_registry.handle("test.signal", {})


async def test_signal_handling_nonexistent(signal_registry: SignalRegistry) -> None:
    """Test signal handling for non-existent signal raises KeyError."""
    with pytest.raises(KeyError):
        await signal_registry.handle("nonexistent.signal", {})


async def test_signal_metadata(signal_registry: SignalRegistry) -> None:
    """Test signal metadata retrieval."""

    async def test_handler(payload: dict[str, object]) -> None:
        pass

    signal_registry.register(
        "test.signal",
        test_handler,
        description="Test signal",
        payload_schema={"key": {"type": "string"}},
    )

    metadata = signal_registry.get_signal_metadata("test.signal")
    assert metadata is not None
    assert metadata.name == "test.signal"
    assert metadata.description == "Test signal"
    assert "key" in metadata.payload_schema
