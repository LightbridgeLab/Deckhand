"""Per-agent focuser registry.

A focuser is an async callable that, when invoked, brings the agent's
window/tab to the foreground on the local machine. Each agent type
registers its own focuser when the agent registers (e.g. an iTerm focuser
for a Claude Code session, an AppleScript focuser for Cursor in a future
ticket). The registry stores them keyed by agent id and the
``agents.focus_next_pending`` action looks them up at press time.

Focusers are in-process state — after a Deckhand restart they re-register
when the next hook fires from each session.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

Focuser = Callable[[], Awaitable[None]]


class FocuserRegistry:
    """Maps agent id → async focuser callable."""

    def __init__(self) -> None:
        self._focusers: dict[str, Focuser] = {}

    def register(self, agent_id: str, focuser: Focuser) -> None:
        self._focusers[agent_id] = focuser

    def unregister(self, agent_id: str) -> None:
        self._focusers.pop(agent_id, None)

    def get(self, agent_id: str) -> Focuser | None:
        return self._focusers.get(agent_id)

    def __contains__(self, agent_id: str) -> bool:
        return agent_id in self._focusers
