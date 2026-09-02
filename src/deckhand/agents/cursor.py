"""Passive adapter reflecting an externally-running Cursor IDE agent session.

Cursor sessions are owned by the user; Deckhand receives lifecycle signals from
Cursor's hook system (``~/.cursor/hooks.json``) and maps them onto AgentStatus.
"""

from __future__ import annotations

from deckhand.agents.base import AgentBase, AgentStatus, snippet
from deckhand.orchestrator.events import build_event

# Cursor hook event names (camelCase as emitted by Cursor).
_HOOK_STATUS_MAP: dict[str, AgentStatus] = {
    "sessionStart": AgentStatus.IDLE,
    "beforeSubmitPrompt": AgentStatus.RUNNING,
    "preToolUse": AgentStatus.RUNNING,
    "postToolUse": AgentStatus.RUNNING,
    "subagentStart": AgentStatus.RUNNING,
    "subagentStop": AgentStatus.RUNNING,
    "afterAgentResponse": AgentStatus.RUNNING,
    "stop": AgentStatus.IDLE,
    "postToolUseFailure": AgentStatus.ERROR,
}


class CursorAgent(AgentBase):
    """Reflects the state of a Cursor IDE agent session."""

    def __init__(
        self,
        agent_id: str,
        session_id: str,
        project_root: str | None = None,
        active_file: str | None = None,
        title: str | None = None,
    ) -> None:
        super().__init__(
            agent_id=agent_id,
            agent_type="cursor",
            capabilities=["cancellable", "hook_driven", "focusable"],
            project_root=project_root,
            active_file=active_file,
        )
        self.session_id = session_id
        self.title = title

    def make_disambiguator(self) -> str:
        if self.title:
            clipped = snippet(self.title)
            if clipped:
                return clipped
        return super().make_disambiguator()

    def as_dict(self) -> dict[str, object]:
        d = super().as_dict()
        d["session_id"] = self.session_id
        if self.title:
            d["title"] = self.title
        return d

    async def start(self) -> None:
        if self.status == AgentStatus.ERROR:
            await self._set_status(AgentStatus.IDLE)

    async def cancel(self) -> None:
        await self._set_status(AgentStatus.IDLE)
        await self._emit_event(
            build_event(
                "agent.cancelled",
                {"kind": "agent", "id": self.id},
                {"agent": self.as_dict()},
            )
        )

    async def provide_input(self, text: str) -> None:
        raise NotImplementedError(
            "CursorAgent cannot inject input; the Cursor hook surface is "
            "read-only in v1."
        )

    async def apply_hook_event(
        self,
        event_name: str,
        *,
        deckhand_status: str | None = None,
    ) -> None:
        """Update status in response to a Cursor hook event."""
        if deckhand_status:
            try:
                target = AgentStatus(deckhand_status)
            except ValueError:
                return
            if self.status != target:
                await self._set_status(target)
            return

        target = _HOOK_STATUS_MAP.get(event_name)
        if target is None:
            return
        if self.status != target:
            await self._set_status(target)
