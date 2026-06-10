"""Action CLI commands."""

from __future__ import annotations

from deckhand.cli.client import DeckhandClient
from deckhand.cli.formatters import emit_json, parse_payload


def list_(client: DeckhandClient) -> None:
    emit_json(client.list_actions())


def call(client: DeckhandClient, name: str, payload: str) -> None:
    emit_json(client.call_action(name, parse_payload(payload)))
