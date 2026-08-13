"""Tests for Antigravity quota parsing and poller (Cloud Code API)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from deckhand.integrations import antigravity_quota as aq
from deckhand.orchestrator.events import EventBus
from deckhand.orchestrator.state import StateStore
from deckhand.plugins import antigravity_usage as au


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


def _sample_raw_api() -> dict[str, Any]:
    """Shape returned by retrieveUserQuotaSummary."""
    return {
        "fetchedAt": "2026-08-11T17:00:00.000Z",
        "groups": [
            {
                "displayName": "Gemini Models",
                "description": "Models within this group: Gemini Flash, Gemini Pro",
                "buckets": [
                    {
                        "bucketId": "gemini-weekly",
                        "displayName": "Weekly Limit Remaining",
                        "window": "weekly",
                        "resetTime": "2026-08-14T12:34:00.000Z",
                        "remainingFraction": 0.71,
                    },
                    {
                        "bucketId": "gemini-5h",
                        "displayName": "Five Hour Limit Remaining",
                        "window": "5h",
                        "resetTime": "2026-08-11T22:00:00.000Z",
                        "remainingFraction": 1.0,
                    },
                ],
            },
            {
                "displayName": "Claude and GPT models",
                "buckets": [
                    {
                        "window": "weekly",
                        "remainingFraction": 0.5,
                        "resetTime": "2026-08-13T00:00:00.000Z",
                    }
                ],
            },
        ],
    }


def test_remaining_fraction_to_used_percent() -> None:
    assert aq.remaining_fraction_to_used_percent(0.71) == pytest.approx(29.0)
    assert aq.remaining_fraction_to_used_percent(0.0) == pytest.approx(100.0)
    assert aq.remaining_fraction_to_used_percent(1.0) == pytest.approx(0.0)
    assert aq.remaining_fraction_to_used_percent(71.0) == pytest.approx(29.0)
    assert aq.remaining_fraction_to_used_percent(None) is None


def test_used_fraction_to_percent() -> None:
    assert aq.used_fraction_to_percent(0.29) == pytest.approx(29.0)
    assert aq.used_fraction_to_percent(29.0) == pytest.approx(29.0)
    assert aq.used_fraction_to_percent(None) is None


def test_parse_quota_snapshot_gemini_session_week() -> None:
    bars = {b.key: b for b in aq.parse_quota_snapshot(_sample_raw_api())}
    assert set(bars) == {"usage.antigravity.session", "usage.antigravity.week"}
    assert bars["usage.antigravity.session"].percent == pytest.approx(0.0)
    assert bars["usage.antigravity.session"].short_label == "Session"
    assert bars["usage.antigravity.session"].resets_at == "2026-08-11T22:00:00.000Z"
    assert bars["usage.antigravity.session"].available is True
    assert bars["usage.antigravity.week"].percent == pytest.approx(29.0)
    assert bars["usage.antigravity.week"].short_label == "Week"
    assert bars["usage.antigravity.week"].resets_at == "2026-08-14T12:34:00.000Z"
    assert bars["usage.antigravity.week"].available is True


def test_parse_quota_snapshot_ignores_non_gemini() -> None:
    bars = aq.parse_quota_snapshot(
        {
            "fetchedAt": "2026-08-11T17:00:00.000Z",
            "groups": [
                {
                    "displayName": "Claude and GPT models",
                    "buckets": [
                        {"window": "5h", "remainingFraction": 0.1},
                        {"window": "weekly", "remainingFraction": 0.2},
                    ],
                }
            ],
        }
    )
    by_key = {b.key: b for b in bars}
    assert by_key["usage.antigravity.session"].available is False
    assert by_key["usage.antigravity.week"].available is False


def test_parse_agy_cli_usage_normalized_shape() -> None:
    """Still accept the agy-cli-usage Snapshot field names if present."""
    bars = {
        b.key: b
        for b in aq.parse_quota_snapshot(
            {
                "fetchedAt": "2026-08-11T12:00:00+00:00",
                "groups": [
                    {
                        "name": "GEMINI MODELS",
                        "buckets": [
                            {
                                "kind": "5h",
                                "remainingFraction": 0.5,
                                "resetsInSeconds": 3600,
                            }
                        ],
                    }
                ],
            }
        )
    }
    assert bars["usage.antigravity.session"].percent == pytest.approx(50.0)
    assert bars["usage.antigravity.session"].resets_at == "2026-08-11T13:00:00+00:00"
    assert bars["usage.antigravity.week"].available is False


def test_parse_quota_snapshot_prefers_used_fraction() -> None:
    bars = {
        b.key: b
        for b in aq.parse_quota_snapshot(
            {
                "groups": [
                    {
                        "displayName": "Gemini Models",
                        "buckets": [
                            {
                                "window": "weekly",
                                "remainingFraction": 0.71,
                                "usedFraction": 0.4,
                            }
                        ],
                    }
                ]
            }
        )
    }
    assert bars["usage.antigravity.week"].percent == pytest.approx(40.0)


def test_decode_keychain_blob_go_keyring() -> None:
    import base64
    import json

    inner = {"token": {"access_token": "abc", "refresh_token": "xyz"}}
    raw = "go-keyring-base64:" + base64.b64encode(
        json.dumps(inner).encode()
    ).decode()
    assert aq._decode_keychain_blob(raw) == inner


@pytest.mark.asyncio
async def test_poller_publishes_state(state: StateStore) -> None:
    registry = _registry_stub(state)
    poller = au.AntigravityUsagePoller(registry=registry, poll_interval=60)

    async def fake_fetch(**_kwargs):
        return aq.parse_quota_snapshot(_sample_raw_api())

    with patch.object(au, "fetch_plan_bars", side_effect=fake_fetch):
        await poller.poll_once()

    session = state.get_state("usage.antigravity.session")
    assert session is not None
    assert session["value"]["percent"] == pytest.approx(0.0)
    assert session["value"]["title"] == "Session\n0%"

    week = state.get_state("usage.antigravity.week")
    assert week is not None
    assert week["value"]["percent"] == pytest.approx(29.0)
    assert week["value"]["title"] == "Week\n29%"
    assert week["value"]["resets_at"] == "2026-08-14T12:34:00.000Z"


@pytest.mark.asyncio
async def test_poller_marks_unavailable_on_error(state: StateStore) -> None:
    registry = _registry_stub(state)
    poller = au.AntigravityUsagePoller(registry=registry, poll_interval=60)

    async def ok(**_kwargs):
        return aq.parse_quota_snapshot(_sample_raw_api())

    async def fail(**_kwargs):
        raise aq.AntigravityQuotaError("auth failed")

    with patch.object(au, "fetch_plan_bars", side_effect=ok):
        await poller.poll_once()

    with patch.object(au, "fetch_plan_bars", side_effect=fail):
        await poller._publish_unavailable()

    session = state.get_state("usage.antigravity.session")
    assert session is not None
    assert session["value"]["percent"] is None
    assert session["value"]["title"].endswith("—")
