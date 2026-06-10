"""Event-bus CLI commands."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterable

from deckhand.cli.client import DeckhandClient
from deckhand.cli.formatters import emit_json


def tail_live(client: DeckhandClient, type_filter: Iterable[str]) -> None:
    wanted = set(type_filter)
    with client.events() as stream:
        for event in stream:
            if wanted and event.get("type") not in wanted:
                continue
            emit_json(event)


def tail_log(path: Path, type_filter: Iterable[str], *, follow: bool) -> None:
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

    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line and _matches(line):
                emit_json(json.loads(line))

        if not follow:
            return

        while True:
            where = fh.tell()
            line = fh.readline()
            if not line:
                time.sleep(0.25)
                fh.seek(where)
                continue
            line = line.rstrip("\n")
            if line and _matches(line):
                emit_json(json.loads(line))
