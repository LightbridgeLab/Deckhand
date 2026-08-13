"""Tests for Cursor spending parse/auth helpers and poller."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from deckhand.catalog.state_keys import seed_entries_for_plugins
from deckhand.integrations import cursor_usage as cu
from deckhand.orchestrator.events import EventBus
from deckhand.orchestrator.state import StateStore
from deckhand.plugins import cursor_usage as plugin


@pytest.fixture
def state() -> StateStore:
    return StateStore(EventBus())


@pytest.fixture(autouse=True)
def _clear_runtime_token() -> None:
    cu._reset_runtime_token_for_tests()
    yield
    cu._reset_runtime_token_for_tests()


def _registry_stub(state: StateStore):
    class _StubRegistry:
        def __init__(self) -> None:
            self.shutdown_hooks: list = []

        def on_shutdown(self, hook) -> None:
            self.shutdown_hooks.append(hook)

    r = _StubRegistry()
    r.state = state
    return r


def _sample_payload() -> dict[str, Any]:
    """Shape verified against GetCurrentPeriodUsage (Pro+ spending UI)."""
    return {
        "billingCycleStart": "1784061150000",
        "billingCycleEnd": "1786739550000",
        "planUsage": {
            "totalSpend": 3544,
            "includedSpend": 3544,
            "remaining": 3456,
            "limit": 7000,
            "autoPercentUsed": 3.08375,
            "apiPercentUsed": 9.790909090909091,
            "totalPercentUsed": 3.8945054945054944,
        },
        "spendLimitUsage": {
            "individualLimit": 5000,
            "individualRemaining": 5000,
            "limitType": "user",
        },
        "autoModelSelectedDisplayMessage": "You've used 4% of your included total usage",
        "namedModelSelectedDisplayMessage": "You've used 10% of your included API usage",
        "autoBucketModels": ["default", "composer-2.5", "grok-4.5"],
    }


def _make_state_db(
    path: Path, *, access: str = "access-jwt", refresh: str | None = "refresh-jwt"
) -> Path:
    con = sqlite3.connect(str(path))
    try:
        con.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
        con.execute(
            "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
            ("cursorAuth/accessToken", access),
        )
        if refresh is not None:
            con.execute(
                "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
                ("cursorAuth/refreshToken", refresh),
            )
        con.commit()
    finally:
        con.close()
    return path


def test_parse_plan_bars_maps_spending_ui() -> None:
    bars = {b.key: b for b in cu.parse_plan_bars(_sample_payload())}
    assert set(bars) == {
        "usage.cursor.models",
        "usage.cursor.other",
        "usage.cursor.on_demand",
    }
    assert bars["usage.cursor.models"].percent == pytest.approx(3.08375)
    assert bars["usage.cursor.models"].short_label == "Models"
    assert bars["usage.cursor.models"].available is True
    assert bars["usage.cursor.other"].percent == pytest.approx(9.790909090909091)
    assert bars["usage.cursor.other"].short_label == "Other"
    assert bars["usage.cursor.on_demand"].percent == pytest.approx(0.0)
    assert bars["usage.cursor.on_demand"].available is True
    # billingCycleEnd 1786739550000 ms → ISO
    assert bars["usage.cursor.models"].resets_at is not None
    assert bars["usage.cursor.models"].resets_at.startswith("2026-")


def test_parse_plan_bars_on_demand_from_individual_used() -> None:
    payload = _sample_payload()
    payload["spendLimitUsage"] = {
        "individualLimit": 5000,
        "individualUsed": 1250,
        "individualRemaining": 3750,
        "limitType": "user",
    }
    bars = {b.key: b for b in cu.parse_plan_bars(payload)}
    assert bars["usage.cursor.on_demand"].percent == pytest.approx(25.0)


def test_parse_plan_bars_on_demand_unavailable_without_limit() -> None:
    payload = _sample_payload()
    payload["spendLimitUsage"] = {"limitType": "user"}
    bars = {b.key: b for b in cu.parse_plan_bars(payload)}
    assert bars["usage.cursor.on_demand"].available is False
    assert bars["usage.cursor.on_demand"].percent is None


def test_parse_plan_bars_missing_plan_usage() -> None:
    bars = {b.key: b for b in cu.parse_plan_bars({"billingCycleEnd": "1786739550000"})}
    assert bars["usage.cursor.models"].available is False
    assert bars["usage.cursor.other"].available is False
    assert bars["usage.cursor.on_demand"].available is False


def test_read_auth_tokens_from_state_db(tmp_path: Path) -> None:
    db = _make_state_db(tmp_path / "state.vscdb")
    tokens = cu.read_auth_tokens(db_path=db)
    assert tokens["access"] == "access-jwt"
    assert tokens["refresh"] == "refresh-jwt"
    assert cu.read_access_token(db_path=db) == "access-jwt"


def test_read_auth_tokens_missing_access(tmp_path: Path) -> None:
    db = tmp_path / "state.vscdb"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
    con.commit()
    con.close()
    with pytest.raises(cu.CursorUsageError, match="access token missing"):
        cu.read_auth_tokens(db_path=db)


def test_read_auth_tokens_missing_db(tmp_path: Path) -> None:
    with pytest.raises(cu.CursorUsageError, match="not found"):
        cu.read_auth_tokens(db_path=tmp_path / "missing.vscdb")


def test_refresh_access_token_sets_runtime(tmp_path: Path) -> None:
    db = _make_state_db(tmp_path / "state.vscdb")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"access_token": "new-access"}
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp

    token = cu.refresh_access_token(
        "refresh-jwt", client=mock_client, db_path=db, persist=True
    )
    assert token == "new-access"
    assert cu.read_access_token(db_path=db) == "new-access"
    # Persisted into DB
    assert cu.read_auth_tokens(db_path=db)["access"] == "new-access"


def test_fetch_usage_snapshot_refreshes_on_401(tmp_path: Path) -> None:
    db = _make_state_db(tmp_path / "state.vscdb")
    payload = _sample_payload()

    class _FakeResp:
        def __init__(self, status: int, body: Any) -> None:
            self.status_code = status
            self._body = body
            self.text = "unauthorized" if status == 401 else "ok"

        def json(self) -> Any:
            return self._body

    calls: list[str] = []

    class _FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, **kwargs: Any) -> _FakeResp:
            calls.append(url)
            if "GetCurrentPeriodUsage" in url:
                auth = kwargs.get("headers", {}).get("Authorization", "")
                if "new-access" in auth:
                    return _FakeResp(200, payload)
                return _FakeResp(401, {"error": "unauthorized"})
            if "oauth/token" in url:
                return _FakeResp(200, {"access_token": "new-access"})
            raise AssertionError(f"unexpected url {url}")

        def close(self) -> None:
            return None

    with patch.object(cu.httpx, "Client", _FakeClient):
        snapshot = cu.fetch_usage_snapshot(db_path=db)

    assert snapshot["planUsage"]["autoPercentUsed"] == pytest.approx(3.08375)
    assert any("oauth/token" in u for u in calls)
    assert any("GetCurrentPeriodUsage" in u for u in calls)


@pytest.mark.asyncio
async def test_poller_publishes_state(state: StateStore) -> None:
    registry = _registry_stub(state)
    poller = plugin.CursorUsagePoller(registry=registry, poll_interval=60)

    async def fake_fetch(**_kwargs):
        return cu.parse_plan_bars(_sample_payload())

    with patch.object(plugin, "fetch_plan_bars", side_effect=fake_fetch):
        await poller.poll_once()

    models = state.get_state("usage.cursor.models")
    assert models is not None
    assert models["value"]["percent"] == pytest.approx(3.08375)
    assert models["value"]["title"] == "Models\n3%"

    other = state.get_state("usage.cursor.other")
    assert other is not None
    assert other["value"]["percent"] == pytest.approx(9.790909090909091)
    assert other["value"]["title"] == "Other\n10%"

    on_demand = state.get_state("usage.cursor.on_demand")
    assert on_demand is not None
    assert on_demand["value"]["percent"] == pytest.approx(0.0)
    assert on_demand["value"]["title"] == "On-demand\n0%"


@pytest.mark.asyncio
async def test_poller_marks_unavailable_on_error(state: StateStore) -> None:
    registry = _registry_stub(state)
    poller = plugin.CursorUsagePoller(registry=registry, poll_interval=60)

    async def ok(**_kwargs):
        return cu.parse_plan_bars(_sample_payload())

    with patch.object(plugin, "fetch_plan_bars", side_effect=ok):
        await poller.poll_once()

    await poller._publish_unavailable()

    models = state.get_state("usage.cursor.models")
    assert models is not None
    assert models["value"]["percent"] is None
    assert models["value"]["title"].endswith("—")


def test_seed_entries_for_cursor() -> None:
    seeds = seed_entries_for_plugins(["deckhand.plugins.cursor_usage"])
    keys = {e.key for e in seeds}
    assert "usage.cursor.models" in keys
    assert "usage.cursor.other" in keys
    assert "usage.cursor.on_demand" in keys
    by_key = {e.key: e for e in seeds}
    assert by_key["usage.cursor.models"].image == "cursor"
    assert by_key["usage.cursor.on_demand"].image == "cursor"
