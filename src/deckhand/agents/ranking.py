"""Priority ordering for ephemeral agent slots and dashboard focus."""

from __future__ import annotations

from typing import Any

STATUS_PRIORITY: dict[str, int] = {
    "awaiting_input": 0,
    "error": 1,
    "running": 2,
    "idle": 3,
}

ATTENTION_STATUSES = frozenset({"awaiting_input", "error"})


def matches_agent_filter(agent: dict[str, Any], agent_filter: str) -> bool:
    if not agent_filter or agent_filter == "*":
        return True
    return agent.get("type") == agent_filter


def rank_agents(
    agents: list[dict[str, Any]], agent_filter: str = "*"
) -> list[dict[str, Any]]:
    """Sort agents for slot assignment: attention first, then most recently updated."""
    filtered = [a for a in agents if matches_agent_filter(a, agent_filter)]
    return sorted(
        filtered,
        key=lambda a: (
            STATUS_PRIORITY.get(str(a.get("status", "idle")), 99),
            -(float(a.get("updated_at") or 0)),
        ),
    )


def agent_for_slot(
    agents: list[dict[str, Any]],
    slot_index: int,
    *,
    page: int = 1,
    per_page: int = 7,
    agent_filter: str = "*",
) -> dict[str, Any] | None:
    """Return the agent bound to a 1-based slot index on the given page."""
    if slot_index < 1:
        return None
    ranked = rank_agents(agents, agent_filter)
    offset = (max(page, 1) - 1) * per_page + slot_index - 1
    if offset >= len(ranked):
        return None
    return ranked[offset]


def needs_attention(agents: list[dict[str, Any]], agent_filter: str = "*") -> bool:
    return any(
        a.get("status") in ATTENTION_STATUSES
        for a in agents
        if matches_agent_filter(a, agent_filter)
    )


def top_attention_agent(
    agents: list[dict[str, Any]], agent_filter: str = "*"
) -> dict[str, Any] | None:
    """Highest-priority agent that needs attention, else the top-ranked agent."""
    ranked = rank_agents(agents, agent_filter)
    if not ranked:
        return None
    for agent in ranked:
        if agent.get("status") in ATTENTION_STATUSES:
            return agent
    return ranked[0]
