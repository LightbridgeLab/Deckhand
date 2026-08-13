"""Pytest fixtures for Deckhand tests."""

from __future__ import annotations

import pytest

from deckhand.agents.mock import MockAgent
from deckhand.orchestrator.actions import ActionRegistry
from deckhand.orchestrator.events import EventBus
from deckhand.orchestrator.manager import Orchestrator
from deckhand.orchestrator.signals import SignalRegistry
from deckhand.plugins.registry import PluginRegistry


@pytest.fixture(autouse=True)
def _isolate_runtime_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Keep Core's runtime.toml out of the developer's ~/.config during tests."""
    path = tmp_path_factory.mktemp("deckhand-runtime") / "runtime.toml"
    monkeypatch.setenv("DECKHAND_RUNTIME_FILE", str(path))


@pytest.fixture
def event_bus() -> EventBus:
    """Fresh EventBus instance."""
    return EventBus()


@pytest.fixture
def orchestrator(event_bus: EventBus) -> Orchestrator:
    """Orchestrator instance with mock agents."""
    orch = Orchestrator()
    orch.register_agent(MockAgent(agent_id="mock-1"))
    orch.register_agent(MockAgent(agent_id="mock-2"))
    return orch


@pytest.fixture
def state_store(event_bus: EventBus):
    """StateStore with test event bus."""
    from deckhand.orchestrator.state import StateStore

    return StateStore(event_bus)


@pytest.fixture
def action_registry(orchestrator: Orchestrator) -> ActionRegistry:
    """ActionRegistry with test orchestrator."""
    return ActionRegistry(orchestrator)


@pytest.fixture
def signal_registry() -> SignalRegistry:
    """SignalRegistry instance."""
    return SignalRegistry()


@pytest.fixture
def plugin_registry(
    action_registry: ActionRegistry,
    signal_registry: SignalRegistry,
    orchestrator: Orchestrator,
) -> PluginRegistry:
    """PluginRegistry with all test components."""
    return PluginRegistry(
        actions=action_registry,
        signals=signal_registry,
        state=orchestrator.state_store,
        events=orchestrator.event_bus,
        orchestrator=orchestrator,
    )
