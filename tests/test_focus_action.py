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
