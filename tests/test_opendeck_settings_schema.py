"""OpenDeck action settings schema and Property Inspector field parity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "docs" / "opendeck-action-settings.json"
PI_DIR = (
    REPO_ROOT / "opendeck-plugin" / "com.deckhand.plugin.sdPlugin" / "propertyInspector"
)


def test_schema_has_all_actions() -> None:
    schema = json.loads(SCHEMA_PATH.read_text())
    expected = {
        "com.deckhand.agent.status",
        "com.deckhand.agent.slot",
        "com.deckhand.widget",
        "com.deckhand.signal.trigger",
        "com.deckhand.action.run",
        "com.deckhand.agent.dashboard",
    }
    assert set(schema) == expected


@pytest.mark.parametrize(
    ("action_uuid", "pi_file"),
    [
        ("com.deckhand.agent.status", "agent_status.html"),
        ("com.deckhand.agent.slot", "agent_slot.html"),
        ("com.deckhand.widget", "widget.html"),
        ("com.deckhand.signal.trigger", "signal_trigger.html"),
        ("com.deckhand.action.run", "action_run.html"),
        ("com.deckhand.agent.dashboard", "agent_dashboard.html"),
    ],
)
def test_pi_html_contains_schema_fields(action_uuid: str, pi_file: str) -> None:
    schema = json.loads(SCHEMA_PATH.read_text())
    entry = schema[action_uuid]
    html = (PI_DIR / pi_file).read_text()
    assert entry["property_inspector"] == f"propertyInspector/{pi_file}"
    for field_name in entry.get("fields", {}):
        assert field_name in html, f"{field_name} missing from {pi_file}"
