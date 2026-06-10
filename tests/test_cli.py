"""Tests for the deckhand CLI.

The HTTP wire is covered by ``test_bridge.py`` (real FastAPI app via ASGI).
These tests focus on:

* CLI command tree (Typer discovers subcommands and exposes ``--help``).
* Command functions (``deckhand.cli.commands.*``) wire client calls to
  formatter output correctly.
* Config resolution precedence.
* Hook simulator dispatches by agent type.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from deckhand.cli import config as cli_config
from deckhand.cli.commands import (
    actions as actions_cmd,
    agents as agents_cmd,
    events as events_cmd,
    hooks as hooks_cmd,
    signals as signals_cmd,
    state as state_cmd,
)
from deckhand.cli.main import app as cli_app


# --------------------------------------------------------------- CLI tree --


def test_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli_app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("state", "events", "actions", "signals", "agents", "hooks"):
        assert cmd in result.output


@pytest.mark.parametrize(
    "group", ["state", "events", "actions", "signals", "agents", "hooks"]
)
def test_group_help(group: str) -> None:
    runner = CliRunner()
    result = runner.invoke(cli_app, [group, "--help"])
    assert result.exit_code == 0


# ---------------------------------------------------------- Stub client ---


class StubClient:
    """Records calls and returns canned responses."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.responses: dict[str, Any] = {}

    def _record(self, name: str, *args, **kwargs) -> Any:
        self.calls.append((name, args, kwargs))
        return self.responses.get(name, {"status": "ok"})

    def list_state(self):
        return self._record("list_state")

    def get_state(self, key: str):
        return self._record("get_state", key)

    def list_actions(self):
        return self._record("list_actions")

    def call_action(self, name: str, payload: dict):
        return self._record("call_action", name, payload)

    def list_signals(self):
        return self._record("list_signals")

    def fire_signal(self, name: str, payload: dict):
        return self._record("fire_signal", name, payload)

    def list_agents(self):
        return self._record("list_agents")

    def start_agent(self, agent_id: str):
        return self._record("start_agent", agent_id)

    def cancel_agent(self, agent_id: str):
        return self._record("cancel_agent", agent_id)

    def agent_input(self, agent_id: str, text: str):
        return self._record("agent_input", agent_id, text)

    def post_claude_code_hook(self, payload: dict):
        return self._record("post_claude_code_hook", payload)

    def post_cursor_hook(self, payload: dict):
        return self._record("post_cursor_hook", payload)


@pytest.fixture
def stub(capsys: pytest.CaptureFixture[str]) -> StubClient:
    return StubClient()


# ----------------------------------------------------- Command dispatch ---


def _captured_json(capsys: pytest.CaptureFixture[str]) -> Any:
    captured = capsys.readouterr().out.strip()
    return json.loads(captured)


def test_state_list_emits_json(
    stub: StubClient, capsys: pytest.CaptureFixture[str]
) -> None:
    stub.responses["list_state"] = [{"key": "a", "value": 1}]
    state_cmd.list_(stub)
    assert _captured_json(capsys) == [{"key": "a", "value": 1}]
    assert stub.calls == [("list_state", (), {})]


def test_state_get_emits_json(
    stub: StubClient, capsys: pytest.CaptureFixture[str]
) -> None:
    stub.responses["get_state"] = {"key": "a", "value": 1}
    state_cmd.get(stub, "a")
    assert _captured_json(capsys) == {"key": "a", "value": 1}
    assert stub.calls == [("get_state", ("a",), {})]


def test_actions_list(stub: StubClient, capsys: pytest.CaptureFixture[str]) -> None:
    stub.responses["list_actions"] = [{"name": "agent.start"}]
    actions_cmd.list_(stub)
    assert _captured_json(capsys) == [{"name": "agent.start"}]


def test_actions_call_parses_payload(
    stub: StubClient, capsys: pytest.CaptureFixture[str]
) -> None:
    actions_cmd.call(stub, "agent.start", '{"agent_id": "mock-1"}')
    assert stub.calls == [("call_action", ("agent.start", {"agent_id": "mock-1"}), {})]


def test_actions_call_empty_payload(
    stub: StubClient, capsys: pytest.CaptureFixture[str]
) -> None:
    actions_cmd.call(stub, "agent.start", "")
    assert stub.calls == [("call_action", ("agent.start", {}), {})]


def test_actions_call_invalid_json_exits(stub: StubClient) -> None:
    with pytest.raises(SystemExit):
        actions_cmd.call(stub, "agent.start", "not-json")


def test_signals_fire_parses_payload(
    stub: StubClient, capsys: pytest.CaptureFixture[str]
) -> None:
    signals_cmd.fire(stub, "camera.motion", '{"key": "front", "active": true}')
    assert stub.calls == [
        ("fire_signal", ("camera.motion", {"key": "front", "active": True}), {})
    ]


def test_agents_start(stub: StubClient, capsys: pytest.CaptureFixture[str]) -> None:
    agents_cmd.start(stub, "mock-1")
    assert stub.calls == [("start_agent", ("mock-1",), {})]


