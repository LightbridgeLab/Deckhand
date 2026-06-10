"""Agent CLI commands."""

from __future__ import annotations

from deckhand.cli.client import DeckhandClient
from deckhand.cli.formatters import emit_json


def list_(client: DeckhandClient) -> None:
    emit_json(client.list_agents())


def start(client: DeckhandClient, agent_id: str) -> None:
    emit_json(client.start_agent(agent_id))


def cancel(client: DeckhandClient, agent_id: str) -> None:
    emit_json(client.cancel_agent(agent_id))


def input_(client: DeckhandClient, agent_id: str, text: str) -> None:
    emit_json(client.agent_input(agent_id, text))
