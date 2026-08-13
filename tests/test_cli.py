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
import os
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from deckhand.cli import config as cli_config
from deckhand.cli.client import DeckhandError
from deckhand.cli.commands import (
    actions as actions_cmd,
)
from deckhand.cli.commands import (
    agents as agents_cmd,
)
from deckhand.cli.commands import (
    catalog as catalog_cmd,
)
from deckhand.cli.commands import (
    events as events_cmd,
)
from deckhand.cli.commands import (
    hooks as hooks_cmd,
)
from deckhand.cli.commands import (
    signals as signals_cmd,
)
from deckhand.cli.commands import (
    state as state_cmd,
)
from deckhand.cli.main import app as cli_app

# --------------------------------------------------------------- CLI tree --


def test_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli_app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("state", "events", "actions", "signals", "agents", "hooks", "catalog"):
        assert cmd in result.output


@pytest.mark.parametrize(
    "group", ["state", "events", "actions", "signals", "agents", "hooks", "catalog"]
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

    def register_agent(self, payload: dict):
        return self._record("register_agent", payload)

    def unregister_agent(self, agent_id: str):
        return self._record("unregister_agent", agent_id)


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
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "deckhand.integrations.session_hooks.default_hooks_log_path",
        lambda: tmp_path / "hooks.log",
    )
    monkeypatch.delenv("ITERM_SESSION_ID", raising=False)
    payload = {"session_id": "abcdef0123", "hook_event_name": "SessionStart"}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    hooks_cmd.simulate(stub, "claude-code")
    assert stub.calls == [("post_claude_code_hook", (payload,), {})]


def test_hook_ingest_claude_quiet_success(
    stub: StubClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    log = tmp_path / "hooks.log"
    monkeypatch.setattr(
        "deckhand.integrations.session_hooks.default_hooks_log_path",
        lambda: log,
    )
    monkeypatch.delenv("ITERM_SESSION_ID", raising=False)
    payload = {"session_id": "abcdef0123", "hook_event_name": "SessionStart"}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    hooks_cmd.ingest(stub, "claude-code")
    assert stub.calls == [("post_claude_code_hook", (payload,), {})]
    assert capsys.readouterr().out == ""
    assert log.read_text(encoding="utf-8").rstrip().endswith(" ok")


def test_hook_ingest_logs_and_exits_zero_on_core_error(
    stub: StubClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    log = tmp_path / "hooks.log"
    monkeypatch.setattr(
        "deckhand.integrations.session_hooks.default_hooks_log_path",
        lambda: log,
    )

    def boom(payload: dict) -> dict:
        raise DeckhandError(401, "unauthorized")

    stub.post_claude_code_hook = boom  # type: ignore[method-assign]
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({"session_id": "s", "hook_event_name": "SessionStart"})),
    )
    with pytest.raises(SystemExit) as exc:
        hooks_cmd.ingest(stub, "claude-code")
    assert exc.value.code == 0
    assert "unauthorized" in log.read_text(encoding="utf-8")


def test_hook_simulate_cursor(
    stub: StubClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "deckhand.integrations.session_hooks.default_hooks_log_path",
        lambda: tmp_path / "hooks.log",
    )
    payload = {"session_id": "xyz", "hook_event_name": "sessionStart"}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    hooks_cmd.simulate(stub, "cursor")
    assert stub.calls == [("post_cursor_hook", (payload,), {})]


def test_hook_ingest_cursor_normalizes_workspace_roots(
    stub: StubClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "deckhand.integrations.session_hooks.default_hooks_log_path",
        lambda: tmp_path / "hooks.log",
    )
    raw = {
        "session_id": "abcdef12xxxx",
        "workspace_roots": ["/tmp/proj"],
        "prompt": "hi",
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(raw)))
    hooks_cmd.ingest(stub, "cursor", event="sessionStart")
    assert stub.calls[0][0] == "post_cursor_hook"
    body = stub.calls[0][1][0]
    assert body["cwd"] == "/tmp/proj"
    assert body["title"] == "hi"
    assert body["hook_event_name"] == "sessionStart"


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


