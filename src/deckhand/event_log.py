"""Append-only JSONL event log.

Off by default. Enable in ``config.toml``::

    [event_log]
    enabled = true
    path = ".deckhand/events.log"

Or via env: ``DECKHAND_EVENT_LOG_ENABLED=1`` and ``DECKHAND_EVENT_LOG=<path>``.

Default path is ``./.deckhand/events.log`` (relative to the service's working
directory). The directory is created on first write.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class EventLogger:
    """Async-safe JSONL writer registered as an EventBus listener."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = asyncio.Lock()
        self._dir_ready = False

    @property
    def path(self) -> Path:
        return self._path

    async def __call__(self, event: dict[str, Any]) -> None:
        try:
            line = json.dumps(event, default=_json_default) + "\n"
        except (TypeError, ValueError) as exc:
            logger.warning("Failed to serialize event for log: %s", exc)
            return
        async with self._lock:
            await asyncio.to_thread(self._write_line, line)

    def _write_line(self, line: str) -> None:
        if not self._dir_ready:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._dir_ready = True
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(line)


def _json_default(value: Any) -> Any:
    if hasattr(value, "as_dict"):
        return value.as_dict()
    if hasattr(value, "value"):  # Enum-like
        return value.value
    return str(value)
