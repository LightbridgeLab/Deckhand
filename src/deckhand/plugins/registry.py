from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from deckhand.orchestrator.actions import ActionRegistry
from deckhand.orchestrator.events import EventBus
from deckhand.orchestrator.signals import SignalRegistry
from deckhand.orchestrator.state import StateStore

if TYPE_CHECKING:
    from deckhand.orchestrator.manager import Orchestrator

logger = logging.getLogger(__name__)

ShutdownHook = Callable[[], Awaitable[None]]


@dataclass
class PluginRegistry:
    """Handed to every plugin's ``register()`` function.

    Plugins use this to register actions, signals, listeners, etc. A plugin
    that starts a background task (poller, file watcher, MQTT subscriber)
    should also register a shutdown hook via :meth:`on_shutdown` so the
    task is cancelled cleanly when the service stops — otherwise the task
    leaks until process exit.
    """

    actions: ActionRegistry
    signals: SignalRegistry
    state: StateStore
    events: EventBus
    orchestrator: Orchestrator | None
    _shutdown_hooks: list[ShutdownHook] = field(default_factory=list)

    def on_shutdown(self, hook: ShutdownHook) -> None:
        """Register an async no-arg callable to run during service shutdown."""
        self._shutdown_hooks.append(hook)

    async def run_shutdown_hooks(self) -> None:
        """Invoke every registered shutdown hook. Hook errors are logged and
        swallowed so one misbehaving plugin can't block teardown of others.
        """
        for hook in self._shutdown_hooks:
            try:
                await hook()
            except Exception:
                logger.exception("plugin shutdown hook failed")
