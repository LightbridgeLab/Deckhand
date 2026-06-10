"""Tests for agent priority ranking."""

from __future__ import annotations

from deckhand.agents.ranking import (
    agent_for_slot,
    needs_attention,
    rank_agents,
    top_attention_agent,
)


def _agent(agent_id: str, status: str, updated_at: float, agent_type: str = "cursor") -> dict:
    return {
        "id": agent_id,
        "type": agent_type,
        "status": status,
        "updated_at": updated_at,
    }


def test_rank_agents_priority_order() -> None:
    agents = [
        _agent("a", "idle", 100),
        _agent("b", "running", 90),
        _agent("c", "awaiting_input", 80),
        _agent("d", "error", 70),
    ]
    ranked = rank_agents(agents, "cursor")
    assert [a["id"] for a in ranked] == ["c", "d", "b", "a"]


def test_agent_for_slot_respects_page() -> None:
    agents = [_agent(f"a{i}", "running", float(i)) for i in range(10)]
    first = agent_for_slot(agents, 1, page=1, per_page=7, agent_filter="cursor")
    eighth = agent_for_slot(agents, 1, page=2, per_page=7, agent_filter="cursor")
    assert first is not None and first["id"] == "a9"
    assert eighth is not None and eighth["id"] == "a2"


def test_needs_attention() -> None:
    agents = [_agent("a", "running", 1), _agent("b", "idle", 2)]
    assert not needs_attention(agents, "cursor")
    agents[1]["status"] = "awaiting_input"
    assert needs_attention(agents, "cursor")


def test_top_attention_agent_prefers_input() -> None:
    agents = [
        _agent("running", "running", 100),
        _agent("input", "awaiting_input", 50),
    ]
    top = top_attention_agent(agents, "cursor")
    assert top is not None
    assert top["id"] == "input"
