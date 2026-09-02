from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Iterable

from deckhand.agents.base import AgentBase
from deckhand.metrics import Metrics
from deckhand.orchestrator.events import EventBus
from deckhand.orchestrator.focusers import Focuser, FocuserRegistry
from deckhand.orchestrator.state import StateStore

logger = logging.getLogger(__name__)

# Cap any single focuser invocation so a hung focuser cannot pin the
# action handler indefinitely. Individual focusers may have their own
# tighter timeout (the iTerm one caps osascript at 5s); this is the
# safety net for any focuser that forgets.
_FOCUSER_TIMEOUT_SEC = 10.0


class Orchestrator:
    """Tracks agent lifecycle and routes commands to agents."""

    def __init__(
        self,
        state_persist_path: str | None = None,
        metrics: Metrics | None = None,
    ) -> None:
        self.agents: dict[str, AgentBase] = {}
        self.metrics = metrics
        self.event_bus = EventBus(metrics=metrics)
        self.state_store = StateStore(self.event_bus, persist_path=state_persist_path)
        self.focusers = FocuserRegistry()

    def register_agent(self, agent: AgentBase) -> None:
        agent.on_event = self.event_bus.emit
        self.agents[agent.id] = agent
        self.refresh_label_disambiguators()

    def unregister_agent(self, agent_id: str) -> AgentBase | None:
        agent = self.agents.pop(agent_id, None)
        if agent is not None:
            agent.on_event = None
        # Focusers are tied to a specific live agent registration; drop on
        # unregister so a re-registered session must re-supply its focuser.
        self.focusers.unregister(agent_id)
        self.refresh_label_disambiguators()
        return agent

    def refresh_label_disambiguators(self) -> None:
        """Suffix colliding same-type, same-project labels.

        Two Claude sessions in ``backend`` become ``Claude: backend · 9e77b92a``
        vs ``Claude: backend · 22d38fc1``. Agents without a project already
        include a short id in the base label, so they are left alone.
        """
        groups: dict[tuple[str, str], list[AgentBase]] = defaultdict(list)
        for agent in self.agents.values():
            if not agent.project_root:
                agent.label_disambiguator = None
                continue
            groups[(agent.type, agent.project_root)].append(agent)
        for group in groups.values():
            collide = len(group) > 1
            for agent in group:
                agent.label_disambiguator = (
                    agent.make_disambiguator() if collide else None
                )

    def register_focuser(self, agent_id: str, focuser: Focuser) -> None:
        self.focusers.register(agent_id, focuser)

    def list_agents(self) -> Iterable[AgentBase]:
        return self.agents.values()

    def get_agent(self, agent_id: str) -> AgentBase | None:
        return self.agents.get(agent_id)

    async def start_agent(self, agent_id: str) -> None:
        agent = self.get_agent(agent_id)
        if agent is None:
            raise KeyError(agent_id)
        await agent.start()

    async def cancel_agent(self, agent_id: str) -> None:
        agent = self.get_agent(agent_id)
        if agent is None:
            raise KeyError(agent_id)
        await agent.cancel()

    async def provide_input(self, agent_id: str, text: str) -> None:
        agent = self.get_agent(agent_id)
        if agent is None:
            raise KeyError(agent_id)
        await agent.provide_input(text)

    async def focus_agent(self, agent_id: str) -> None:
        """Bring a specific agent's window/tab to the front.

        No-op (logged) when the agent has no registered focuser — Claude
        outside iTerm, for example. Missing agent raises ``KeyError``.
        """
        agent = self.get_agent(agent_id)
        if agent is None:
            raise KeyError(agent_id)
        focuser = self.focusers.get(agent_id)
        if focuser is None:
            logger.info("agent %s has no focuser; focus is a no-op", agent_id)
            return
        try:
            await asyncio.wait_for(focuser(), timeout=_FOCUSER_TIMEOUT_SEC)
        except TimeoutError:
            logger.warning(
                "focuser for %s timed out after %.1fs",
                agent_id,
                _FOCUSER_TIMEOUT_SEC,
            )
        except Exception:
            logger.exception("focuser for %s failed", agent_id)

    async def focus_next_pending(self) -> str | None:
        """Focus the oldest agent in `awaiting_input` whose focuser is registered.

        Reads ``agents.pending_input`` from the state store fresh on every
        call — each press of a Stream Deck button thus targets the current
        head of the queue, and resolved agents drop out naturally. Returns
        the focused agent id, or ``None`` if there is no pending agent (or
        none of the pending agents have a registered focuser).
        """
        pending_entry = self.state_store.get_state("agents.pending_input")
        if not pending_entry:
            return None
        agent_ids = (pending_entry.get("value") or {}).get("agent_ids") or []
        for agent_id in agent_ids:
            focuser = self.focusers.get(agent_id)
            if focuser is None:
                logger.info("pending agent %s has no focuser; skipping", agent_id)
                continue
            try:
                await asyncio.wait_for(focuser(), timeout=_FOCUSER_TIMEOUT_SEC)
            except TimeoutError:
                logger.warning(
                    "focuser for %s timed out after %.1fs",
                    agent_id,
                    _FOCUSER_TIMEOUT_SEC,
                )
                continue
            except Exception:
                logger.exception("focuser for %s failed", agent_id)
                continue
            return agent_id
        return None
