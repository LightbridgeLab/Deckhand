"""HTTP-level tests for the POST /agents/claude-code/hook endpoint."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

TEST_API_KEY = "test-key-for-claude-code-hook-tests"


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setenv("DECKHAND_API_KEY", TEST_API_KEY)

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


async def test_hook_auto_registers_agent_on_first_sighting(
    client: AsyncClient,
) -> None:
    resp = await client.post(
        "/agents/claude-code/hook",
        json={
            "session_id": "abcdef1234567890",
            "hook_event_name": "SessionStart",
            "cwd": "/tmp/my-project",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["agent"]["id"] == "claude-code-abcdef12"
    assert body["agent"]["type"] == "claude_code"
    assert body["agent"]["project_root"] == "/tmp/my-project"
    assert body["agent"]["status"] == "idle"

    # Agent shows up in /agents listing
    agents = (await client.get("/agents")).json()
    ids = [a["id"] for a in agents]
    assert "claude-code-abcdef12" in ids


async def test_hook_status_transitions(client: AsyncClient) -> None:
    session = {"session_id": "deadbeef00000000", "cwd": "/tmp/p"}

    async def push(event: str) -> str:
        resp = await client.post(
            "/agents/claude-code/hook",
            json={**session, "hook_event_name": event},
        )
        assert resp.status_code == 200
        return resp.json()["agent"]["status"]

    assert await push("SessionStart") == "idle"
    assert await push("UserPromptSubmit") == "running"
    assert await push("Notification") == "awaiting_input"
    assert await push("Stop") == "idle"


async def test_hook_session_end_unregisters(client: AsyncClient) -> None:
    session_id = "cafebabe00000000"
    await client.post(
        "/agents/claude-code/hook",
        json={
            "session_id": session_id,
            "hook_event_name": "SessionStart",
            "cwd": "/tmp/p",
        },
    )

    ids = [a["id"] for a in (await client.get("/agents")).json()]
    assert "claude-code-cafebabe" in ids

    resp = await client.post(
        "/agents/claude-code/hook",
        json={"session_id": session_id, "hook_event_name": "SessionEnd"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "unregistered"

    ids_after = [a["id"] for a in (await client.get("/agents")).json()]
    assert "claude-code-cafebabe" not in ids_after


async def test_hook_distinct_sessions_yield_distinct_agents(
    client: AsyncClient,
) -> None:
    await client.post(
        "/agents/claude-code/hook",
        json={
            "session_id": "1111111111111111",
            "hook_event_name": "SessionStart",
            "cwd": "/tmp/alpha",
        },
    )
    await client.post(
        "/agents/claude-code/hook",
        json={
            "session_id": "2222222222222222",
            "hook_event_name": "SessionStart",
            "cwd": "/tmp/beta",
        },
    )

    agents = (await client.get("/agents")).json()
    claude_agents = [a for a in agents if a["type"] == "claude_code"]
    ids = {a["id"] for a in claude_agents}
    roots = {a["project_root"] for a in claude_agents}
    assert "claude-code-11111111" in ids
    assert "claude-code-22222222" in ids
    assert "/tmp/alpha" in roots
    assert "/tmp/beta" in roots


async def test_hook_registers_iterm_focuser_when_session_id_present(
    client: AsyncClient,
) -> None:
    """SessionStart with iterm_session_id binds a focuser on the orchestrator."""
    import deckhand.main as main_mod

    await client.post(
        "/agents/claude-code/hook",
        json={
            "session_id": "feedface00000000",
            "hook_event_name": "SessionStart",
            "cwd": "/tmp/p",
            "iterm_session_id": "iterm-uuid-xyz",
        },
    )
    assert main_mod.orchestrator is not None
    assert "claude-code-feedface" in main_mod.orchestrator.focusers


async def test_hook_skips_focuser_when_iterm_session_id_absent(
    client: AsyncClient,
) -> None:
    """Without iterm_session_id (e.g. Terminal.app), the agent is unfocusable."""
    import deckhand.main as main_mod

    await client.post(
        "/agents/claude-code/hook",
        json={
            "session_id": "feedbeef00000000",
            "hook_event_name": "SessionStart",
            "cwd": "/tmp/p",
        },
    )
    assert main_mod.orchestrator is not None
    assert "claude-code-feedbeef" not in main_mod.orchestrator.focusers


async def test_hook_late_registers_focuser_on_subsequent_event(
    client: AsyncClient,
) -> None:
    """User upgrades their hook script mid-session; focuser binds late."""
    import deckhand.main as main_mod

    session_id = "1234deadbeef0000"
    await client.post(
        "/agents/claude-code/hook",
        json={
            "session_id": session_id,
            "hook_event_name": "SessionStart",
            "cwd": "/tmp/p",
        },
    )
    assert "claude-code-1234dead" not in main_mod.orchestrator.focusers

    await client.post(
        "/agents/claude-code/hook",
        json={
            "session_id": session_id,
            "hook_event_name": "UserPromptSubmit",
            "cwd": "/tmp/p",
            "iterm_session_id": "iterm-uuid-late",
        },
    )
    assert "claude-code-1234dead" in main_mod.orchestrator.focusers


async def test_hook_session_end_drops_focuser(client: AsyncClient) -> None:
    import deckhand.main as main_mod

    session_id = "f00dface00000000"
    await client.post(
        "/agents/claude-code/hook",
        json={
            "session_id": session_id,
            "hook_event_name": "SessionStart",
            "cwd": "/tmp/p",
            "iterm_session_id": "iterm-uuid-bye",
        },
    )
    assert "claude-code-f00dface" in main_mod.orchestrator.focusers

    await client.post(
        "/agents/claude-code/hook",
        json={"session_id": session_id, "hook_event_name": "SessionEnd"},
    )
    assert "claude-code-f00dface" not in main_mod.orchestrator.focusers


async def test_focus_next_pending_action_against_live_orchestrator(
    client: AsyncClient,
) -> None:
    """Full integration: two awaiting agents → first press focuses head."""
    import deckhand.main as main_mod
    from deckhand.focusers import iterm as iterm_mod

    calls: list[str] = []

    def fake_make_focuser(session_id: str):
        async def f() -> None:
            calls.append(session_id)

        return f

    # Patch where the symbol is imported, not its source module.
    main_mod.make_iterm_focuser = fake_make_focuser  # type: ignore[assignment]
    try:
        for letter, iterm_id in [("a", "iterm-A"), ("b", "iterm-B")]:
            await client.post(
                "/agents/claude-code/hook",
                json={
                    "session_id": f"{letter}" * 16,
                    "hook_event_name": "SessionStart",
                    "cwd": f"/tmp/{letter}",
                    "iterm_session_id": iterm_id,
                },
            )
            await client.post(
                "/agents/claude-code/hook",
                json={
                    "session_id": f"{letter}" * 16,
                    "hook_event_name": "Notification",
                    "cwd": f"/tmp/{letter}",
                    "iterm_session_id": iterm_id,
                },
            )

        # State should reflect both pending; press the action and 'A' focuses.
        resp = await client.post("/actions/agents.focus_next_pending", json={})
        assert resp.status_code == 200
        assert calls == ["iterm-A"]

        # Agent A resolves; next press should focus B.
        await client.post(
            "/agents/claude-code/hook",
            json={
                "session_id": "a" * 16,
                "hook_event_name": "Stop",
                "cwd": "/tmp/a",
                "iterm_session_id": "iterm-A",
            },
        )
        resp = await client.post("/actions/agents.focus_next_pending", json={})
        assert resp.status_code == 200
        assert calls == ["iterm-A", "iterm-B"]

        # Empty queue: still success (action is no-op).
        await client.post(
            "/agents/claude-code/hook",
            json={
                "session_id": "b" * 16,
                "hook_event_name": "Stop",
                "cwd": "/tmp/b",
                "iterm_session_id": "iterm-B",
            },
        )
        resp = await client.post("/actions/agents.focus_next_pending", json={})
        assert resp.status_code == 200
    finally:
        # Restore so other tests in the module pick up the real symbol.
        main_mod.make_iterm_focuser = iterm_mod.make_iterm_focuser  # type: ignore[assignment]


async def test_hook_requires_auth() -> None:
    import importlib
    import deckhand.main as main_mod

    importlib.reload(main_mod)
    from deckhand.main import app, lifespan

    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/agents/claude-code/hook",
                json={
                    "session_id": "x" * 16,
                    "hook_event_name": "SessionStart",
                },
            )
            assert resp.status_code == 401
