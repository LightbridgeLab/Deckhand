"""Tests for ClaudeCodeAgent and its hook-event mapping."""

from __future__ import annotations

import pytest

from deckhand.agents.base import AgentStatus
from deckhand.agents.claude_code import ClaudeCodeAgent
from deckhand.orchestrator.manager import Orchestrator


async def _drain(agent: ClaudeCodeAgent) -> list[dict]:
    events: list[dict] = []

    async def handler(event: dict) -> None:
        events.append(event)

    agent.on_event = handler
    return events


async def test_initial_state_is_idle() -> None:
    agent = ClaudeCodeAgent(
        agent_id="claude-code-abc12345",
        session_id="abc12345-full",
        project_root="/tmp/proj",
    )
    assert agent.status == AgentStatus.IDLE
    assert agent.type == "claude_code"
    assert "cancellable" in agent.capabilities
    assert agent.as_dict()["session_id"] == "abc12345-full"


@pytest.mark.parametrize(
    "event_name,expected",
    [
        ("UserPromptSubmit", AgentStatus.RUNNING),
        ("PreToolUse", AgentStatus.RUNNING),
        ("Notification", AgentStatus.AWAITING_INPUT),
        ("Stop", AgentStatus.IDLE),
        ("SessionStart", AgentStatus.IDLE),
    ],
)
async def test_hook_event_mapping(event_name: str, expected: AgentStatus) -> None:
    agent = ClaudeCodeAgent(agent_id="c1", session_id="s1")
    # Force a non-target starting state where possible so the transition is real
    if expected != AgentStatus.RUNNING:
        agent.status = AgentStatus.RUNNING
    else:
        agent.status = AgentStatus.IDLE
    events = await _drain(agent)
    await agent.apply_hook_event(event_name)
    assert agent.status == expected
    assert any(e["type"] == "agent.status_changed" for e in events)


async def test_unknown_hook_event_is_noop() -> None:
    agent = ClaudeCodeAgent(agent_id="c1", session_id="s1")
    agent.status = AgentStatus.RUNNING
    events = await _drain(agent)
    await agent.apply_hook_event("SomethingUnknown")
    assert agent.status == AgentStatus.RUNNING
    assert events == []


async def test_no_event_emitted_when_status_unchanged() -> None:
    agent = ClaudeCodeAgent(agent_id="c1", session_id="s1")
    agent.status = AgentStatus.RUNNING
    events = await _drain(agent)
    await agent.apply_hook_event("PreToolUse")  # already RUNNING
    assert events == []


async def test_provide_input_not_implemented() -> None:
    agent = ClaudeCodeAgent(agent_id="c1", session_id="s1")
    with pytest.raises(NotImplementedError):
        await agent.provide_input("hello")


async def test_cancel_transitions_to_idle_and_emits() -> None:
    agent = ClaudeCodeAgent(agent_id="c1", session_id="s1")
    agent.status = AgentStatus.RUNNING
    events = await _drain(agent)
    await agent.cancel()
    assert agent.status == AgentStatus.IDLE
    event_types = [e["type"] for e in events]
    assert "agent.status_changed" in event_types
    assert "agent.cancelled" in event_types


async def test_start_is_noop_from_idle() -> None:
    agent = ClaudeCodeAgent(agent_id="c1", session_id="s1")
    events = await _drain(agent)
    await agent.start()
    # start() is a no-op from IDLE — no status change, no events
    assert agent.status == AgentStatus.IDLE
    assert events == []


async def test_start_recovers_from_error() -> None:
    agent = ClaudeCodeAgent(agent_id="c1", session_id="s1")
    agent.status = AgentStatus.ERROR
    events = await _drain(agent)
    await agent.start()
    assert agent.status == AgentStatus.IDLE
    assert any(e["type"] == "agent.status_changed" for e in events)


async def test_orchestrator_multi_instance_isolation() -> None:
    orch = Orchestrator()
    a1 = ClaudeCodeAgent(
        agent_id="claude-code-aaaaaaaa",
        session_id="aaaaaaaa",
        project_root="/tmp/alpha",
    )
    a2 = ClaudeCodeAgent(
        agent_id="claude-code-bbbbbbbb",
        session_id="bbbbbbbb",
        project_root="/tmp/beta",
    )
    orch.register_agent(a1)
    orch.register_agent(a2)

    assert orch.get_agent(a1.id) is a1
    assert orch.get_agent(a2.id) is a2
    assert a1.display_label != a2.display_label

    await a1.apply_hook_event("UserPromptSubmit")
    assert a1.status == AgentStatus.RUNNING
    assert a2.status == AgentStatus.IDLE


async def test_orchestrator_unregister_agent() -> None:
    orch = Orchestrator()
    agent = ClaudeCodeAgent(agent_id="c1", session_id="s1")
    orch.register_agent(agent)
    assert orch.get_agent("c1") is agent

    removed = orch.unregister_agent("c1")
    assert removed is agent
    assert orch.get_agent("c1") is None
    assert agent.on_event is None

    # Unregistering a missing id is a no-op returning None
    assert orch.unregister_agent("c1") is None
