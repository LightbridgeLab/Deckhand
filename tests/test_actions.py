"""Tests for action registry and routing."""

from __future__ import annotations

import pytest

from deckhand.orchestrator.actions import ActionRegistry


async def test_action_registration(action_registry: ActionRegistry) -> None:
    """Test action registration and listing."""

    async def test_handler(payload: dict[str, object]) -> None:
        pass

    action_registry.register(
        "test.action",
        test_handler,
        description="Test action",
        payload_schema={"test": {"type": "string"}},
    )

    actions = action_registry.list_actions()
    assert len(actions) >= 4  # 3 defaults + 1 test
    assert any(a.name == "test.action" for a in actions)


async def test_action_execution_valid(action_registry: ActionRegistry) -> None:
    """Test action execution with valid payload."""
    executed = []

    async def test_handler(payload: dict[str, object]) -> None:
        executed.append(payload)

    action_registry.register("test.action", test_handler)
    await action_registry.run("test.action", {"key": "value"})
    assert len(executed) == 1
    assert executed[0] == {"key": "value"}


async def test_action_execution_missing_field(action_registry: ActionRegistry) -> None:
    """Test action execution with missing required fields raises ValueError."""
    with pytest.raises(ValueError, match="agent_id is required"):
        await action_registry.run("agent.start", {})


async def test_action_execution_nonexistent(action_registry: ActionRegistry) -> None:
    """Test action execution for non-existent action raises KeyError."""
    with pytest.raises(KeyError):
        await action_registry.run("nonexistent.action", {})


async def test_default_actions(action_registry: ActionRegistry) -> None:
    """Test default actions are registered."""
    actions = action_registry.list_actions()
    action_names = [a.name for a in actions]
    assert "agent.start" in action_names
    assert "agent.cancel" in action_names
    assert "agent.input" in action_names
    assert "ui.focus_agent" in action_names


async def test_agent_start(action_registry: ActionRegistry) -> None:
    """Test agent.start action."""
    await action_registry.run("agent.start", {"agent_id": "mock-1"})


async def test_agent_cancel(action_registry: ActionRegistry) -> None:
    """Test agent.cancel action."""
    await action_registry.run("agent.cancel", {"agent_id": "mock-1"})


async def test_agent_input(action_registry: ActionRegistry) -> None:
    """Test agent.input action."""
    await action_registry.run("agent.input", {"agent_id": "mock-1", "text": "test"})


async def test_action_metadata(action_registry: ActionRegistry) -> None:
    """Test action metadata retrieval."""
    metadata = action_registry.get_action_metadata("agent.start")
    assert metadata is not None
    assert metadata.name == "agent.start"
    assert metadata.description == "Start an agent by ID"
    assert "agent_id" in metadata.payload_schema
