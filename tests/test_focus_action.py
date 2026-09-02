"""Tests for ui.focus_cursor_agent action."""

from __future__ import annotations

import pytest

from deckhand.agents.cursor import CursorAgent
from deckhand.orchestrator.actions import ActionRegistry
from deckhand.orchestrator.manager import Orchestrator


@pytest.fixture
def orch_with_cursor() -> Orchestrator:
    orch = Orchestrator()
    orch.register_agent(
        CursorAgent(
            agent_id="cursor-test1234",
            session_id="test1234",
            project_root="/tmp/my-app",
        )
    )
    return orch


async def test_focus_emits_ui_open_url(orch_with_cursor: Orchestrator) -> None:
    captured: list[dict] = []
    bus = orch_with_cursor.event_bus
    original_emit = bus.emit

    async def capture_emit(event: dict) -> None:
        captured.append(event)
        await original_emit(event)

    bus.emit = capture_emit  # type: ignore[method-assign]
    registry = ActionRegistry(orch_with_cursor, event_bus=bus)

    await registry.run("ui.focus_cursor_agent", {"agent_id": "cursor-test1234"})

    assert any(e["type"] == "ui.open_url" for e in captured)
    open_events = [e for e in captured if e["type"] == "ui.open_url"]
    assert open_events[0]["payload"]["agent_id"] == "cursor-test1234"


async def test_focus_agent_invokes_registered_focuser() -> None:
    orch = Orchestrator()
    from deckhand.agents.claude_code import ClaudeCodeAgent

    agent = ClaudeCodeAgent(
        agent_id="claude-code-aaaaaaaa",
        session_id="aaaaaaaa",
        project_root="/tmp/p",
    )
    orch.register_agent(agent)
    called: list[str] = []

    async def focuser() -> None:
        called.append("ok")

    orch.register_focuser(agent.id, focuser)
    registry = ActionRegistry(orch)
    await registry.run("ui.focus_agent", {"agent_id": agent.id})
    assert called == ["ok"]


async def test_focus_agent_missing_focuser_is_noop() -> None:
    orch = Orchestrator()
    from deckhand.agents.claude_code import ClaudeCodeAgent

    orch.register_agent(
        ClaudeCodeAgent(agent_id="claude-code-bbbbbbbb", session_id="bbbbbbbb")
    )
    registry = ActionRegistry(orch)
    await registry.run("ui.focus_agent", {"agent_id": "claude-code-bbbbbbbb"})


async def test_focus_agent_unknown_id_raises() -> None:
    registry = ActionRegistry(Orchestrator())
    with pytest.raises(KeyError):
        await registry.run("ui.focus_agent", {"agent_id": "missing"})
