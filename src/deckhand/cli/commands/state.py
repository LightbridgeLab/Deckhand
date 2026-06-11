"""State-store CLI commands."""

from __future__ import annotations

from deckhand.cli.client import DeckhandClient
from deckhand.cli.formatters import emit_json


def list_(client: DeckhandClient) -> None:
    emit_json(client.list_state())


def get(client: DeckhandClient, key: str) -> None:
    emit_json(client.get_state(key))


def watch(client: DeckhandClient, key: str | None) -> None:
    with client.events() as stream:
        for event in stream:
            if event.get("type") != "state.changed":
                continue
            payload = event.get("payload", {})
            if key is not None and payload.get("key") != key:
                continue
            emit_json(event)
