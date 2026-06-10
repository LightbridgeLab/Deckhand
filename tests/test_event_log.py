"""Tests for the JSONL event log."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from deckhand.event_log import EventLogger
from deckhand.orchestrator.events import EventBus, build_event


@pytest.fixture
def log_path(tmp_path: Path) -> Path:
    return tmp_path / "subdir" / "events.log"


async def test_event_logger_writes_jsonl(log_path: Path) -> None:
    logger = EventLogger(log_path)
    event = build_event(
        "state.changed",
        {"kind": "state", "id": "foo"},
        {"key": "foo", "value": 1},
    )

    await logger(event)
    await logger(event)

    assert log_path.exists()
    lines = log_path.read_text().splitlines()
    assert len(lines) == 2
    parsed = json.loads(lines[0])
    assert parsed["type"] == "state.changed"
    assert parsed["payload"]["key"] == "foo"


async def test_event_logger_creates_parent_dir(log_path: Path) -> None:
    assert not log_path.parent.exists()
    logger = EventLogger(log_path)
    await logger(build_event("test", {"kind": "test", "id": "1"}, {}))
    assert log_path.parent.is_dir()


async def test_event_logger_registered_on_bus(log_path: Path) -> None:
    bus = EventBus()
    logger = EventLogger(log_path)
    bus.add_listener(logger)

    await bus.emit(build_event("test.a", {"kind": "test", "id": "a"}, {"n": 1}))
    await bus.emit(build_event("test.b", {"kind": "test", "id": "b"}, {"n": 2}))

    await asyncio.sleep(0)  # let any deferred work settle
    lines = log_path.read_text().splitlines()
    assert [json.loads(line)["type"] for line in lines] == ["test.a", "test.b"]


async def test_listener_failure_does_not_break_emit(tmp_path: Path) -> None:
    bus = EventBus()
    bad_calls: list[int] = []
    good_calls: list[int] = []

    async def bad(event: dict) -> None:
        bad_calls.append(1)
        raise RuntimeError("boom")

    async def good(event: dict) -> None:
        good_calls.append(1)

    bus.add_listener(bad)
    bus.add_listener(good)

    await bus.emit(build_event("test", {"kind": "t", "id": "x"}, {}))

    assert len(bad_calls) == 1
    assert len(good_calls) == 1


async def test_remove_listener(log_path: Path) -> None:
    bus = EventBus()
    logger = EventLogger(log_path)
    bus.add_listener(logger)
    bus.remove_listener(logger)

    await bus.emit(build_event("test", {"kind": "t", "id": "x"}, {}))
    assert not log_path.exists()