def test_agents_input(stub: StubClient, capsys: pytest.CaptureFixture[str]) -> None:
    agents_cmd.input_(stub, "mock-1", "hello")
    assert stub.calls == [("agent_input", ("mock-1", "hello"), {})]


# ------------------------------------------------------ Hook simulator ----


def test_hook_simulate_claude_code(
    stub: StubClient,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = {"session_id": "abcdef0123", "hook_event_name": "SessionStart"}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    hooks_cmd.simulate(stub, "claude-code")
    assert stub.calls == [("post_claude_code_hook", (payload,), {})]


def test_hook_simulate_cursor(
    stub: StubClient,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = {"session_id": "xyz", "hook_event_name": "sessionStart"}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    hooks_cmd.simulate(stub, "cursor")
    assert stub.calls == [("post_cursor_hook", (payload,), {})]


def test_hook_simulate_unknown_type_exits(
    stub: StubClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO('{"x": 1}'))
    with pytest.raises(SystemExit):
        hooks_cmd.simulate(stub, "gemini")


def test_hook_simulate_empty_stdin_exits(
    stub: StubClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("   "))
    with pytest.raises(SystemExit):
        hooks_cmd.simulate(stub, "claude-code")


# --------------------------------------------------------- events tail ----


def _parse_json_stream(text: str) -> list[dict]:
    """Parse a stream of concatenated JSON documents (whitespace-separated)."""
    decoder = json.JSONDecoder()
    idx = 0
    objs: list[dict] = []
    while idx < len(text):
        while idx < len(text) and text[idx].isspace():
            idx += 1
        if idx >= len(text):
            break
        obj, end = decoder.raw_decode(text[idx:])
        objs.append(obj)
        idx += end
    return objs


def test_events_tail_log_filters(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "events.log"
    log.write_text(
        json.dumps({"type": "state.changed", "n": 1})
        + "\n"
        + json.dumps({"type": "agent.status_changed", "n": 2})
        + "\n"
        + json.dumps({"type": "state.changed", "n": 3})
        + "\n"
    )
    events_cmd.tail_log(log, ["state.changed"], follow=False)
    events = _parse_json_stream(capsys.readouterr().out)
    assert [e["n"] for e in events] == [1, 3]


def test_events_tail_log_no_filter(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "events.log"
    log.write_text(
        json.dumps({"type": "a", "n": 1})
        + "\n"
        + json.dumps({"type": "b", "n": 2})
        + "\n"
    )
    events_cmd.tail_log(log, [], follow=False)
    events = _parse_json_stream(capsys.readouterr().out)
    assert [e["n"] for e in events] == [1, 2]


def test_events_tail_log_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        events_cmd.tail_log(tmp_path / "missing.log", [], follow=False)


# ----------------------------------------------------------- Config -------


def test_config_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for var in (
        "DECKHAND_URL",
        "DECKHAND_API_KEY",
        "DECKHAND_EVENT_LOG",
        "DECKHAND_CONFIG_FILE",
    ):
        monkeypatch.delenv(var, raising=False)

    cfg = cli_config.load()
    assert cfg.url == cli_config.DEFAULT_URL
    assert cfg.api_key is None
    assert cfg.event_log_path == Path(cli_config.DEFAULT_EVENT_LOG)


def test_config_flag_overrides_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DECKHAND_URL", "http://env-host:8000")
    monkeypatch.setenv("DECKHAND_API_KEY", "env-key")

    cfg = cli_config.load(url_flag="http://flag-host:9000", api_key_flag="flag-key")
    assert cfg.url == "http://flag-host:9000"
    assert cfg.api_key == "flag-key"


def test_config_env_overrides_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[service]\nhost = "1.2.3.4"\nport = 1234\n'
        '[auth]\napi_keys = [{ key = "file-key", scope = "write" }]\n'
        '[event_log]\npath = "/from-file/events.log"\n'
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DECKHAND_URL", "http://env:8000")
    monkeypatch.setenv("DECKHAND_API_KEY", "env-key")
    monkeypatch.delenv("DECKHAND_EVENT_LOG", raising=False)
    monkeypatch.delenv("DECKHAND_CONFIG_FILE", raising=False)

    cfg = cli_config.load()
    assert cfg.url == "http://env:8000"
    assert cfg.api_key == "env-key"
    assert cfg.event_log_path == Path("/from-file/events.log")


def test_config_file_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[service]\nhost = "1.2.3.4"\nport = 1234\n'
        '[auth]\napi_keys = [{ key = "file-key", scope = "write" }]\n'
    )
    monkeypatch.chdir(tmp_path)
    for var in ("DECKHAND_URL", "DECKHAND_API_KEY", "DECKHAND_CONFIG_FILE"):
        monkeypatch.delenv(var, raising=False)

    cfg = cli_config.load()
    assert cfg.url == "http://1.2.3.4:1234"
    assert cfg.api_key == "file-key"
