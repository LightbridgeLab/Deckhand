"""Tests for CursorAgent and its hook-event mapping."""

from __future__ import annotations

import pytest

from deckhand.agents.base import AgentStatus
from deckhand.agents.cursor import CursorAgent
from deckhand.orchestrator.manager import Orchestrator


async def _drain(agent: CursorAgent) -> list[dict]:
    events: list[dict] = []

    async def handler(event: dict) -> None:
        events.append(event)

    agent.on_event = handler
    return events


async def test_initial_state_is_idle() -> None:
    agent = CursorAgent(
        agent_id="cursor-abc12345",
        session_id="abc12345-full",
        project_root="/tmp/proj",
        title="Fix bug",
    )
    assert agent.status == AgentStatus.IDLE
    assert agent.type == "cursor"
    assert agent.display_label == "Cursor: proj"
    assert agent.as_dict()["session_id"] == "abc12345-full"


@pytest.mark.parametrize(
    "event_name,expected",
    [
        ("beforeSubmitPrompt", AgentStatus.RUNNING),
        ("preToolUse", AgentStatus.RUNNING),
        ("stop", AgentStatus.IDLE),
        ("sessionStart", AgentStatus.IDLE),
        ("postToolUseFailure", AgentStatus.ERROR),
    ],
)
async def test_hook_event_mapping(event_name: str, expected: AgentStatus) -> None:
    agent = CursorAgent(agent_id="c1", session_id="s1")
    if expected != AgentStatus.RUNNING:
        agent.status = AgentStatus.RUNNING
    else:
        agent.status = AgentStatus.IDLE
    events = await _drain(agent)
    await agent.apply_hook_event(event_name)
    assert agent.status == expected
    if expected != AgentStatus.IDLE or event_name in ("stop", "postToolUseFailure"):
        assert any(e["type"] == "agent.status_changed" for e in events)


async def test_deckhand_status_override() -> None:
    agent = CursorAgent(agent_id="c1", session_id="s1")
    await agent.apply_hook_event("preToolUse", deckhand_status="awaiting_input")
    assert agent.status == AgentStatus.AWAITING_INPUT


async def test_provide_input_not_implemented() -> None:
    agent = CursorAgent(agent_id="c1", session_id="s1")
    with pytest.raises(NotImplementedError):
        await agent.provide_input("hello")


async def test_orchestrator_multi_instance_isolation() -> None:
    orch = Orchestrator()
    a1 = CursorAgent(
        agent_id="cursor-aaaaaaaa",
        session_id="aaaaaaaa",
        project_root="/tmp/alpha",
    )
    a2 = CursorAgent(
        agent_id="cursor-bbbbbbbb",
        session_id="bbbbbbbb",
        project_root="/tmp/beta",
    )
    orch.register_agent(a1)
    orch.register_agent(a2)

    await a1.apply_hook_event("beforeSubmitPrompt")
    assert a1.status == AgentStatus.RUNNING
    assert a2.status == AgentStatus.IDLE
