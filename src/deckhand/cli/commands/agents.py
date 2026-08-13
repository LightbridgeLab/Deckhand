"""Agent CLI commands."""

from __future__ import annotations

from deckhand.cli.client import DeckhandClient
from deckhand.cli.formatters import emit_json

DEMO_AGENT_ID = "demo-1"


def list_(client: DeckhandClient) -> None:
    emit_json(client.list_agents())


def start(client: DeckhandClient, agent_id: str) -> None:
    emit_json(client.start_agent(agent_id))


def cancel(client: DeckhandClient, agent_id: str) -> None:
    emit_json(client.cancel_agent(agent_id))


def input_(client: DeckhandClient, agent_id: str, text: str) -> None:
    emit_json(client.agent_input(agent_id, text))


def demo(client: DeckhandClient, *, remove: bool = False) -> None:
    """Register (or remove) a local MockAgent for Property Inspector testing."""
    if remove:
        emit_json(client.unregister_agent(DEMO_AGENT_ID))
        return
    emit_json(
        client.register_agent(
            {
                "agent_id": DEMO_AGENT_ID,
                "agent_type": "mock",
                "capabilities": ["accepts_text", "cancellable"],
                "project_root": "/tmp/deckhand-demo",
            }
        )
    )
