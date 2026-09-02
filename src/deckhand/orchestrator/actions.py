from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from deckhand.metrics import Metrics
from deckhand.orchestrator.events import build_event
from deckhand.orchestrator.metadata import ActionMetadata


class OrchestratorActions(Protocol):
    async def start_agent(self, agent_id: str) -> None: ...

    async def cancel_agent(self, agent_id: str) -> None: ...

    async def provide_input(self, agent_id: str, text: str) -> None: ...

    def get_agent(self, agent_id: str) -> Any: ...

    async def focus_agent(self, agent_id: str) -> None: ...

    async def focus_next_pending(self) -> str | None: ...


ActionHandler = Callable[[dict[str, object]], Awaitable[None]]


class ActionRegistry:
    """Maps named actions to orchestrator commands."""

    def __init__(
        self,
        orchestrator: OrchestratorActions,
        metrics: Metrics | None = None,
        event_bus: Any | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._event_bus = event_bus
        self._metrics = metrics
        self._actions: dict[str, ActionHandler] = {}
        self._metadata: dict[str, ActionMetadata] = {}
        self._register_defaults()

    def register(
        self,
        name: str,
        handler: ActionHandler,
        description: str = "",
        payload_schema: dict[str, Any] | None = None,
    ) -> None:
        """Register an action with optional metadata."""
        self._actions[name] = handler
        self._metadata[name] = ActionMetadata(
            name=name,
            description=description,
            payload_schema=payload_schema or {},
        )

    async def run(self, name: str, payload: dict[str, object]) -> None:
        handler = self._actions.get(name)
        if handler is None:
            raise KeyError(name)
        try:
            await handler(payload)
        except Exception:
            if self._metrics is not None:
                self._metrics.record_action(success=False)
            raise
        if self._metrics is not None:
            self._metrics.record_action(success=True)

    def list_actions(self) -> list[ActionMetadata]:
        """List all registered actions with metadata."""
        return [self._metadata[name] for name in sorted(self._actions.keys())]

    def get_action_metadata(self, name: str) -> ActionMetadata | None:
        """Get metadata for a specific action."""
        return self._metadata.get(name)

    def _register_defaults(self) -> None:
        async def start_agent(payload: dict[str, object]) -> None:
            agent_id = payload.get("agent_id")
            if not agent_id:
                raise ValueError("agent_id is required")
            await self._orchestrator.start_agent(str(agent_id))

        async def cancel_agent(payload: dict[str, object]) -> None:
            agent_id = payload.get("agent_id")
            if not agent_id:
                raise ValueError("agent_id is required")
            await self._orchestrator.cancel_agent(str(agent_id))

        async def input_agent(payload: dict[str, object]) -> None:
            agent_id = payload.get("agent_id")
            text = payload.get("text")
            if not agent_id:
                raise ValueError("agent_id is required")
            if text is None:
                raise ValueError("text is required")
            await self._orchestrator.provide_input(str(agent_id), str(text))

        async def open_url(payload: dict[str, object]) -> None:
            url = payload.get("url")
            if not url:
                raise ValueError("url is required")
            if self._event_bus is None:
                raise RuntimeError("event bus not configured")
            await self._event_bus.emit(
                build_event(
                    "ui.open_url",
                    {"kind": "action", "id": "ui.open_url"},
                    {"url": str(url)},
                )
            )

        async def focus_next_pending(payload: dict[str, object]) -> None:
            await self._orchestrator.focus_next_pending()

        async def focus_agent(payload: dict[str, object]) -> None:
            agent_id = payload.get("agent_id")
            if not agent_id:
                raise ValueError("agent_id is required")
            await self._orchestrator.focus_agent(str(agent_id))

        async def focus_cursor_agent(payload: dict[str, object]) -> None:
            agent_id = payload.get("agent_id")
            if not agent_id:
                raise ValueError("agent_id is required")
            agent = self._orchestrator.get_agent(str(agent_id))
            if agent is None:
                raise KeyError(str(agent_id))
            project_root = agent.project_root
            url = f"cursor://file/{project_root}" if project_root else "cursor://"
            if self._event_bus is not None:
                await self._event_bus.emit(
                    build_event(
                        "ui.open_url",
                        {"kind": "action", "id": "ui.focus_cursor_agent"},
                        {
                            "url": url,
                            "agent_id": agent.id,
                            "project_root": project_root,
                        },
                    )
                )
            if sys.platform == "darwin":
                cmd = ["open", "-a", "Cursor"]
                if project_root:
                    cmd.append(project_root)
                await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )

        self.register(
            "agent.start",
            start_agent,
            description="Start an agent by ID",
            payload_schema={"agent_id": {"type": "string", "required": True}},
        )
        self.register(
            "agent.cancel",
            cancel_agent,
            description="Cancel a running agent by ID",
            payload_schema={"agent_id": {"type": "string", "required": True}},
        )
        self.register(
            "agent.input",
            input_agent,
            description="Provide input text to an agent",
            payload_schema={
                "agent_id": {"type": "string", "required": True},
                "text": {"type": "string", "required": True},
            },
        )
        self.register(
            "ui.open_url",
            open_url,
            description="Request that a client open a URL or deep link",
            payload_schema={"url": {"type": "string", "required": True}},
        )
        self.register(
            "ui.focus_cursor_agent",
            focus_cursor_agent,
            description="Focus Cursor on an agent's project (macOS opens Cursor locally)",
            payload_schema={"agent_id": {"type": "string", "required": True}},
        )
        self.register(
            "ui.focus_agent",
            focus_agent,
            description=(
                "Focus a live agent's window/tab via its registered focuser "
                "(iTerm for Claude Code, Cursor app for Cursor). No-op if "
                "the agent has no focuser."
            ),
            payload_schema={"agent_id": {"type": "string", "required": True}},
        )
        self.register(
            "agents.focus_next_pending",
            focus_next_pending,
            description=(
                "Focus the oldest agent currently awaiting input; no-op if the "
                "pending list is empty or no focuser is registered."
            ),
            payload_schema={},
        )
