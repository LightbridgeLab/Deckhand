from __future__ import annotations

from typing import Iterable

from deckhand.agents.base import AgentBase
from deckhand.metrics import Metrics
from deckhand.orchestrator.events import EventBus
from deckhand.orchestrator.state import StateStore


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

    def register_agent(self, agent: AgentBase) -> None:
        agent.on_event = self.event_bus.emit
        self.agents[agent.id] = agent

    def unregister_agent(self, agent_id: str) -> AgentBase | None:
        agent = self.agents.pop(agent_id, None)
        if agent is not None:
            agent.on_event = None
        return agent

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