def test_hooks_install_writes_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    claude = tmp_path / "claude" / "settings.json"
    cursor = tmp_path / "cursor" / "hooks.json"
    claude.parent.mkdir()
    cursor.parent.mkdir()
    claude.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {"hooks": [{"type": "command", "command": "echo keep"}]}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    cfg = tmp_path / "config.toml"
    cfg.write_text("[auth]\n", encoding="utf-8")
    hooks_cmd.install(
        ["all"],
        binary="/opt/deckhand",
        claude_path=claude,
        cursor_path=cursor,
        config_path=str(cfg),
    )
    out = _captured_json(capsys)
    assert out["binary"] == "/opt/deckhand"
    assert out["config"] == str(cfg.resolve())
    assert len(out["installed"]) == 2

    claude_data = json.loads(claude.read_text(encoding="utf-8"))
    blob = json.dumps(claude_data)
    assert "echo keep" in blob
    assert "hooks ingest claude-code" in blob
    assert f"--config {cfg.resolve()}" in blob

    # Second install does not duplicate
    hooks_cmd.install(
        ["claude-code"],
        binary="/opt/deckhand",
        claude_path=claude,
        cursor_path=cursor,
        config_path=str(cfg),
    )
    claude_data2 = json.loads(claude.read_text(encoding="utf-8"))
    ingest_hits = json.dumps(claude_data2).count("hooks ingest claude-code")
    assert ingest_hits == json.dumps(claude_data).count("hooks ingest claude-code")


def test_hooks_status_report(
    stub: StubClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "deckhand.integrations.session_hooks.claude_settings_path",
        lambda: tmp_path / "missing-claude.json",
    )
    monkeypatch.setattr(
        "deckhand.integrations.session_hooks.cursor_hooks_path",
        lambda: tmp_path / "missing-cursor.json",
    )
    monkeypatch.setattr(
        "deckhand.integrations.session_hooks.default_hooks_log_path",
        lambda: tmp_path / "hooks.log",
    )
    stub.responses["list_agents"] = []
    hooks_cmd.status(stub, api_key="k")
    report = _captured_json(capsys)
    assert report["core"]["reachable"] is True
    assert report["core"]["agent_count"] == 0
    assert report["api_key_configured"] is True
    assert any("hooks install" in h for h in report["hints"])


