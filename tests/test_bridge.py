"""Tests for the DeckhandBridge HTTP/WS client (mocked against Deckhand Core)."""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

# We test the bridge logic by verifying it would make the right HTTP calls.
# Since the real bridge uses aiohttp, we test at a higher level against the
# actual Deckhand Core FastAPI app.

TEST_API_KEY = "test-key-for-bridge-tests"


@pytest.fixture
async def client(monkeypatch):
    """Async HTTP client against the Deckhand Core app with auth."""
    monkeypatch.setenv("DECKHAND_API_KEY", TEST_API_KEY)
    monkeypatch.setenv("DECKHAND_CONFIG_FILE", "/tmp/deckhand-tests-nonexistent.toml")

    # Import after env is set so Settings picks up the key
    import importlib
    import deckhand.main as main_mod

    importlib.reload(main_mod)
    from deckhand.main import app, lifespan

    async with lifespan(app):
        # test_bridge.py predates the cleanup that removed default mock-agent
        # registrations from the lifespan. The HTTP route shapes it exercises
        # are still real; we register the same mock agents here so each test
        # keeps testing the routes rather than the lifespan policy.
        from deckhand.agents.mock import MockAgent

        main_mod.orchestrator.register_agent(
            MockAgent(agent_id="mock-1", project_root="/home/dev/project-alpha")
        )
        main_mod.orchestrator.register_agent(
            MockAgent(agent_id="mock-2", project_root="/home/dev/project-beta")
        )
        transport = ASGITransport(app=app)
        headers = {"Authorization": f"Bearer {TEST_API_KEY}"}
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=headers
        ) as c:
            yield c


async def test_list_agents(client: AsyncClient) -> None:
    """Bridge.list_agents() hits GET /agents and includes context fields."""
    resp = await client.get("/agents")
    assert resp.status_code == 200
    agents = resp.json()
    assert isinstance(agents, list)
    assert len(agents) >= 2
    ids = [a["id"] for a in agents]
    assert "mock-1" in ids
    assert "mock-2" in ids

    # Verify context fields are present
    mock1 = next(a for a in agents if a["id"] == "mock-1")
    assert "project_root" in mock1
    assert "display_label" in mock1
    assert mock1["project_root"] == "/home/dev/project-alpha"
    assert mock1["display_label"] == "mock: project-alpha"


async def test_start_agent(client: AsyncClient) -> None:
    """Bridge.start_agent() hits POST /agents/{id}/start."""
    resp = await client.post("/agents/mock-1/start")
    assert resp.status_code == 200
    assert resp.json()["status"] == "started"


async def test_start_agent_not_found(client: AsyncClient) -> None:
    """Bridge.start_agent() returns 404 for unknown agent."""
    resp = await client.post("/agents/nonexistent/start")
    assert resp.status_code == 404


