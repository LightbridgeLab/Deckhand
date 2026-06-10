"""Tests for the /dev development console."""

from __future__ import annotations

import importlib

import pytest
from httpx import ASGITransport, AsyncClient

TEST_API_KEY = "test-key-dev-console"


@pytest.fixture
async def client_dev_console(monkeypatch, request):
    """HTTP client with dev console enabled or disabled via parametrize."""
    enabled = getattr(request, "param", True)
    monkeypatch.setenv("DECKHAND_API_KEY", TEST_API_KEY)
    monkeypatch.setenv("DECKHAND_DEV_CONSOLE", "1" if enabled else "0")

    import deckhand.main as main_mod

    importlib.reload(main_mod)
    from deckhand.main import app, lifespan

    async with lifespan(app):
        transport = ASGITransport(app=main_mod.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.mark.parametrize("client_dev_console", [True], indirect=True)
async def test_dev_console_index(client_dev_console: AsyncClient) -> None:
    resp = await client_dev_console.get("/dev/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "Deckhand Dev Console" in resp.text


@pytest.mark.parametrize("client_dev_console", [True], indirect=True)
async def test_dev_console_redirect(client_dev_console: AsyncClient) -> None:
    resp = await client_dev_console.get("/dev", follow_redirects=False)
    assert resp.status_code in (307, 308)
    assert resp.headers.get("location") == "/dev/"


@pytest.mark.parametrize("client_dev_console", [True], indirect=True)
async def test_dev_console_static_assets(client_dev_console: AsyncClient) -> None:
    resp = await client_dev_console.get("/dev/app.js")
    assert resp.status_code == 200
    assert "connectWs" in resp.text
    assert "deckhand_dev_virtual_tiles_v2" in resp.text

    resp_tb = await client_dev_console.get("/dev/tile-behavior.js")
    assert resp_tb.status_code == 200
    assert "DeckhandTileBehavior" in resp_tb.text

    resp_schema = await client_dev_console.get("/dev/action-settings.json")
    assert resp_schema.status_code == 200
    data = resp_schema.json()
    assert "com.deckhand.agent.status" in data
    assert "com.deckhand.agent.slot" in data
    assert "com.deckhand.agent.dashboard" in data


@pytest.mark.parametrize("client_dev_console", [True], indirect=True)
async def test_dev_console_index_loads_tile_scripts(client_dev_console: AsyncClient) -> None:
    resp = await client_dev_console.get("/dev/")
    assert "tile-behavior.js" in resp.text
    assert "Virtual buttons" in resp.text


@pytest.mark.parametrize("client_dev_console", [False], indirect=True)
async def test_dev_console_disabled(client_dev_console: AsyncClient) -> None:
    resp = await client_dev_console.get("/dev/")
    assert resp.status_code == 404


def test_settings_dev_console_default_localhost() -> None:
    import os

    env_keys = (
        "DECKHAND_DEV_CONSOLE",
        "DECKHAND_HOST",
        "DECKHAND_CONFIG_FILE",
        "DECKHAND_API_KEY",
    )
    saved = {k: os.environ.pop(k, None) for k in env_keys}
    try:
        from deckhand.config.settings import Settings

        s = Settings()
        assert s.host == "127.0.0.1"
        assert s.dev_console_enabled is True
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_settings_dev_console_disabled_on_non_localhost(monkeypatch) -> None:
    monkeypatch.setenv("DECKHAND_HOST", "0.0.0.0")
    monkeypatch.delenv("DECKHAND_DEV_CONSOLE", raising=False)

    from deckhand.config.settings import Settings

    s = Settings()
    assert s.dev_console_enabled is False