def test_hooks_status_stale_401_ignored_when_agents_listed(
    stub: StubClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    log = tmp_path / "hooks.log"
    log.write_text(
        "2026-08-13T13:16:37Z [claude-code] HTTP 401: Missing API key\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "deckhand.integrations.session_hooks.claude_settings_path",
        lambda: tmp_path / "missing-claude.json",
    )
    monkeypatch.setattr(
        "deckhand.integrations.session_hooks.cursor_hooks_path",
        lambda: tmp_path / "missing-cursor.json",
    )
    monkeypatch.setattr(
        "deckhand.integrations.session_hooks.default_hooks_log_path",
        lambda: log,
    )
    stub.responses["list_agents"] = [{"id": "claude-code-abcdef12"}]
    hooks_cmd.status(stub, api_key="k")
    report = _captured_json(capsys)
    assert report["core"]["agent_count"] == 1
    assert "Missing API key" in (report["last_ingest_error"] or "")
    assert not any("Missing API key" in h or "do not see" in h for h in report["hints"])


def test_hooks_status_ok_line_clears_error(
    stub: StubClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    log = tmp_path / "hooks.log"
    log.write_text(
        "2026-08-13T13:16:37Z [claude-code] HTTP 401: Missing API key\n"
        "2026-08-13T13:20:00Z [claude-code] ok\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "deckhand.integrations.session_hooks.claude_settings_path",
        lambda: tmp_path / "missing-claude.json",
    )
    monkeypatch.setattr(
        "deckhand.integrations.session_hooks.cursor_hooks_path",
        lambda: tmp_path / "missing-cursor.json",
    )
    monkeypatch.setattr(
        "deckhand.integrations.session_hooks.default_hooks_log_path",
        lambda: log,
    )
    stub.responses["list_agents"] = []
    hooks_cmd.status(stub, api_key="k")
    report = _captured_json(capsys)
    assert report["last_ingest_error"] is None


def test_agents_demo_registers_mock(
    stub: StubClient, capsys: pytest.CaptureFixture[str]
) -> None:
    agents_cmd.demo(stub)
    assert stub.calls[0][0] == "register_agent"
    assert stub.calls[0][1][0]["agent_type"] == "mock"
    assert stub.calls[0][1][0]["agent_id"] == "demo-1"


def test_agents_demo_remove(stub: StubClient) -> None:
    agents_cmd.demo(stub, remove=True)
    assert stub.calls == [("unregister_agent", ("demo-1",), {})]


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


def test_events_tail_log_detects_truncation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Truncation under the reader is recognized and the file is re-read."""
    log = tmp_path / "events.log"
    log.write_text(json.dumps({"type": "a", "n": 1}) + "\n")

    # Drive the follow loop in lockstep:
    # step 1 truncates to empty; step 2 writes the new event; step 3 exits.
    state = {"step": 0}

    def driver(_seconds: float) -> None:
        state["step"] += 1
        if state["step"] == 1:
            log.write_text("")  # truncate to zero bytes
        elif state["step"] == 2:
            log.write_text(json.dumps({"type": "b", "n": 2}) + "\n")
        else:
            raise KeyboardInterrupt

    monkeypatch.setattr("deckhand.cli.commands.events.time.sleep", driver)

    try:
        events_cmd.tail_log(log, [], follow=True)
    except KeyboardInterrupt:
        pass

    events = _parse_json_stream(capsys.readouterr().out)
    assert {e["n"] for e in events} == {1, 2}


def test_events_tail_log_detects_rotation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Renaming the log and creating a fresh one under the same name re-reads it."""
    log = tmp_path / "events.log"
    log.write_text(json.dumps({"type": "a", "n": 1}) + "\n")

    state = {"step": 0}

    def driver(_seconds: float) -> None:
        state["step"] += 1
        if state["step"] == 1:
            # Rotate: rename current file, create fresh one at same path
            log.rename(tmp_path / "events.log.1")
            log.write_text(json.dumps({"type": "b", "n": 2}) + "\n")
        else:
            raise KeyboardInterrupt

    monkeypatch.setattr("deckhand.cli.commands.events.time.sleep", driver)

    try:
        events_cmd.tail_log(log, [], follow=True)
    except KeyboardInterrupt:
        pass

    events = _parse_json_stream(capsys.readouterr().out)
    assert {e["n"] for e in events} == {1, 2}


# ----------------------------------------------------------- Config -------


def test_config_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
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
    # Relative default resolves against cwd when no config.toml is present.
    assert cfg.event_log_path == (tmp_path / cli_config.DEFAULT_EVENT_LOG).resolve()
    assert cfg.event_log_path.is_absolute()


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
    # Absolute paths pass through unchanged.
    assert cfg.event_log_path == Path("/from-file/events.log")


def test_config_relative_log_resolves_against_config_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A relative event_log.path anchors to config.toml's directory, not cwd."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "config.toml").write_text(
        '[event_log]\npath = ".deckhand/events.log"\n'
    )

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    for var in ("DECKHAND_URL", "DECKHAND_API_KEY", "DECKHAND_EVENT_LOG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DECKHAND_CONFIG_FILE", str(project_dir / "config.toml"))

    cfg = cli_config.load()
    assert cfg.event_log_path == (project_dir / ".deckhand" / "events.log").resolve()


def test_config_env_log_relative_resolves_against_config_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """DECKHAND_EVENT_LOG=<relative> also anchors to config.toml's directory."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "config.toml").write_text("")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    for var in ("DECKHAND_URL", "DECKHAND_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DECKHAND_CONFIG_FILE", str(project_dir / "config.toml"))
    monkeypatch.setenv("DECKHAND_EVENT_LOG", "logs/x.log")

    cfg = cli_config.load()
    assert cfg.event_log_path == (project_dir / "logs" / "x.log").resolve()


def test_config_live_runtime_wins_over_client_section(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A running Core's runtime.toml beats a stale [client] url."""
    from deckhand.config.runtime import write_runtime

    runtime = tmp_path / "runtime.toml"
    monkeypatch.setenv("DECKHAND_RUNTIME_FILE", str(runtime))
    write_runtime("127.0.0.1", 19000, pid=os.getpid())

    (tmp_path / "config.toml").write_text(
        '[client]\nurl = "http://127.0.0.1:18765"\napi_key = "client-key"\n'
    )
    monkeypatch.chdir(tmp_path)
    for var in ("DECKHAND_URL", "DECKHAND_API_KEY", "DECKHAND_CONFIG_FILE"):
        monkeypatch.delenv(var, raising=False)

    cfg = cli_config.load()
    assert cfg.url == "http://127.0.0.1:19000"
    assert cfg.api_key == "client-key"


def test_config_dead_runtime_falls_back_to_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from deckhand.config.runtime import write_runtime

    runtime = tmp_path / "runtime.toml"
    monkeypatch.setenv("DECKHAND_RUNTIME_FILE", str(runtime))
    write_runtime("127.0.0.1", 19000, pid=1_000_000_000)

    (tmp_path / "config.toml").write_text(
        '[client]\nurl = "http://127.0.0.1:18765"\napi_key = "client-key"\n'
    )
    monkeypatch.chdir(tmp_path)
    for var in ("DECKHAND_URL", "DECKHAND_API_KEY", "DECKHAND_CONFIG_FILE"):
        monkeypatch.delenv(var, raising=False)

    cfg = cli_config.load()
    assert cfg.url == "http://127.0.0.1:18765"


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


def test_config_prefers_client_section_over_legacy_extraction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The [client] section is the canonical place for client URL + key.
    When present it wins over the legacy [service]/[auth] inference."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[service]\nhost = "1.2.3.4"\nport = 1234\n'
        '[auth]\napi_keys = [{ key = "auth-key", scope = "write" }]\n'
        "[client]\n"
        'url = "http://client:9999"\n'
        'api_key = "client-key"\n'
    )
    monkeypatch.chdir(tmp_path)
    for var in ("DECKHAND_URL", "DECKHAND_API_KEY", "DECKHAND_CONFIG_FILE"):
        monkeypatch.delenv(var, raising=False)

    cfg = cli_config.load()
    assert cfg.url == "http://client:9999"
    assert cfg.api_key == "client-key"


