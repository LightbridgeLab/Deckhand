from __future__ import annotations

import importlib
import logging
from collections.abc import Iterable

from deckhand.plugins.capabilities import (
    PluginSpec,
    build_scoped_registry,
)
from deckhand.plugins.registry import PluginRegistry

logger = logging.getLogger(__name__)

PluginEntry = str | PluginSpec


def load_plugins(entries: Iterable[PluginEntry], registry: PluginRegistry) -> None:
    """Load and register plugins.

    Each entry may be either a module path string (defaults to ``full``
    capability) or a :class:`PluginSpec`. Each plugin receives a registry
    scoped to its declared capability.
    """
    for entry in entries:
        spec = (
            entry
            if isinstance(entry, PluginSpec)
            else PluginSpec(module=entry, capability="full")
        )
        module = importlib.import_module(spec.module)
        register = getattr(module, "register", None)
        if register is None:
            raise ValueError(
                f"Plugin module {spec.module} has no register(registry) function"
            )
        scoped = build_scoped_registry(registry, spec.capability)
        logger.info(
            "Loading plugin %s with capability=%s", spec.module, spec.capability
        )
        register(scoped)