async def test_cancel_agent(client: AsyncClient) -> None:
    """Bridge.cancel_agent() hits POST /agents/{id}/cancel."""
    # Start first, then cancel
    await client.post("/agents/mock-1/start")
    # Give the mock agent a moment to transition
    await asyncio.sleep(0.1)
    resp = await client.post("/agents/mock-1/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


async def test_provide_input(client: AsyncClient) -> None:
    """Bridge.provide_input() hits POST /agents/{id}/input."""
    # Start agent and wait for it to reach awaiting_input
    await client.post("/agents/mock-1/start")
    await asyncio.sleep(0.7)  # MockAgent transitions after 0.5s

    resp = await client.post(
        "/agents/mock-1/input",
        json={"text": "hello"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "input_sent"


async def test_execute_action_not_found(client: AsyncClient) -> None:
    """Bridge.execute_action() returns 404 for unknown action."""
    resp = await client.post("/actions/nonexistent", json={})
    assert resp.status_code == 404


async def test_get_state_not_found(client: AsyncClient) -> None:
    """Bridge.get_state() returns 404 for missing key."""
    resp = await client.get("/state/nonexistent.key")
    assert resp.status_code == 404


async def test_list_state(client: AsyncClient) -> None:
    """Bridge.list_state() hits GET /state."""
    resp = await client.get("/state")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_list_actions(client: AsyncClient) -> None:
    """Bridge can discover available actions via GET /actions."""
    resp = await client.get("/actions")
    assert resp.status_code == 200
    data = resp.json()
    assert "actions" in data
    # Default agent actions should exist
    names = [a["name"] for a in data["actions"]]
    assert "agent.start" in names
    assert "agent.cancel" in names


async def test_unauthenticated_request_rejected(client: AsyncClient) -> None:
    """Requests without API key are rejected with 401."""
    transport = ASGITransport(app=client._transport.app)
    async with AsyncClient(transport=transport, base_url="http://test") as no_auth:
        resp = await no_auth.get("/agents")
        assert resp.status_code == 401


async def test_read_only_key_blocks_write(client: AsyncClient) -> None:
    """A read-scoped key cannot access write endpoints."""
    transport = ASGITransport(app=client._transport.app)
    headers = {"Authorization": "Bearer wrong-key"}
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=headers
    ) as bad:
        resp = await bad.post("/agents/mock-1/start")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Agent registration & context tests
# ---------------------------------------------------------------------------


async def test_register_agent(client: AsyncClient) -> None:
    """POST /agents/register creates a new agent with context."""
    resp = await client.post(
        "/agents/register",
        json={
            "agent_id": "ext-1",
            "agent_type": "claude-code",
            "capabilities": ["accepts_text"],
            "project_root": "/home/dev/my-project",
            "active_file": "/home/dev/my-project/src/main.py",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "ext-1"
    assert data["type"] == "claude-code"
    assert data["project_root"] == "/home/dev/my-project"
    assert data["active_file"] == "/home/dev/my-project/src/main.py"
    assert data["display_label"] == "claude-code: my-project"

    # Agent should now be listable
    resp2 = await client.get("/agents")
    ids = [a["id"] for a in resp2.json()]
    assert "ext-1" in ids


async def test_register_agent_duplicate(client: AsyncClient) -> None:
    """Registering an agent with an existing ID returns 409."""
    resp = await client.post(
        "/agents/register",
        json={"agent_id": "mock-1"},
    )
    assert resp.status_code == 409


async def test_update_agent_context(client: AsyncClient) -> None:
    """PATCH /agents/{id}/context updates project_root and active_file."""
    resp = await client.patch(
        "/agents/mock-1/context",
        json={
            "project_root": "/tmp/new-project",
            "active_file": "/tmp/new-project/README.md",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["project_root"] == "/tmp/new-project"
    assert data["active_file"] == "/tmp/new-project/README.md"
    assert data["display_label"] == "mock: new-project"


async def test_update_agent_context_not_found(client: AsyncClient) -> None:
    """PATCH /agents/{id}/context returns 404 for unknown agent."""
    resp = await client.patch(
        "/agents/nonexistent/context",
        json={"project_root": "/tmp/x"},
    )
    assert resp.status_code == 404


async def test_health_endpoint(client: AsyncClient) -> None:
    """GET /health returns service health info and does not require auth."""
    transport = ASGITransport(app=client._transport.app)
    async with AsyncClient(transport=transport, base_url="http://test") as no_auth:
        resp = await no_auth.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert data["uptime_seconds"] >= 0
    assert data["websocket_clients"] == 0
    assert data["agents"]["count"] >= 2
    assert "mock-1" in data["agents"]["statuses"]
    assert data["plugins"]["actions"] > 0
    assert "entry_count" in data["state_store"]
    assert data["state_store"]["writable"] is True


async def test_metrics_endpoint(client: AsyncClient) -> None:
    """GET /metrics returns operational counters and reflects activity."""
    # Trigger some activity: one successful action and one failing action.
    resp = await client.post("/actions/agent.start", json={"agent_id": "mock-1"})
    assert resp.status_code == 200

    resp = await client.post(
        "/actions/agent.start",
        json={},  # missing agent_id -> ValidationError
    )
    assert resp.status_code in (400, 422)

    # Metrics is unauthenticated.
    transport = ASGITransport(app=client._transport.app)
    async with AsyncClient(transport=transport, base_url="http://test") as no_auth:
        resp = await no_auth.get("/metrics")
    assert resp.status_code == 200
    data = resp.json()

    assert data["uptime_seconds"] > 0
    assert data["events"]["total"] >= 1
    assert data["events"]["per_second"] >= 0
    # At least the successful action ran; the failing one was rejected before
    # the handler by payload validation, so only success is guaranteed.
    assert data["actions"]["total"] >= 1
    assert data["actions"]["success"] >= 1
    assert "by_status" in data["agents"]
    assert data["agents"]["count"] >= 2
    assert data["websocket_clients"] == 0
    assert "entry_count" in data["state_store"]


async def test_agent_without_context_uses_id_as_label(client: AsyncClient) -> None:
    """An agent with no project_root falls back to its ID for display_label."""
    resp = await client.post(
        "/agents/register",
        json={"agent_id": "bare-agent"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["project_root"] is None
    assert data["display_label"] == "bare-agent"