def test_config_falls_back_to_home_dir_when_no_project_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With no ./config.toml and no DECKHAND_CONFIG_FILE, the CLI falls back
    to ~/.config/deckhand/config.toml. This is the OpenDeck-plugin-only
    install path: no service checkout, just a home-dir config."""
    fake_home = tmp_path / "home"
    home_config_dir = fake_home / ".config" / "deckhand"
    home_config_dir.mkdir(parents=True)
    (home_config_dir / "config.toml").write_text(
        '[client]\nurl = "http://home:8000"\napi_key = "home-key"\n'
    )

    project_dir = tmp_path / "project-without-config"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)
    monkeypatch.setenv("HOME", str(fake_home))
    for var in ("DECKHAND_URL", "DECKHAND_API_KEY", "DECKHAND_CONFIG_FILE"):
        monkeypatch.delenv(var, raising=False)

    cfg = cli_config.load()
    assert cfg.url == "http://home:8000"
    assert cfg.api_key == "home-key"


def test_config_project_toml_wins_over_home_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If both ./config.toml and ~/.config/deckhand/config.toml exist, the
    project-local one wins. Same precedence as the service uses."""
    fake_home = tmp_path / "home"
    (fake_home / ".config" / "deckhand").mkdir(parents=True)
    (fake_home / ".config" / "deckhand" / "config.toml").write_text(
        '[client]\nurl = "http://home:1"\napi_key = "home"\n'
    )

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "config.toml").write_text(
        '[client]\nurl = "http://project:2"\napi_key = "project"\n'
    )

    monkeypatch.chdir(project_dir)
    monkeypatch.setenv("HOME", str(fake_home))
    for var in ("DECKHAND_URL", "DECKHAND_API_KEY", "DECKHAND_CONFIG_FILE"):
        monkeypatch.delenv(var, raising=False)

    cfg = cli_config.load()
    assert cfg.url == "http://project:2"
    assert cfg.api_key == "project"


# --------------------------------------------------------------- catalog ---


def test_catalog_sync_no_live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[plugins]\nmodules = ["deckhand.plugins.claude_code_usage"]\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for var in ("DECKHAND_URL", "DECKHAND_API_KEY", "DECKHAND_CONFIG_FILE"):
        monkeypatch.delenv(var, raising=False)

    runner = CliRunner()
    result = runner.invoke(
        cli_app, ["--config", str(config_path), "catalog", "sync", "--no-live"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    keys = {e["key"] for e in payload["entries"]}
    assert "usage.claude_code.session" in keys
    assert "agents.pending_input_count" in keys

    listed = runner.invoke(cli_app, ["--config", str(config_path), "catalog", "list"])
    assert listed.exit_code == 0
    assert "usage.claude_code.session" in listed.output


def test_catalog_sync_live_warning_includes_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[plugins]\nmodules = []\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    class FailingClient:
        def list_state(self):
            raise DeckhandError(0, "connection failed: [Errno 61] Connection refused")

    catalog_cmd.sync(FailingClient(), str(config_path), include_live=True)
    payload = _captured_json(capsys)
    assert "live_warning" in payload
    assert "make dev" in payload["hint"]
    assert "--no-live" in payload["hint"]
