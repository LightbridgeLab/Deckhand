"""Tests for the editable [catalog.state_keys] helper."""

from __future__ import annotations

from pathlib import Path

from deckhand.catalog.state_keys import (
    StateKeyEntry,
    load_state_key_entries,
    merge_state_key_entries,
    parse_state_key_entries,
    seed_entries_for_plugins,
    sort_catalog_dicts_by_label,
    sync_state_key_catalog,
    write_state_key_catalog,
)
from deckhand.config.settings import Settings


def test_parse_entries_accepts_dicts_and_strings() -> None:
    entries = parse_state_key_entries(
        {
            "entries": [
                {
                    "key": "usage.claude_code.session",
                    "dropdown_label": "Session",
                    "format": "percentage",
                    "button_title": "Sess",
                },
                "agents.pending_input_count",
                {
                    "key": "usage.claude_code.session",
                    "dropdown_label": "Ignored duplicate",
                },
                {"key": "  "},
                {"key": "bad.format", "format": "nope"},
                {"key": "legacy.label", "label": "Not a catalog field"},
            ]
        }
    )
    assert entries == [
        StateKeyEntry(
            key="usage.claude_code.session",
            dropdown_label="Session",
            format="percentage",
            button_title="Sess",
        ),
        StateKeyEntry(key="agents.pending_input_count"),
        StateKeyEntry(key="bad.format"),
        StateKeyEntry(key="legacy.label"),
    ]


def test_merge_preserves_existing_dropdown_labels() -> None:
    existing = [StateKeyEntry(key="a", dropdown_label="Mine")]
    seeds = [
        StateKeyEntry(key="a", dropdown_label="Seed"),
        StateKeyEntry(key="b", dropdown_label="B"),
    ]
    live = [StateKeyEntry(key="b"), StateKeyEntry(key="c")]
    merged = merge_state_key_entries(existing, seeds, live)
    assert merged == [
        StateKeyEntry(key="a", dropdown_label="Mine"),
        StateKeyEntry(key="b", dropdown_label="B"),
        StateKeyEntry(key="c"),
    ]


def test_merge_fills_missing_image_format_and_button_title() -> None:
    existing = [
        StateKeyEntry(key="usage.claude_code.session", dropdown_label="My Session")
    ]
    seeds = [
        StateKeyEntry(
            key="usage.claude_code.session",
            dropdown_label="Claude: Session (5h)",
            image="claude",
            format="percentage",
            button_title="Session",
        )
    ]
    merged = merge_state_key_entries(existing, seeds)
    assert merged[0].dropdown_label == "My Session"
    assert merged[0].image == "claude"
    assert merged[0].format == "percentage"
    assert merged[0].button_title == "Session"


def test_merge_preserves_existing_format_and_button_title() -> None:
    existing = [
        StateKeyEntry(
            key="usage.claude_code.credits",
            dropdown_label="Credits",
            format="number",
            button_title="Cred",
        )
    ]
    seeds = [
        StateKeyEntry(
            key="usage.claude_code.credits",
            dropdown_label="Claude: Credits remaining",
            format="percentage",
            button_title="Credits",
        )
    ]
    merged = merge_state_key_entries(existing, seeds)
    assert merged[0].format == "number"
    assert merged[0].button_title == "Cred"


def test_seed_entries_for_plugins() -> None:
    seeds = seed_entries_for_plugins(["deckhand.plugins.claude_code_usage"])
    keys = {e.key for e in seeds}
    assert "usage.claude_code.session" in keys
    assert "agents.pending_input_count" in keys
    assert "usage.antigravity.session" not in keys
    by_key = {e.key: e for e in seeds}
    assert by_key["usage.claude_code.session"].dropdown_label == "Claude: Session (5h)"
    assert by_key["usage.claude_code.session"].format == "percentage"
    assert by_key["usage.claude_code.session"].button_title == "Session"
    assert by_key["usage.claude_code.credits"].format == "percentage"
    assert by_key["agents.pending_input_count"].format == "number"
    assert by_key["cursor.summary"].format == "summary"


def test_seed_entries_for_antigravity() -> None:
    seeds = seed_entries_for_plugins(["deckhand.plugins.antigravity_usage"])
    keys = {e.key for e in seeds}
    assert "usage.antigravity.session" in keys
    assert "usage.antigravity.week" in keys
    assert "usage.antigravity.credits" not in keys
    by_key = {e.key: e for e in seeds}
    assert by_key["usage.antigravity.session"].image == "antigravity"
    assert by_key["usage.antigravity.week"].image == "antigravity"
    assert by_key["usage.antigravity.session"].format == "percentage"


