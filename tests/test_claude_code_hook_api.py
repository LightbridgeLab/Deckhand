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
