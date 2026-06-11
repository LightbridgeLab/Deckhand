"""Derived state keys for agent integrations (e.g. cursor.summary)."""

from __future__ import annotations

from deckhand.agents.ranking import matches_agent_filter
from deckhand.orchestrator.manager import Orchestrator

_CURSOR_TYPES = frozenset({"cursor", "cursor_cloud"})

_STATUS_EMOJI = {
    "idle": "-",
    "running": ">",
    "awaiting_input": "?",
    "error": "!",
}


def _cursor_agents(orchestrator: Orchestrator) -> list[dict[str, object]]:
    return [a.as_dict() for a in orchestrator.list_agents() if a.type in _CURSOR_TYPES]


def build_cursor_summary_value(agents: list[dict[str, object]]) -> dict[str, object]:
    counts: dict[str, int] = {}
    for agent in agents:
        status = str(agent.get("status", "idle"))
        counts[status] = counts.get(status, 0) + 1

    parts: list[str] = []
    for status in ("running", "awaiting_input", "error", "idle"):
        count = counts.get(status, 0)
        if count > 0:
            parts.append(f"{count}{_STATUS_EMOJI.get(status, '')}")

    return {
        "counts": counts,
        "total": len(agents),
        "title": " ".join(parts) if parts else "No Agents",
        "attention": counts.get("awaiting_input", 0) + counts.get("error", 0),
    }


async def update_cursor_summary(orchestrator: Orchestrator) -> None:
    """Write ``cursor.summary`` from the current cursor agent registry."""
    agents = _cursor_agents(orchestrator)
    await orchestrator.state_store.set_state(
        "cursor.summary",
        build_cursor_summary_value(agents),
        source={"kind": "plugin", "id": "cursor.summary"},
    )


def build_filtered_dashboard_title(
    agents: list[dict[str, object]], agent_filter: str = "*"
) -> str:
    """Compact dashboard title for a filtered agent list."""
    filtered = [a for a in agents if matches_agent_filter(a, agent_filter)]
    if not filtered:
        return "No Agents"

    counts: dict[str, int] = {}
    for agent in filtered:
        status = str(agent.get("status", "idle"))
        counts[status] = counts.get(status, 0) + 1

    parts: list[str] = []
    for status in ("running", "awaiting_input", "error", "idle"):
        count = counts.get(status, 0)
        if count > 0:
            parts.append(f"{count}{_STATUS_EMOJI.get(status, '')}")
    return " ".join(parts) if parts else f"{len(filtered)} agents"
