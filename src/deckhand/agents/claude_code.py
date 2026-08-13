"""Passive adapter reflecting an externally-running Claude Code session.

Claude Code itself runs as a long-lived CLI session owned by the user; Deckhand
cannot subprocess it. Instead, this adapter is a *reflector*: it receives
lifecycle signals pushed from Claude Code's hook system (SessionStart,
UserPromptSubmit, PreToolUse, Notification, Stop, SessionEnd) and maps them
onto Deckhand's AgentStatus model.

Because the hook surface is push-only, ``provide_input`` is not implemented in
v1 — Deckhand cannot inject text into a running Claude Code session. ``cancel``
likewise does not kill the external session; it simply records a local
transition back to IDLE so the operator sees the agent as quiescent.

Agents are created on demand per Claude Code ``session_id`` so multiple
concurrent sessions appear as distinct Deckhand agents.
"""

from __future__ import annotations

from deckhand.agents.base import AgentBase, AgentStatus
from deckhand.orchestrator.events import build_event

# Mapping of Claude Code hook event names to the AgentStatus they imply.
# SessionStart is handled as "ensure registered / IDLE"; SessionEnd is handled
# out-of-band (unregistration) by the caller.
_HOOK_STATUS_MAP: dict[str, AgentStatus] = {
    "SessionStart": AgentStatus.IDLE,
    "UserPromptSubmit": AgentStatus.RUNNING,
    "PreToolUse": AgentStatus.RUNNING,
    "PostToolUse": AgentStatus.RUNNING,
    "Notification": AgentStatus.AWAITING_INPUT,
    "Stop": AgentStatus.IDLE,
    "SubagentStop": AgentStatus.RUNNING,
}


class ClaudeCodeAgent(AgentBase):
    """Reflects the state of an externally-running Claude Code session."""

    def __init__(
        self,
        agent_id: str,
        session_id: str,
        project_root: str | None = None,
        active_file: str | None = None,
    ) -> None:
        super().__init__(
            agent_id=agent_id,
            agent_type="claude_code",
            capabilities=["cancellable", "hook_driven"],
            project_root=project_root,
            active_file=active_file,
        )
        self.session_id = session_id

    def as_dict(self) -> dict[str, object]:
        d = super().as_dict()
        d["session_id"] = self.session_id
        return d

    async def start(self) -> None:
        # The Claude Code session is owned by the user; Deckhand cannot
        # spawn one. "Starting" is effectively a no-op that ensures we are
        # at least marked IDLE so the UI shows the agent as live.
        if self.status == AgentStatus.ERROR:
            await self._set_status(AgentStatus.IDLE)

    async def cancel(self) -> None:
        # We do not (and cannot) kill the external Claude Code process.
        # Record a local transition so the operator sees a quiescent state.
        await self._set_status(AgentStatus.IDLE)
        await self._emit_event(
            build_event(
                "agent.cancelled",
                {"kind": "agent", "id": self.id},
                {"agent": self.as_dict()},
            )
        )

    async def provide_input(self, text: str) -> None:
        # The Claude Code hook surface is push-only in v1 — there is no
        # supported channel to inject text into a running session from here.
        raise NotImplementedError(
            "ClaudeCodeAgent cannot inject input; the Claude Code hook "
            "surface is read-only in v1."
        )

    async def apply_hook_event(self, event_name: str) -> None:
        """Update status in response to a Claude Code hook event."""
        target = _HOOK_STATUS_MAP.get(event_name)
        if target is None:
            return
        if self.status != target:
            await self._set_status(target)