def test_seed_cursor_on_demand_button_title_fits() -> None:
    seeds = seed_entries_for_plugins(["deckhand.plugins.cursor_usage"])
    by_key = {e.key: e for e in seeds}
    assert by_key["usage.cursor.on_demand"].dropdown_label == "Cursor: On-demand"
    assert by_key["usage.cursor.on_demand"].button_title == "Demand"


def test_write_and_load_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        '[service]\nname = "deckhand"\n\n[client]\nurl = "http://127.0.0.1:8000"\n',
        encoding="utf-8",
    )
    write_state_key_catalog(
        path,
        [
            StateKeyEntry(
                key="usage.claude_code.session",
                dropdown_label='Claude "session"',
                image="claude",
                format="percentage",
                button_title="Sess",
            ),
            StateKeyEntry(key="agents.pending_input_count"),
        ],
    )
    text = path.read_text(encoding="utf-8")
    assert '[service]\nname = "deckhand"' in text
    assert '[client]\nurl = "http://127.0.0.1:8000"' in text
    assert "[catalog.state_keys]" in text
    assert 'image = "claude"' in text
    assert 'format = "percentage"' in text
    assert 'dropdown_label = "Claude \\"session\\""' in text
    assert 'button_title = "Sess"' in text

    loaded = load_state_key_entries(path)
    assert loaded[0].key == "usage.claude_code.session"
    assert loaded[0].dropdown_label == 'Claude "session"'
    assert loaded[0].image == "claude"
    assert loaded[0].format == "percentage"
    assert loaded[0].button_title == "Sess"
    assert loaded[1] == StateKeyEntry(key="agents.pending_input_count")


def test_write_replaces_existing_catalog_section(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        "[catalog.state_keys]\n"
        "entries = [\n"
        '  { key = "old.key", dropdown_label = "Old" },\n'
        "]\n\n"
        "[logging]\n"
        'level = "INFO"\n',
        encoding="utf-8",
    )
    write_state_key_catalog(path, [StateKeyEntry(key="new.key", dropdown_label="New")])
    text = path.read_text(encoding="utf-8")
    assert "old.key" not in text
    assert "new.key" in text
    assert '[logging]\nlevel = "INFO"' in text


def test_sync_merges_seeds_and_live(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        "[plugins]\n"
        'modules = ["deckhand.plugins.claude_code_usage"]\n\n'
        "[catalog.state_keys]\n"
        "entries = [\n"
        '  { key = "usage.claude_code.session", dropdown_label = "My Session" },\n'
        "]\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DECKHAND_CONFIG_FILE", raising=False)

    written, entries = sync_state_key_catalog(
        path,
        live_keys=["usage.claude_code.session", "usage.antigravity.session"],
    )
    assert written == path
    by_key = {e.key: e for e in entries}
    assert by_key["usage.claude_code.session"].dropdown_label == "My Session"
    assert by_key["usage.claude_code.session"].format == "percentage"
    assert by_key["usage.claude_code.session"].button_title == "Session"
    assert "usage.claude_code.week" in by_key
    assert "usage.antigravity.session" in by_key
    assert by_key["usage.antigravity.session"].image == "antigravity"


def test_settings_loads_state_key_catalog(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        "[catalog.state_keys]\n"
        "entries = [\n"
        '  { key = "usage.claude_code.session", '
        'dropdown_label = "Session", format = "percentage", '
        'button_title = "Sess" },\n'
        "]\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DECKHAND_CONFIG_FILE", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    settings = Settings()
    assert settings.state_key_catalog == [
        StateKeyEntry(
            key="usage.claude_code.session",
            dropdown_label="Session",
            format="percentage",
            button_title="Sess",
        )
    ]


def test_sort_catalog_dicts_by_label() -> None:
    rows = [
        {"key": "z", "dropdown_label": "Zebra"},
        {"key": "a", "dropdown_label": "ant"},
        {"key": "m", "dropdown_label": "Mouse"},
    ]
    sorted_rows = sort_catalog_dicts_by_label(rows)
    assert [r["dropdown_label"] for r in sorted_rows] == ["ant", "Mouse", "Zebra"]
