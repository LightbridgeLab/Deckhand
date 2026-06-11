"""Plugin capability model.

Plugins declare a capability level in configuration. The registry passed to
each plugin's ``register()`` function is scoped to that capability — attempts
to call methods outside the allowed set raise ``PermissionError``.

Capabilities (cumulative):

- ``read-only``: list/inspect actions and signals, read state, subscribe to
  events. Cannot register handlers, mutate state, emit events, or access the
  orchestrator.
- ``state-only``: everything in ``read-only`` plus state mutation, signal
  registration, and event emission. No orchestrator access and cannot
  register *or invoke* actions (which by definition drive orchestrator
  commands).
- ``full``: unrestricted access, equivalent to the raw ``PluginRegistry``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from deckhand.orchestrator.actions import ActionRegistry
from deckhand.orchestrator.events import EventBus
from deckhand.orchestrator.metadata import ActionMetadata, SignalMetadata
from deckhand.orchestrator.signals import SignalRegistry
from deckhand.orchestrator.state import StateStore
from deckhand.plugins.registry import PluginRegistry

Capability = Literal["read-only", "state-only", "full"]

VALID_CAPABILITIES: tuple[Capability, ...] = ("read-only", "state-only", "full")


def _deny(capability: str, op: str) -> "PermissionError":
    return PermissionError(
        f"Plugin with capability '{capability}' is not permitted to {op}"
    )


@dataclass(frozen=True)
class PluginSpec:
    """A plugin module path paired with its declared capability."""

    module: str
    capability: Capability = "full"


class ScopedActionRegistry:
    """ActionRegistry proxy that enforces a capability level."""

    def __init__(self, inner: ActionRegistry, capability: Capability) -> None:
        self._inner = inner
        self._capability = capability

    def register(
        self,
        name: str,
        handler: Any,
        description: str = "",
        payload_schema: dict[str, Any] | None = None,
    ) -> None:
        if self._capability != "full":
            raise _deny(self._capability, "register actions")
        self._inner.register(name, handler, description, payload_schema)

    async def run(self, name: str, payload: dict[str, object]) -> None:
        if self._capability != "full":
            raise _deny(self._capability, "run actions")
        await self._inner.run(name, payload)

    def list_actions(self) -> list[ActionMetadata]:
        return self._inner.list_actions()

    def get_action_metadata(self, name: str) -> ActionMetadata | None:
        return self._inner.get_action_metadata(name)


class ScopedSignalRegistry:
    """SignalRegistry proxy that enforces a capability level."""

    def __init__(self, inner: SignalRegistry, capability: Capability) -> None:
        self._inner = inner
        self._capability = capability

    def register(
        self,
        name: str,
        handler: Any,
        description: str = "",
        payload_schema: dict[str, Any] | None = None,
    ) -> None:
        if self._capability == "read-only":
            raise _deny(self._capability, "register signals")
        self._inner.register(name, handler, description, payload_schema)

    async def handle(self, name: str, payload: dict[str, object]) -> None:
        await self._inner.handle(name, payload)

    def list_signals(self) -> list[SignalMetadata]:
        return self._inner.list_signals()

    def get_signal_metadata(self, name: str) -> SignalMetadata | None:
        return self._inner.get_signal_metadata(name)


class ScopedStateStore:
    """StateStore proxy that enforces a capability level.

    This wrapper deliberately exposes an **explicit allow-list** of
    ``StateStore`` methods. There is no ``__getattr__`` fallback: any new
    method added to ``StateStore`` is invisible to plugins until it is
    explicitly proxied here with the appropriate capability check. This
    ensures that future write-capable methods (e.g. ``bulk_set``, ``purge``)
    cannot silently be reached by ``read-only`` plugins.

    When adding a new ``StateStore`` method, decide whether it is a read or
    a write operation and add a corresponding proxy method below. Write
    operations must guard against ``read-only`` via ``_deny``.
    """

    def __init__(self, inner: StateStore, capability: Capability) -> None:
        self._inner = inner
        self._capability = capability

    # --- read operations (allowed for all capability levels) ---

    def list_state(self) -> list[dict[str, Any]]:
        return self._inner.list_state()

    def entry_count(self) -> int:
        return self._inner.entry_count()

    def get_state(self, key: str) -> dict[str, Any] | None:
        return self._inner.get_state(key)

    def is_writable(self) -> bool:
        return self._capability != "read-only" and self._inner.is_writable()

    # --- write operations (denied for read-only) ---

    async def set_state(self, *args: Any, **kwargs: Any) -> Any:
        if self._capability == "read-only":
            raise _deny(self._capability, "write state")
        return await self._inner.set_state(*args, **kwargs)

    async def clear_state(self, *args: Any, **kwargs: Any) -> Any:
        if self._capability == "read-only":
            raise _deny(self._capability, "write state")
        return await self._inner.clear_state(*args, **kwargs)


class ScopedEventBus:
    """EventBus proxy that enforces a capability level."""

    def __init__(self, inner: EventBus, capability: Capability) -> None:
        self._inner = inner
        self._capability = capability

    @property
    def client_count(self) -> int:
        return self._inner.client_count

    async def subscribe(self, *args: Any, **kwargs: Any) -> Any:
        return await self._inner.subscribe(*args, **kwargs)

    def unsubscribe(self, *args: Any, **kwargs: Any) -> Any:
        return self._inner.unsubscribe(*args, **kwargs)

    async def emit(self, event: dict[str, Any]) -> None:
        if self._capability == "read-only":
            raise _deny(self._capability, "emit events")
        await self._inner.emit(event)


def build_scoped_registry(
    base: PluginRegistry, capability: Capability
) -> PluginRegistry:
    """Return a PluginRegistry scoped to the given capability level."""
    if capability not in VALID_CAPABILITIES:
        raise ValueError(
            f"Unknown plugin capability '{capability}'. "
            f"Valid values: {', '.join(VALID_CAPABILITIES)}"
        )
    if capability == "full":
        return base
    return PluginRegistry(
        actions=ScopedActionRegistry(base.actions, capability),  # type: ignore[arg-type]
        signals=ScopedSignalRegistry(base.signals, capability),  # type: ignore[arg-type]
        state=ScopedStateStore(base.state, capability),  # type: ignore[arg-type]
        events=ScopedEventBus(base.events, capability),  # type: ignore[arg-type]
        orchestrator=None,
        _shutdown_hooks=base._shutdown_hooks,
    )
