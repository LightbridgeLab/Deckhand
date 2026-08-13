"""Tests for Claude OAuth plan-usage parsing and poller."""

from __future__ import annotations

from typing import Any, ClassVar
from unittest.mock import patch

import pytest

from deckhand.integrations.claude_oauth import (
    ClaudeOAuthError,
    fetch_usage_payload,
    parse_plan_bars,
)
from deckhand.orchestrator.events import EventBus
from deckhand.orchestrator.state import StateStore
from deckhand.plugins import claude_code_usage as ccu


@pytest.fixture
def state() -> StateStore:
    return StateStore(EventBus())


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
    return {
        "five_hour": {
            "utilization": 36.0,
            "resets_at": "2026-08-11T18:20:00+00:00",
        },
        "seven_day": {
            "utilization": 35.0,
            "resets_at": "2026-08-15T09:00:00+00:00",
        },
        "seven_day_sonnet": None,
        "extra_usage": {
            "is_enabled": True,
            "monthly_limit": 5000,
            "used_credits": 2100.0,
            "utilization": 42.0,
            "user_disabled": False,
        },
        "spend": {"percent": 42, "enabled": True},
        "limits": [
            {
                "kind": "session",
                "group": "session",
                "percent": 36,
                "scope": None,
            },
            {
                "kind": "weekly_all",
                "group": "weekly",
                "percent": 35,
                "scope": None,
            },
            {
                "kind": "weekly_scoped",
                "group": "weekly",
                "percent": 60,
                "resets_at": "2026-08-15T08:59:59+00:00",
                "scope": {
                    "model": {"id": None, "display_name": "Fable"},
                    "surface": None,
                },
                "is_active": True,
            },
        ],
    }


def test_parse_plan_bars_extracts_four_keys() -> None:
    bars = {b.key: b for b in parse_plan_bars(_sample_payload())}
    assert bars["usage.claude_code.session"].percent == 36.0
    assert bars["usage.claude_code.session"].short_label == "Session"
    assert bars["usage.claude_code.week"].percent == 35.0
    assert bars["usage.claude_code.week_fable"].percent == 60.0
    assert bars["usage.claude_code.week_fable"].available is True
    assert bars["usage.claude_code.credits"].percent == 42.0
    assert bars["usage.claude_code.credits"].available is True


def test_parse_plan_bars_credits_disabled() -> None:
    payload = _sample_payload()
    payload["extra_usage"]["is_enabled"] = False
    bars = {b.key: b for b in parse_plan_bars(payload)}
    assert bars["usage.claude_code.credits"].available is False
    assert bars["usage.claude_code.credits"].percent is None


def test_parse_plan_bars_missing_fable() -> None:
    payload = _sample_payload()
    payload["limits"] = [
        item for item in payload["limits"] if item["kind"] != "weekly_scoped"
    ]
    bars = {b.key: b for b in parse_plan_bars(payload)}
    assert bars["usage.claude_code.week_fable"].available is False
    assert bars["usage.claude_code.week_fable"].percent is None


def test_utilization_fraction_normalized() -> None:
    payload = _sample_payload()
    payload["five_hour"]["utilization"] = 0.36
    bars = {b.key: b for b in parse_plan_bars(payload)}
    assert bars["usage.claude_code.session"].percent == pytest.approx(36.0)


@pytest.mark.asyncio
async def test_plan_poller_publishes_state(state: StateStore) -> None:
    registry = _registry_stub(state)
    poller = ccu.PlanUsagePoller(registry=registry, poll_interval=60)

    async def fake_fetch(_client=None):
        return parse_plan_bars(_sample_payload())

    with patch.object(ccu, "fetch_plan_bars", side_effect=fake_fetch):
        await poller.poll_once()

    session = state.get_state("usage.claude_code.session")
    assert session is not None
    assert session["value"]["percent"] == 36.0
    assert session["value"]["short_label"] == "Session"
    assert session["value"]["title"] == "Session\n36%"

    fable = state.get_state("usage.claude_code.week_fable")
    assert fable is not None
    assert fable["value"]["percent"] == 60.0
    assert fable["value"]["title"] == "Fable\n60%"

    credits = state.get_state("usage.claude_code.credits")
    assert credits is not None
    assert credits["value"]["percent"] == 42.0


@pytest.mark.asyncio
async def test_plan_poller_seeds_placeholders_on_first_failure(
    state: StateStore,
) -> None:
    registry = _registry_stub(state)
    poller = ccu.PlanUsagePoller(registry=registry, poll_interval=60)
    await poller._publish_placeholders_if_empty()

    session = state.get_state("usage.claude_code.session")
    assert session is not None
    assert session["value"]["percent"] is None
    assert session["value"]["title"] == "Session\n—"
    assert state.get_state("usage.claude_code.week") is not None
    assert state.get_state("usage.claude_code.week_fable") is not None
    assert state.get_state("usage.claude_code.credits") is not None


@pytest.mark.asyncio
async def test_plan_poller_keeps_last_known_on_later_failure(state: StateStore) -> None:
    registry = _registry_stub(state)
    poller = ccu.PlanUsagePoller(registry=registry, poll_interval=60)

    async def fake_fetch(_client=None):
        return parse_plan_bars(_sample_payload())

    with patch.object(ccu, "fetch_plan_bars", side_effect=fake_fetch):
        await poller.poll_once()

    await poller._publish_placeholders_if_empty()

    session = state.get_state("usage.claude_code.session")
    assert session is not None
    assert session["value"]["percent"] == 36.0


@pytest.mark.asyncio
async def test_fetch_usage_payload_429_includes_retry_after() -> None:
    class _Resp:
        status_code = 429
        text = '{"error":{"type":"rate_limit_error"}}'
        headers: ClassVar[dict[str, str]] = {"Retry-After": "90"}

    class _Client:
        async def get(self, *_args, **_kwargs):
            return _Resp()

    with pytest.raises(ClaudeOAuthError) as exc_info:
        await fetch_usage_payload(_Client(), "token")  # type: ignore[arg-type]
    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after == 90.0
