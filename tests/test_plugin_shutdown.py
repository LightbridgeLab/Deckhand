"""Tests for PluginRegistry.on_shutdown / run_shutdown_hooks."""

from __future__ import annotations

import asyncio

import pytest

from deckhand.plugins.capabilities import build_scoped_registry
from deckhand.plugins.claude_code_usage import _BACKGROUND_TASKS
from deckhand.plugins.claude_code_usage import register as ccu_register
from deckhand.plugins.registry import PluginRegistry


async def test_on_shutdown_runs_registered_hook(
    plugin_registry: PluginRegistry,
) -> None:
    calls: list[int] = []

    async def hook() -> None:
        calls.append(1)

    plugin_registry.on_shutdown(hook)
    await plugin_registry.run_shutdown_hooks()
    assert calls == [1]


async def test_run_shutdown_runs_all_hooks_even_if_one_fails(
    plugin_registry: PluginRegistry,
) -> None:
    ran: list[str] = []

    async def first() -> None:
        ran.append("first")

    async def boom() -> None:
        ran.append("boom")
        raise RuntimeError("plugin teardown error")

    async def last() -> None:
        ran.append("last")

    plugin_registry.on_shutdown(first)
    plugin_registry.on_shutdown(boom)
    plugin_registry.on_shutdown(last)

    # Must not raise even though one hook errors.
    await plugin_registry.run_shutdown_hooks()
    assert ran == ["first", "boom", "last"]


async def test_no_hooks_registered_is_noop(plugin_registry: PluginRegistry) -> None:
    await plugin_registry.run_shutdown_hooks()  # must not raise


@pytest.mark.parametrize("capability", ["read-only", "state-only"])
async def test_scoped_registry_forwards_shutdown_hook_to_base(
    plugin_registry: PluginRegistry, capability: str
) -> None:
    """Hooks registered on a scoped registry must run when the base
    registry's run_shutdown_hooks is invoked — otherwise poller plugins
    loaded under reduced capability leak their background tasks at shutdown."""
    scoped = build_scoped_registry(plugin_registry, capability)  # type: ignore[arg-type]
    ran: list[str] = []

    async def hook() -> None:
        ran.append("scoped")

    scoped.on_shutdown(hook)
    await plugin_registry.run_shutdown_hooks()
    assert ran == ["scoped"]


async def test_claude_code_usage_plugin_registers_shutdown_hook(
    plugin_registry: PluginRegistry,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Loading the usage plugin in a running loop schedules a poller AND
    registers a shutdown hook that cancels it cleanly."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DECKHAND_CONFIG_FILE", raising=False)

    _BACKGROUND_TASKS.clear()
    ccu_register(plugin_registry)

    assert len(_BACKGROUND_TASKS) == 1, "poller task should be scheduled"
    assert len(plugin_registry._shutdown_hooks) == 1, (
        "shutdown hook should be registered"
    )

    await plugin_registry.run_shutdown_hooks()
    # Give the cancelled task a tick to settle.
    await asyncio.sleep(0)
    assert len(_BACKGROUND_TASKS) == 0, "poller task should be drained after shutdown"
