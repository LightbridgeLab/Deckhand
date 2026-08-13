"""Tests for the live runtime.toml bind advertisement."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from deckhand.config.runtime import (
    advertised_url,
    read_live_url,
    runtime_file_path,
    write_runtime,
)


def test_advertised_url_rewrites_wildcard_hosts() -> None:
    assert advertised_url("127.0.0.1", 18765) == "http://127.0.0.1:18765"
    assert advertised_url("0.0.0.0", 19000) == "http://127.0.0.1:19000"
    assert advertised_url("::", 19000) == "http://127.0.0.1:19000"


def test_write_and_read_live_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "runtime.toml"
    monkeypatch.setenv("DECKHAND_RUNTIME_FILE", str(path))

    written = write_runtime("127.0.0.1", 19000, pid=os.getpid())
    assert written == path
    assert 'url = "http://127.0.0.1:19000"' in path.read_text(encoding="utf-8")
    assert read_live_url() == "http://127.0.0.1:19000"


def test_read_live_url_ignores_dead_pid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "runtime.toml"
    monkeypatch.setenv("DECKHAND_RUNTIME_FILE", str(path))
    write_runtime("127.0.0.1", 19000, pid=1_000_000_000)
    assert read_live_url() is None


def test_read_live_url_missing_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DECKHAND_RUNTIME_FILE", str(tmp_path / "nope.toml"))
    assert read_live_url() is None


def test_runtime_file_path_honors_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "custom.toml"
    monkeypatch.setenv("DECKHAND_RUNTIME_FILE", str(target))
    assert runtime_file_path() == target
