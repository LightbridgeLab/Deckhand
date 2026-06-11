"""Tests for the deckhand.plugins.claude_code_usage built-in plugin."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from deckhand.orchestrator.events import EventBus
from deckhand.orchestrator.state import StateStore
from deckhand.plugins import claude_code_usage as ccu


# ----------------------------------------------------- fixtures + helpers ---


@pytest.fixture
def state() -> StateStore:
    return StateStore(EventBus())


def _registry_stub(state: StateStore):
    class _StubRegistry:
        pass

    r = _StubRegistry()
    r.state = state
    return r


def _record(
    *,
    timestamp: datetime,
    model: str,
    input_tokens: int = 0,
    cache_creation: int = 0,
    cache_read: int = 0,
    output: int = 0,
) -> dict[str, Any]:
    return {
        "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
        "message": {
            "model": model,
            "role": "assistant",
            "usage": {
                "input_tokens": input_tokens,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
                "output_tokens": output,
            },
        },
    }


def _write_session(path: Path, *records: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def _seed(data_dir: Path, *records: dict[str, Any], project: str = "p") -> None:
    path = data_dir / "projects" / project / "session.jsonl"
    _write_session(path, *records)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _run_poll(state: StateStore, data_dir: Path, **kwargs) -> ccu.UsagePoller:
    caps = kwargs.pop("caps", None) or {
        "session_tokens": None,
        "week_tokens": None,
        "week_sonnet_tokens": None,
    }
    poller = ccu.UsagePoller(
        registry=_registry_stub(state),
        data_dir=data_dir,
        poll_interval=kwargs.pop("poll_interval", 30.0),
        session_window_hours=kwargs.pop("session_window_hours", 5.0),
        caps=caps,
    )
    await poller.poll_once()
    return poller


# ----------------------------------------------------- happy-path metrics --


async def test_publishes_three_metric_keys(state: StateStore, tmp_path: Path) -> None:
    _seed(
        tmp_path,
        _record(
            timestamp=_now() - timedelta(minutes=10),
            model="claude-opus-4-7",
            input_tokens=100,
            output=200,
        ),
    )
    await _run_poll(state, tmp_path)

    keys = {entry["key"] for entry in state.list_state()}
    assert "usage.claude_code.session_tokens" in keys
    assert "usage.claude_code.week_tokens" in keys
    assert "usage.claude_code.week_sonnet_tokens" in keys


async def test_state_value_shape(state: StateStore, tmp_path: Path) -> None:
    _seed(
        tmp_path,
        _record(
            timestamp=_now() - timedelta(minutes=5),
            model="claude-opus-4-7",
            input_tokens=10,
            output=20,
        ),
    )
    await _run_poll(state, tmp_path)
    entry = state.get_state("usage.claude_code.session_tokens")
    value = entry["value"]
    assert set(value.keys()) == {
        "label",
        "current",
        "max",
        "percent",
        "unit",
        "updated_at",
    }
    assert value["unit"] == "tokens"
    assert value["max"] is None
    assert value["percent"] is None
    assert value["current"] == 30


# --------------------------------------------------------- token counting --


async def test_token_total_excludes_cache_read(
    state: StateStore, tmp_path: Path
) -> None:
    _seed(
        tmp_path,
        _record(
            timestamp=_now() - timedelta(minutes=5),
            model="claude-opus-4-7",
            input_tokens=10,
            cache_creation=20,
            cache_read=9999,  # must NOT be counted
            output=30,
        ),
    )
    await _run_poll(state, tmp_path)
    entry = state.get_state("usage.claude_code.session_tokens")
    assert entry["value"]["current"] == 60  # 10 + 20 + 30


async def test_skips_records_without_usage(state: StateStore, tmp_path: Path) -> None:
    """User messages and file-history-snapshot records carry no usage."""
    records = [
        {"type": "file-history-snapshot", "timestamp": _now().isoformat()},
        {
            "timestamp": _now().isoformat(),
            "message": {"role": "user", "content": "hi"},
        },
        _record(
            timestamp=_now() - timedelta(minutes=5),
            model="claude-opus-4-7",
            output=50,
        ),
    ]
    _seed(tmp_path, *records)
    await _run_poll(state, tmp_path)
    assert state.get_state("usage.claude_code.session_tokens")["value"]["current"] == 50


async def test_skips_malformed_lines(state: StateStore, tmp_path: Path) -> None:
    """Garbage JSON lines must not abort the parse."""
    path = tmp_path / "projects" / "p" / "session.jsonl"
    path.parent.mkdir(parents=True)
    good = _record(
        timestamp=_now() - timedelta(minutes=1),
        model="claude-opus-4-7",
        output=42,
    )
    with path.open("w") as fh:
        fh.write("{not json\n")
        fh.write("\n")
        fh.write(json.dumps(good) + "\n")
        fh.write("null\n")
    await _run_poll(state, tmp_path)
    assert state.get_state("usage.claude_code.session_tokens")["value"]["current"] == 42


# -------------------------------------------------------------- windows ----


async def test_session_window_excludes_older_records(
    state: StateStore, tmp_path: Path
) -> None:
    """A record older than session_window_hours appears in week_tokens but not session_tokens."""
    _seed(
        tmp_path,
        _record(
            timestamp=_now() - timedelta(hours=10),  # outside 5h session
            model="claude-opus-4-7",
            output=100,
        ),
        _record(
            timestamp=_now() - timedelta(minutes=30),  # inside 5h
            model="claude-opus-4-7",
            output=50,
        ),
    )
    await _run_poll(state, tmp_path)
    assert state.get_state("usage.claude_code.session_tokens")["value"]["current"] == 50
    assert state.get_state("usage.claude_code.week_tokens")["value"]["current"] == 150


async def test_week_window_excludes_older_files(
    state: StateStore, tmp_path: Path
) -> None:
    """A session log whose mtime is >7d old is skipped entirely (perf)."""
    old_session = tmp_path / "projects" / "old" / "session.jsonl"
    _write_session(
        old_session,
        _record(
            timestamp=_now() - timedelta(days=20),
            model="claude-opus-4-7",
            output=9999,
        ),
    )
    # Force mtime well outside the 7d window.
    twenty_days_ago = time.time() - 20 * 86400
    import os as _os

    _os.utime(old_session, (twenty_days_ago, twenty_days_ago))

    recent = tmp_path / "projects" / "recent" / "session.jsonl"
    _write_session(
        recent,
        _record(
            timestamp=_now() - timedelta(hours=1),
            model="claude-opus-4-7",
            output=7,
        ),
    )

    await _run_poll(state, tmp_path)
    assert state.get_state("usage.claude_code.week_tokens")["value"]["current"] == 7


# --------------------------------------------------------------- Sonnet ----


async def test_sonnet_filter_isolates_sonnet_models(
    state: StateStore, tmp_path: Path
) -> None:
    _seed(
        tmp_path,
        _record(
            timestamp=_now() - timedelta(minutes=1),
            model="claude-opus-4-7",
            output=1000,
        ),
        _record(
            timestamp=_now() - timedelta(minutes=2),
            model="claude-sonnet-4-6",
            output=500,
        ),
        _record(
            timestamp=_now() - timedelta(minutes=3),
            model="claude-haiku-4-5",
            output=250,
        ),
    )
    await _run_poll(state, tmp_path)
    assert state.get_state("usage.claude_code.week_tokens")["value"]["current"] == 1750
    assert (
        state.get_state("usage.claude_code.week_sonnet_tokens")["value"]["current"]
        == 500
    )


@pytest.mark.parametrize(
    "model",
    [
        "claude-sonnet-4-6",
        "claude-3-5-sonnet-20241022",
        "Claude-Sonnet-4",  # case-insensitive
    ],
)
async def test_sonnet_filter_matches_variants(
    state: StateStore, tmp_path: Path, model: str
) -> None:
    _seed(
        tmp_path,
        _record(
            timestamp=_now() - timedelta(minutes=1),
            model=model,
            output=100,
        ),
    )
    await _run_poll(state, tmp_path)
    assert (
        state.get_state("usage.claude_code.week_sonnet_tokens")["value"]["current"]
        == 100
    )


# ----------------------------------------------------------------- caps ----


async def test_percent_computed_when_cap_set(state: StateStore, tmp_path: Path) -> None:
    _seed(
        tmp_path,
        _record(
            timestamp=_now() - timedelta(minutes=1),
            model="claude-opus-4-7",
            output=250,
        ),
    )
    caps = {
        "session_tokens": 1000,
        "week_tokens": None,
        "week_sonnet_tokens": None,
    }
    await _run_poll(state, tmp_path, caps=caps)
    entry = state.get_state("usage.claude_code.session_tokens")["value"]
    assert entry["current"] == 250
    assert entry["max"] == 1000
    assert entry["percent"] == 25.0
    # Cap-less metric still null.
    assert state.get_state("usage.claude_code.week_tokens")["value"]["percent"] is None


async def test_zero_or_negative_cap_treated_as_unset(
    state: StateStore, tmp_path: Path
) -> None:
    _seed(
        tmp_path,
        _record(
            timestamp=_now() - timedelta(minutes=1),
            model="claude-opus-4-7",
            output=10,
        ),
    )
    # _optional_int filters non-positive values; pass through what register() would.
    caps = {
        "session_tokens": ccu._optional_int(0),
        "week_tokens": ccu._optional_int(-1),
        "week_sonnet_tokens": ccu._optional_int(None),
    }
    await _run_poll(state, tmp_path, caps=caps)
    for key in (
        "usage.claude_code.session_tokens",
        "usage.claude_code.week_tokens",
        "usage.claude_code.week_sonnet_tokens",
    ):
        assert state.get_state(key)["value"]["percent"] is None


# ----------------------------------------------------------- empty state ----


async def test_no_data_dir_publishes_zero_metrics(
    state: StateStore, tmp_path: Path
) -> None:
    # tmp_path has no projects/ subdir → poller publishes zeroes.
    await _run_poll(state, tmp_path)
    for key in (
        "usage.claude_code.session_tokens",
        "usage.claude_code.week_tokens",
        "usage.claude_code.week_sonnet_tokens",
    ):
        assert state.get_state(key)["value"]["current"] == 0
