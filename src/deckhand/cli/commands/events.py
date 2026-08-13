"""Event-bus CLI commands."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable
from pathlib import Path

from deckhand.cli.client import DeckhandClient
from deckhand.cli.formatters import emit_json

_POLL_INTERVAL_SEC = 0.25


def tail_live(client: DeckhandClient, type_filter: Iterable[str]) -> None:
    wanted = set(type_filter)
    with client.events() as stream:
        for event in stream:
            if wanted and event.get("type") not in wanted:
                continue
            emit_json(event)


def tail_log(path: Path, type_filter: Iterable[str], *, follow: bool) -> None:
    """Tail a JSONL log. ``follow`` polls and survives rotation/truncation.

    Polling detects:
    - Inode change (rename + new file under the same path → rotation).
    - File shrunk below the reader's last position (in-place truncation).

    Same-size in-place rewrite is not observable via polling without
    content comparison; that edge case is left for an OS-level watcher.
    """
    wanted = set(type_filter)
    if not path.exists():
        raise FileNotFoundError(str(path))

    def _matches(line: str) -> bool:
        if not wanted:
            return True
        try:
            return json.loads(line).get("type") in wanted
        except json.JSONDecodeError:
            return False

    def _read_and_emit(fh) -> None:
        for line in fh:
            line = line.rstrip("\n")
            if line and _matches(line):
                emit_json(json.loads(line))

    fh = path.open("r", encoding="utf-8")
    try:
        _read_and_emit(fh)
        if not follow:
            return

        while True:
            where = fh.tell()
            line = fh.readline()
            if line:
                line = line.rstrip("\n")
                if line and _matches(line):
                    emit_json(json.loads(line))
                continue

            # No new data. Detect truncation or rotation, then sleep.
            if _file_was_replaced_or_truncated(path, fh, where):
                fh.close()
                fh = path.open("r", encoding="utf-8")
                _read_and_emit(fh)
                continue

            time.sleep(_POLL_INTERVAL_SEC)
            fh.seek(where)
    finally:
        fh.close()


def _file_was_replaced_or_truncated(path: Path, fh, last_pos: int) -> bool:
    """Detect log rotation (new inode at path) or truncation (size shrunk)."""
    try:
        path_stat = path.stat()
    except FileNotFoundError:
        return False  # rotated away with no replacement yet; keep tailing fh

    try:
        fh_stat = os.fstat(fh.fileno())
    except OSError:
        return True

    if path_stat.st_ino != fh_stat.st_ino:
        return True  # path now points at a different inode (rotated)
    # True when the file was truncated under us.
    return path_stat.st_size < last_pos
