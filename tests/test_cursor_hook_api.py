"""HTTP-level tests for the POST /agents/cursor/hook endpoint."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

TEST_API_KEY = "test-key-for-cursor-hook-tests"


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setenv("DECKHAND_API_KEY", TEST_API_KEY)
    # Isolate from any developer-local config.toml that may reference
    # plugins that no longer exist.
    monkeypatch.setenv("DECKHAND_CONFIG_FILE", "/tmp/deckhand-tests-nonexistent.toml")

    import importlib

    import deckhand.main as main_mod

    importlib.reload(main_mod)
    from deckhand.main import app, lifespan

    async with lifespan(app):
        transport = ASGITransport(app=app)
        headers = {"Authorization": f"Bearer {TEST_API_KEY}"}
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=headers
        ) as c:
            yield c


async def test_hook_auto_registers_agent(client: AsyncClient) -> None:
    resp = await client.post(
        "/agents/cursor/hook",
        json={
            "session_id": "abcdef1234567890",
            "hook_event_name": "sessionStart",
            "cwd": "/tmp/my-project",
            "title": "Ship feature",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["agent"]["id"] == "cursor-abcdef12"
    assert body["agent"]["type"] == "cursor"
    assert body["agent"]["project_root"] == "/tmp/my-project"
    assert body["agent"]["status"] == "idle"
    assert body["agent"]["display_label"] == "Cursor: my-project"

    summary = await client.get("/state/cursor.summary")
    assert summary.status_code == 200
    assert summary.json()["value"]["total"] == 1


async def test_hook_title_update_emits_context_changed(client: AsyncClient) -> None:
    import deckhand.main as main_mod

    captured: list[str] = []
    assert main_mod.orchestrator is not None
    bus = main_mod.orchestrator.event_bus
    original = bus.emit

    async def capture(event: dict) -> None:
        captured.append(event["type"])
        await original(event)

    bus.emit = capture  # type: ignore[method-assign]
    session = {
        "session_id": "feedfeed00000000",
        "cwd": "/tmp/Deckhand",
        "hook_event_name": "sessionStart",
    }
    await client.post("/agents/cursor/hook", json=session)
    await client.post(
        "/agents/cursor/hook",
        json={
            **session,
            "hook_event_name": "beforeSubmitPrompt",
            "title": "Please review @CONFIG",
        },
    )
    assert "agent.context_changed" in captured
    row = next(
        a for a in (await client.get("/agents")).json() if a["id"] == "cursor-feedfeed"
    )
    assert row["title"] == "Please review @CONFIG"
    assert row["display_label"] == "Cursor: Deckhand"


async def test_hook_status_transitions(client: AsyncClient) -> None:
    session = {"session_id": "deadbeef00000000", "cwd": "/tmp/p"}

    async def push(event: str, **extra: object) -> str:
        resp = await client.post(
            "/agents/cursor/hook",
            json={**session, "hook_event_name": event, **extra},
        )
        assert resp.status_code == 200
        return resp.json()["agent"]["status"]

    assert await push("sessionStart") == "idle"
    assert await push("beforeSubmitPrompt") == "running"
    assert (
        await push("preToolUse", deckhand_status="awaiting_input") == "awaiting_input"
    )
    assert await push("stop") == "idle"


async def test_hook_session_end_unregisters(client: AsyncClient) -> None:
    session_id = "cafebabe00000000"
    await client.post(
        "/agents/cursor/hook",
        json={
            "session_id": session_id,
            "hook_event_name": "sessionStart",
            "cwd": "/tmp/p",
        },
    )

    resp = await client.post(
        "/agents/cursor/hook",
        json={"session_id": session_id, "hook_event_name": "sessionEnd"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "unregistered"

    ids = [a["id"] for a in (await client.get("/agents")).json()]
    assert "cursor-cafebabe" not in ids

    summary = await client.get("/state/cursor.summary")
    assert summary.json()["value"]["total"] == 0


async def test_focus_cursor_agent_action(client: AsyncClient) -> None:
    await client.post(
        "/agents/cursor/hook",
        json={
            "session_id": "1111111111111111",
            "hook_event_name": "sessionStart",
            "cwd": "/tmp/alpha",
        },
    )
    resp = await client.post(
        "/actions/ui.focus_cursor_agent",
        json={"agent_id": "cursor-11111111"},
    )
    assert resp.status_code == 200


async def test_hook_registers_cursor_focuser_on_session_start(
    client: AsyncClient,
) -> None:
    """sessionStart must wire a focuser into the orchestrator so the agent is
    reachable via agents.focus_next_pending."""
    import deckhand.main as main_mod

    await client.post(
        "/agents/cursor/hook",
        json={
            "session_id": "22222222aaaaaaaa",
            "hook_event_name": "sessionStart",
            "cwd": "/tmp/beta",
        },
    )

    assert "cursor-22222222" in main_mod.orchestrator.focusers


async def test_hook_rebinds_cursor_focuser_when_workspace_changes(
    client: AsyncClient,
) -> None:
    """If the workspace path changes mid-session (rare but valid — multi-root
    workspaces or a user switching roots), the focuser must rebind so the
    next focus call lands on the new workspace."""
    import deckhand.main as main_mod

    session = {"session_id": "33333333bbbbbbbb"}
    await client.post(
        "/agents/cursor/hook",
        json={**session, "hook_event_name": "sessionStart", "cwd": "/tmp/before"},
    )
    first = main_mod.orchestrator.focusers.get("cursor-33333333")

    await client.post(
        "/agents/cursor/hook",
        json={
            **session,
            "hook_event_name": "beforeSubmitPrompt",
            "cwd": "/tmp/after",
        },
    )
    second = main_mod.orchestrator.focusers.get("cursor-33333333")

    assert second is not None
    assert second is not first


async def test_focus_next_pending_cycles_through_mixed_cursor_and_claude(
    client: AsyncClient,
) -> None:
    """Acceptance test from #24: mixed Claude + Cursor pending sessions both
    surface in agents.pending_input and are reached by successive
    focus_next_pending calls."""
    import deckhand.main as main_mod

    # Register a Cursor agent and drive it to awaiting_input via the
    # documented hook-config opt-in (deckhand_status=awaiting_input on stop).
    await client.post(
        "/agents/cursor/hook",
        json={
            "session_id": "cccccccc11111111",
            "hook_event_name": "sessionStart",
            "cwd": "/tmp/cursor-project",
        },
    )
    await client.post(
        "/agents/cursor/hook",
        json={
            "session_id": "cccccccc11111111",
            "hook_event_name": "stop",
            "cwd": "/tmp/cursor-project",
            "deckhand_status": "awaiting_input",
        },
    )

    # Register a Claude Code agent and drive it to awaiting_input.
    await client.post(
        "/agents/claude-code/hook",
        json={
            "session_id": "dddddddd22222222",
            "hook_event_name": "SessionStart",
            "cwd": "/tmp/cc-project",
            "iterm_session_id": "cc-iterm-uuid",
        },
    )
    await client.post(
        "/agents/claude-code/hook",
        json={
            "session_id": "dddddddd22222222",
            "hook_event_name": "Notification",
            "iterm_session_id": "cc-iterm-uuid",
        },
    )

    # Both should appear in pending_input. Cursor registered first → head.
    pending_resp = await client.get("/state/agents.pending_input")
    pending = pending_resp.json()["value"]["agent_ids"]
    assert "cursor-cccccccc" in pending
    assert "claude-code-dddddddd" in pending

    # Stub both focusers so the test doesn't actually launch apps.
    fired: list[str] = []

    async def fake_cursor() -> None:
        fired.append("cursor")

    async def fake_claude() -> None:
        fired.append("claude")

    main_mod.orchestrator.register_focuser("cursor-cccccccc", fake_cursor)
    main_mod.orchestrator.register_focuser("claude-code-dddddddd", fake_claude)

    # Each press of the focus_next_pending button focuses the head, then
    # the head resolves (status leaves awaiting_input) and the next press
    # hits the other agent. Simulate the resolution manually by driving
    # each focused agent's status off awaiting_input.
    first_focused = await main_mod.orchestrator.focus_next_pending()
    assert first_focused in {"cursor-cccccccc", "claude-code-dddddddd"}

    # Resolve the first focused agent so the next press cycles to the other.
    if first_focused == "cursor-cccccccc":
        await client.post(
            "/agents/cursor/hook",
            json={
                "session_id": "cccccccc11111111",
                "hook_event_name": "beforeSubmitPrompt",
                "cwd": "/tmp/cursor-project",
            },
        )
        expected_next = "claude-code-dddddddd"
    else:
        await client.post(
            "/agents/claude-code/hook",
            json={
                "session_id": "dddddddd22222222",
                "hook_event_name": "UserPromptSubmit",
                "iterm_session_id": "cc-iterm-uuid",
            },
        )
        expected_next = "cursor-cccccccc"

    second_focused = await main_mod.orchestrator.focus_next_pending()
    assert second_focused == expected_next
    assert set(fired) == {"cursor", "claude"}
