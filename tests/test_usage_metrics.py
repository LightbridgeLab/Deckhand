"""Tests for shared plan-bar metric helpers."""

from __future__ import annotations

import logging

import pytest

from deckhand.integrations.usage_metrics import (
    backoff_poll_delay,
    clamp_poll_interval,
    parse_retry_after_seconds,
    plan_bar_value,
)


def test_plan_bar_value_available() -> None:
    value = plan_bar_value(
        label="Current session",
        short_label="Session",
        percent=36.0,
        resets_at="2026-08-11T18:00:00+00:00",
        updated_at=1.0,
        available=True,
    )
    assert value["percent"] == 36.0
    assert value["title"] == "Session\n36%"
    assert value["max"] == 100


def test_plan_bar_value_unavailable() -> None:
    value = plan_bar_value(
        label="Credits",
        short_label="Credits",
        percent=None,
        resets_at=None,
        updated_at=1.0,
        available=False,
    )
    assert value["percent"] is None
    assert value["title"] == "Credits\n—"


def test_clamp_poll_interval(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        clamped = clamp_poll_interval(
            "poll_interval_seconds",
            0.1,
            minimum=1.0,
            log=logging.getLogger("test"),
            plugin_id="demo",
        )
    assert clamped == 1.0
    assert "below minimum" in caplog.text


def test_parse_retry_after_seconds_numeric() -> None:
    assert parse_retry_after_seconds("120") == 120.0
    assert parse_retry_after_seconds(" 0 ") == 0.0
    assert parse_retry_after_seconds(None) is None
    assert parse_retry_after_seconds("nope") is None


def test_parse_retry_after_http_date() -> None:
    header = "Thu, 13 Aug 2026 16:00:00 GMT"
    now = 1786636740.0  # 2026-08-13 15:59:00 GMT
    delay = parse_retry_after_seconds(header, now=now)
    assert delay == pytest.approx(60.0)


def test_backoff_poll_delay_exponential_and_retry_after() -> None:
    assert backoff_poll_delay(1, 60.0) == 60.0
    assert backoff_poll_delay(2, 60.0) == 120.0
    assert backoff_poll_delay(3, 60.0) == 240.0
    assert backoff_poll_delay(8, 60.0) == 900.0
    assert backoff_poll_delay(1, 60.0, retry_after=30.0) == 60.0
    assert backoff_poll_delay(1, 60.0, retry_after=600.0) == 600.0
    assert backoff_poll_delay(1, 60.0, retry_after=1200.0) == 1200.0
