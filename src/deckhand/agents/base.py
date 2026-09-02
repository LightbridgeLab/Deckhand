from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Iterable
from enum import Enum

from deckhand.orchestrator.events import build_event

_TYPE_LABELS: dict[str, str] = {
    "claude_code": "Claude",
    "claude-code": "Claude",
    "cursor": "Cursor",
    "cursor_cloud": "Cursor",
    "mock": "Demo",
}

_DISAMBIGUATOR_MAX = 24


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    ERROR = "error"


EventHandler = Callable[[dict[str, object]], Awaitable[None]]


def friendly_agent_type(agent_type: str) -> str:
    """Human label for an agent type (``claude_code`` → ``Claude``)."""
    key = agent_type.strip()
    if key in _TYPE_LABELS:
        return _TYPE_LABELS[key]
    normalized = key.replace("-", "_").lower()
    if normalized in _TYPE_LABELS:
        return _TYPE_LABELS[normalized]
    return key.replace("_", " ").replace("-", " ").title()


def project_folder_name(project_root: str | None) -> str | None:
    if not project_root:
        return None
    name = project_root.rstrip("/").rsplit("/", 1)[-1]
    return name or None


def snippet(text: str, max_len: int = _DISAMBIGUATOR_MAX) -> str:
    """Collapse whitespace and truncate for button/dropdown use."""
    compact = " ".join(text.strip().split())
    if not compact:
        return ""
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 1] + "…"


class AgentBase(ABC):
    """Base class for long-lived agents."""

    def __init__(
        self,
        agent_id: str,
        agent_type: str,
        capabilities: Iterable[str],
        project_root: str | None = None,
        active_file: str | None = None,
    ) -> None:
        self.id = agent_id
        self.type = agent_type
        self.status = AgentStatus.IDLE
        self.capabilities = list(capabilities)
        self.project_root = project_root
        self.active_file = active_file
        self.updated_at = time.time()
        self.on_event: EventHandler | None = None
        # Set by Orchestrator when two live agents share type + project.
        self.label_disambiguator: str | None = None

    @property
    def type_label(self) -> str:
        return friendly_agent_type(self.type)

    def short_id(self) -> str:
        """Stable short token: session id prefix, else the agent id."""
        session_id = getattr(self, "session_id", None)
        if isinstance(session_id, str) and session_id:
            return session_id[:8]
        return self.id

    def make_disambiguator(self) -> str:
        """Extra label when two agents share type + project."""
        return self.short_id()

    @property
    def display_label(self) -> str:
        """Context-aware label for UI display.

        Examples: ``Claude: backend``, ``Cursor: Deckhand · Please review…``,
        ``Claude · 9e77b92a`` when no project path is known.
        """
        kind = self.type_label
        project = project_folder_name(self.project_root)
        if project:
            base = f"{kind}: {project}"
        else:
            base = f"{kind} · {self.short_id()}"
        extra = self.label_disambiguator
        if extra and extra not in base:
            return f"{base} · {extra}"
        return base

    def as_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "id": self.id,
            "type": self.type,
            "type_label": self.type_label,
            "status": self.status.value,
            "capabilities": self.capabilities,
            "project_root": self.project_root,
            "active_file": self.active_file,
            "display_label": self.display_label,
            "updated_at": self.updated_at,
        }
        return d

    async def _set_status(self, status: AgentStatus) -> None:
        self.status = status
        self.updated_at = time.time()
        await self._emit_event(
            build_event(
                "agent.status_changed",
                {"kind": "agent", "id": self.id},
                {"agent": self.as_dict()},
            )
        )

    async def _emit_event(self, payload: dict[str, object]) -> None:
        if self.on_event is not None:
            await self.on_event(payload)

    @abstractmethod
    async def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def cancel(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def provide_input(self, text: str) -> None:
        raise NotImplementedError
