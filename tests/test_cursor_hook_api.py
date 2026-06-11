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

    summary = await client.get("/state/cursor.summary")
    assert summary.status_code == 200
    assert summary.json()["value"]["total"] == 1


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
