"""Hook simulator: read a JSON payload from stdin and POST it."""

from __future__ import annotations

import json
import sys

from deckhand.cli.client import DeckhandClient
from deckhand.cli.formatters import emit_error, emit_json


def simulate(client: DeckhandClient, agent_type: str) -> None:
    raw = sys.stdin.read()
    if not raw.strip():
        emit_error("expected a JSON hook payload on stdin")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        emit_error(f"invalid JSON on stdin: {exc}")

    if agent_type == "claude-code":
        emit_json(client.post_claude_code_hook(payload))
    elif agent_type == "cursor":
        emit_json(client.post_cursor_hook(payload))
    else:
        emit_error(
            f"unknown agent type {agent_type!r} (expected 'claude-code' or 'cursor')"
        )
