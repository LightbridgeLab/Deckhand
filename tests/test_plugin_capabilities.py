"""Tests for plugin capability restrictions."""

from __future__ import annotations

import pytest

from deckhand.config.settings import _parse_plugin_entry
from deckhand.plugins.capabilities import (
    PluginSpec,
    build_scoped_registry,
)
from deckhand.plugins.loader import load_plugins
from deckhand.plugins.registry import PluginRegistry


async def test_full_capability_is_passthrough(
    plugin_registry: PluginRegistry,
) -> None:
    scoped = build_scoped_registry(plugin_registry, "full")
    assert scoped is plugin_registry
    assert scoped.orchestrator is not None


async def test_read_only_denies_all_writes(
    plugin_registry: PluginRegistry,
) -> None:
    scoped = build_scoped_registry(plugin_registry, "read-only")

    assert scoped.orchestrator is None
    # Read paths still work
    assert isinstance(scoped.actions.list_actions(), list)
    assert isinstance(scoped.signals.list_signals(), list)
    assert isinstance(scoped.state.list_state(), list)

    async def noop(payload: dict) -> None:
        return None

    with pytest.raises(PermissionError):
        scoped.actions.register("evil.action", noop)
    with pytest.raises(PermissionError):
        scoped.signals.register("evil.signal", noop)
    with pytest.raises(PermissionError):
        await scoped.state.set_state("k", {"v": 1})
    with pytest.raises(PermissionError):
        await scoped.events.emit(
            {
                "type": "x",
                "source": {"kind": "test", "id": "t"},
                "payload": {},
                "ts": 0.0,
                "version": "1.0",
            }
        )
    with pytest.raises(PermissionError):
        await scoped.actions.run("agent.start", {"agent_id": "mock-1"})


async def test_scoped_state_store_has_no_getattr_fallback(
    plugin_registry: PluginRegistry,
) -> None:
    """ScopedStateStore must expose only its explicit allow-list.

    If a future write-capable method is added to StateStore, it must not be
    silently reachable through the scoped wrapper — plugins should get an
    AttributeError until the method is explicitly proxied with the right
    capability check. This test pins that contract.
    """
    scoped = build_scoped_registry(plugin_registry, "read-only")

    # Simulate a hypothetical future write method on the underlying store.
    async def bulk_set(entries: dict[str, object]) -> None:  # pragma: no cover
        raise AssertionError("should not be reachable via scoped store")

    plugin_registry.state.bulk_set = bulk_set  # type: ignore[attr-defined]

    with pytest.raises(AttributeError):
        _ = scoped.state.bulk_set  # type: ignore[attr-defined]


async def test_state_only_allows_state_and_signals_but_not_actions(
    plugin_registry: PluginRegistry,
) -> None:
    scoped = build_scoped_registry(plugin_registry, "state-only")

    assert scoped.orchestrator is None

    async def noop(payload: dict) -> None:
        return None

    # Signal registration allowed
    scoped.signals.register("my.signal", noop)
    assert plugin_registry.signals.get_signal_metadata("my.signal") is not None

    # State writes allowed
    await scoped.state.set_state("k", {"v": 1})
    assert any(
        e.get("value", {}).get("v") == 1 for e in plugin_registry.state.list_state()
    )

    # Actions registration still denied
    with pytest.raises(PermissionError):
        scoped.actions.register("evil.action", noop)

    # Action invocation also denied — state-only must not reach orchestrator
    # commands via the action layer.
    with pytest.raises(PermissionError):
        await scoped.actions.run("agent.start", {"agent_id": "mock-1"})


async def test_load_plugins_with_spec(
    plugin_registry: PluginRegistry, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """state-only capability allows a plugin to register a signal."""
    plugin_dir = tmp_path
    (plugin_dir / "signal_plugin.py").write_text(
        "async def _h(payload): return None\n"
        "def register(registry):\n"
        "    registry.signals.register('test.signal', _h)\n"
    )
    monkeypatch.syspath_prepend(str(plugin_dir))
    load_plugins(
        [PluginSpec(module="signal_plugin", capability="state-only")],
        plugin_registry,
    )
    assert plugin_registry.signals.get_signal_metadata("test.signal") is not None


async def test_load_plugins_read_only_blocks_signal_register(
    plugin_registry: PluginRegistry, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plugin that tries to register under read-only must be rejected."""
    (tmp_path / "rwsignal_plugin.py").write_text(
        "async def _h(payload): return None\n"
        "def register(registry):\n"
        "    registry.signals.register('rw.signal', _h)\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(PermissionError):
        load_plugins(
            [PluginSpec(module="rwsignal_plugin", capability="read-only")],
            plugin_registry,
        )


def test_invalid_capability_rejected(plugin_registry: PluginRegistry) -> None:
    with pytest.raises(ValueError):
        build_scoped_registry(plugin_registry, "admin")  # type: ignore[arg-type]


def test_parse_plugin_entry_string() -> None:
    spec = _parse_plugin_entry("some.module")
    assert spec.module == "some.module"
    assert spec.capability == "full"


def test_parse_plugin_entry_colon_shorthand() -> None:
    spec = _parse_plugin_entry("some.module:read-only")
    assert spec.module == "some.module"
    assert spec.capability == "read-only"


def test_parse_plugin_entry_dict() -> None:
    spec = _parse_plugin_entry({"module": "x.y", "capability": "state-only"})
    assert spec == PluginSpec(module="x.y", capability="state-only")


def test_parse_plugin_entry_invalid_capability() -> None:
    with pytest.raises(ValueError):
        _parse_plugin_entry("m:wheee")
    with pytest.raises(ValueError):
        _parse_plugin_entry({"module": "m", "capability": "bogus"})
    with pytest.raises(ValueError):
        _parse_plugin_entry({"capability": "full"})
