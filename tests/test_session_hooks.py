"""Tests for session hook normalize / merge / log helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from deckhand.integrations import session_hooks as sh


def test_normalize_claude_adds_iterm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ITERM_SESSION_ID", "w0t0p0:ABC")
    out = sh.normalize_claude_payload(
        {"session_id": "s1", "hook_event_name": "SessionStart"}
    )
    assert out["iterm_session_id"] == "w0t0p0:ABC"


def test_normalize_cursor_from_raw_workspace_roots() -> None:
    out = sh.normalize_cursor_payload(
        {
            "session_id": "abcdef12xxxx",
            "workspace_roots": ["/tmp/proj"],
            "prompt": "Ship it",
        },
        event="sessionStart",
    )
    assert out == {
        "session_id": "abcdef12xxxx",
        "hook_event_name": "sessionStart",
        "cwd": "/tmp/proj",
        "title": "Ship it",
    }


def test_normalize_cursor_stop_defaults_awaiting_input() -> None:
    out = sh.normalize_cursor_payload(
        {"session_id": "s1", "cwd": "/tmp"},
        event="stop",
    )
    assert out["deckhand_status"] == "awaiting_input"


def test_normalize_cursor_requires_event() -> None:
    with pytest.raises(ValueError, match="hook_event_name"):
        sh.normalize_cursor_payload({"session_id": "s1"})


def test_merge_claude_idempotent(tmp_path: Path) -> None:
    binary = "/usr/local/bin/deckhand"
    first = sh.merge_claude_settings({}, binary=binary)
    # Unrelated hook preserved
    first["hooks"]["SessionStart"].insert(
        0,
        {"hooks": [{"type": "command", "command": "echo other"}]},
    )
    second = sh.merge_claude_settings(first, binary=binary)
    session_start = second["hooks"]["SessionStart"]
    other = [
        g
        for g in session_start
        if any(
            isinstance(h, dict) and h.get("command") == "echo other"
            for h in (g.get("hooks") or [])
        )
    ]
    ours = [
        g
        for g in session_start
        if any(
            isinstance(h, dict) and sh.INGEST_MARKER in str(h.get("command", ""))
            for h in (g.get("hooks") or [])
        )
    ]
    assert len(other) == 1
    assert len(ours) == 1
    assert ours[0]["hooks"][0]["command"] == f"{binary} hooks ingest claude-code"


def test_ingest_command_pins_config_before_subcommand() -> None:
    cmd = sh.ingest_command(
        "/opt/deckhand",
        "claude-code",
        config_path="/Users/me/dev/Deckhand/config.toml",
    )
    assert cmd.startswith(
        "/opt/deckhand --config /Users/me/dev/Deckhand/config.toml hooks ingest"
    )


def test_merge_cursor_idempotent() -> None:
    binary = "/opt/deckhand"
    first = sh.merge_cursor_hooks({"version": 1, "hooks": {}}, binary=binary)
    first["hooks"]["sessionStart"].insert(0, {"command": "echo keep-me"})
    second = sh.merge_cursor_hooks(first, binary=binary)
    cmds = [e["command"] for e in second["hooks"]["sessionStart"]]
    assert cmds.count("echo keep-me") == 1
    assert sum(1 for c in cmds if sh.INGEST_MARKER in c) == 1


def test_append_and_read_hook_log(tmp_path: Path) -> None:
    log = tmp_path / "hooks.log"
    sh.append_hook_log("boom", path=log, agent_type="cursor")
    sh.append_hook_log("later", path=log, agent_type="claude-code")
    assert sh.read_last_hook_log_line(log) is not None
    assert "later" in (sh.read_last_hook_log_line(log) or "")
    sh.append_hook_log("ok", path=log, agent_type="claude-code")
    last = sh.read_last_hook_log_line(log)
    assert sh.hook_log_line_is_ok(last)


def test_file_has_deckhand_ingest(tmp_path: Path) -> None:
    path = tmp_path / "hooks.json"
    path.write_text('{"cmd": "deckhand hooks ingest cursor"}', encoding="utf-8")
    assert sh.file_has_deckhand_ingest(path) is True
    assert sh.file_has_deckhand_ingest(tmp_path / "missing.json") is False
