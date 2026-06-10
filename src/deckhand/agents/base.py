from __future__ import annotations

import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Awaitable, Callable, Iterable, Optional

from deckhand.orchestrator.events import build_event


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    ERROR = "error"


EventHandler = Callable[[dict[str, object]], Awaitable[None]]


class AgentBase(ABC):
    """Base class for long-lived agents."""

    def __init__(
        self,
        agent_id: str,
        agent_type: str,
        capabilities: Iterable[str],
        project_root: Optional[str] = None,
        active_file: Optional[str] = None,
    ) -> None:
        self.id = agent_id
        self.type = agent_type
        self.status = AgentStatus.IDLE
        self.capabilities = list(capabilities)
        self.project_root = project_root
        self.active_file = active_file
        self.updated_at = time.time()
        self.on_event: Optional[EventHandler] = None

    @property
    def display_label(self) -> str:
        """Context-aware label for UI display.

        Returns a label like "Claude: feature-x" when project context is
        available, falling back to the agent id.
        """
        if not self.project_root:
            return self.id
        # Use the last path component as a short project name
        project_name = self.project_root.rstrip("/").rsplit("/", 1)[-1]
        return f"{self.type}: {project_name}"

    def as_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "id": self.id,
            "type": self.type,
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
