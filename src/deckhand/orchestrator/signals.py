from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from deckhand.metrics import Metrics
from deckhand.orchestrator.metadata import SignalMetadata

SignalHandler = Callable[[dict[str, object]], Awaitable[None]]


class SignalRegistry:
    """Maps named signals to handlers."""

    def __init__(self, metrics: Metrics | None = None) -> None:
        self._signals: dict[str, SignalHandler] = {}
        self._metadata: dict[str, SignalMetadata] = {}
        self._metrics = metrics

    def register(
        self,
        name: str,
        handler: SignalHandler,
        description: str = "",
        payload_schema: dict[str, Any] | None = None,
    ) -> None:
        """Register a signal with optional metadata."""
        self._signals[name] = handler
        self._metadata[name] = SignalMetadata(
            name=name,
            description=description,
            payload_schema=payload_schema or {},
        )

    async def handle(self, name: str, payload: dict[str, object]) -> None:
        handler = self._signals.get(name)
        if handler is None:
            raise KeyError(name)
        await handler(payload)
        if self._metrics is not None:
            self._metrics.record_signal(name)

    def list_signals(self) -> list[SignalMetadata]:
        """List all registered signals with metadata."""
        return [self._metadata[name] for name in sorted(self._signals.keys())]

    def get_signal_metadata(self, name: str) -> SignalMetadata | None:
        """Get metadata for a specific signal."""
        return self._metadata.get(name)
