"""Signal CLI commands."""

from __future__ import annotations

from deckhand.cli.client import DeckhandClient
from deckhand.cli.formatters import emit_json, parse_payload


def list_(client: DeckhandClient) -> None:
    emit_json(client.list_signals())


def fire(client: DeckhandClient, name: str, payload: str) -> None:
    emit_json(client.fire_signal(name, parse_payload(payload)))
