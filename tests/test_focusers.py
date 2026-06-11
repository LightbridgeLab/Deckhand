"""Tests for the FocuserRegistry and the iTerm AppleScript focuser."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from deckhand.agents.mock import MockAgent
from deckhand.focusers.iterm import _build_applescript, make_iterm_focuser
from deckhand.orchestrator.focusers import FocuserRegistry
from deckhand.orchestrator.manager import Orchestrator


# --------------------------------------------------------- FocuserRegistry ---


async def test_registry_register_and_get() -> None:
    registry = FocuserRegistry()

    async def f() -> None: ...

    registry.register("agent-a", f)
    assert registry.get("agent-a") is f
    assert "agent-a" in registry


async def test_registry_unregister_clears() -> None:
    registry = FocuserRegistry()

    async def f() -> None: ...

    registry.register("agent-a", f)
    registry.unregister("agent-a")
    assert registry.get("agent-a") is None
    assert "agent-a" not in registry


async def test_registry_unregister_unknown_is_noop() -> None:
    registry = FocuserRegistry()
    registry.unregister("never-existed")  # must not raise


# --------------------------------------------------------- Orchestrator wiring


async def test_orchestrator_drops_focuser_when_agent_unregisters() -> None:
    orch = Orchestrator()
    agent = MockAgent(agent_id="mock-1")
    orch.register_agent(agent)

    called: list[bool] = []

    async def focuser() -> None:
        called.append(True)

    orch.register_focuser("mock-1", focuser)
    assert "mock-1" in orch.focusers

    orch.unregister_agent("mock-1")
    assert "mock-1" not in orch.focusers


async def test_focus_next_pending_empty_is_noop() -> None:
    orch = Orchestrator()
    result = await orch.focus_next_pending()
    assert result is None


async def test_focus_next_pending_invokes_head_focuser() -> None:
    orch = Orchestrator()
    calls: list[str] = []

    async def focuser_a() -> None:
        calls.append("a")

    async def focuser_b() -> None:
        calls.append("b")

    orch.register_focuser("agent-a", focuser_a)
    orch.register_focuser("agent-b", focuser_b)
    await orch.state_store.set_state(
        "agents.pending_input",
        {"agent_ids": ["agent-a", "agent-b"]},
        source={"kind": "tracker", "id": "agents.pending_input"},
    )

    focused = await orch.focus_next_pending()
    assert focused == "agent-a"
    assert calls == ["a"]


async def test_focus_next_pending_skips_missing_focuser() -> None:
    """If head has no registered focuser, fall through to the next one."""
    orch = Orchestrator()
    calls: list[str] = []

    async def focuser_b() -> None:
        calls.append("b")

    orch.register_focuser("agent-b", focuser_b)
    await orch.state_store.set_state(
        "agents.pending_input",
        {"agent_ids": ["agent-a", "agent-b"]},
        source={"kind": "tracker", "id": "agents.pending_input"},
    )

    focused = await orch.focus_next_pending()
    assert focused == "agent-b"
    assert calls == ["b"]


async def test_focus_next_pending_continues_on_focuser_failure() -> None:
    orch = Orchestrator()

    async def bad() -> None:
        raise RuntimeError("boom")

    async def good() -> None:
        return None

    orch.register_focuser("agent-a", bad)
    orch.register_focuser("agent-b", good)
    await orch.state_store.set_state(
        "agents.pending_input",
        {"agent_ids": ["agent-a", "agent-b"]},
        source={"kind": "tracker", "id": "agents.pending_input"},
    )

    focused = await orch.focus_next_pending()
    assert focused == "agent-b"


# ---------------------------------------------------------- iTerm focuser ----


def test_applescript_contains_session_id() -> None:
    script = _build_applescript("ABC-123-DEF")
    assert "ABC-123-DEF" in script
    assert 'tell application "iTerm2"' in script
    assert "activate" in script


def test_applescript_escapes_quotes_in_session_id() -> None:
    """A pathological session id with a double-quote must not break the script."""
    script = _build_applescript('abc"injected"')
    # The raw quote should be backslash-escaped so AppleScript treats it as
    # one literal string rather than ending the contains argument early.
    assert 'abc\\"injected\\"' in script


async def test_iterm_focuser_invokes_osascript() -> None:
    focuser = make_iterm_focuser("uuid-1")

    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with patch("subprocess.run", return_value=completed) as run:
        await focuser()

    assert run.call_count == 1
    args, kwargs = run.call_args
    cmd = args[0]
    assert cmd[0] == "osascript"
    assert cmd[1] == "-e"
    assert "uuid-1" in cmd[2]
    assert kwargs.get("timeout") == 5


async def test_iterm_focuser_swallows_osascript_failure() -> None:
    focuser = make_iterm_focuser("uuid-1")
    completed = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="something broke"
    )
    with patch("subprocess.run", return_value=completed):
        await focuser()  # must not raise


async def test_iterm_focuser_swallows_missing_osascript() -> None:
    focuser = make_iterm_focuser("uuid-1")
    with patch("subprocess.run", side_effect=FileNotFoundError):
        await focuser()  # must not raise


async def test_iterm_focuser_swallows_timeout() -> None:
    focuser = make_iterm_focuser("uuid-1")
    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=5),
    ):
        await focuser()  # must not raise
