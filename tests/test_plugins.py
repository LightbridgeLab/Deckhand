"""Tests for plugin loading and registration."""

from __future__ import annotations

import importlib
import tempfile
from pathlib import Path

import pytest

from deckhand.plugins.loader import load_plugins
from deckhand.plugins.registry import PluginRegistry


async def test_plugin_loading_missing_register() -> None:
    """Test plugin loading with missing register() function raises ValueError."""
    # Create a temporary module without register function
    with tempfile.TemporaryDirectory() as tmpdir:
        plugin_file = Path(tmpdir) / "test_plugin.py"
        plugin_file.write_text("def other_function(): pass\n")

        # Add to path and import
        import sys

        sys.path.insert(0, tmpdir)

        try:
            importlib.import_module("test_plugin")
            registry = PluginRegistry(
                actions=None,  # type: ignore
                signals=None,  # type: ignore
                state=None,  # type: ignore
                events=None,  # type: ignore
                orchestrator=None,  # type: ignore
            )

            with pytest.raises(ValueError, match="has no register"):
                load_plugins(["test_plugin"], registry)
        finally:
            sys.path.remove(tmpdir)


async def test_plugin_loading_valid(plugin_registry: PluginRegistry) -> None:
    """Test plugin loading with a valid in-test module that registers a signal."""
    with tempfile.TemporaryDirectory() as tmpdir:
        plugin_file = Path(tmpdir) / "ok_plugin.py"
        plugin_file.write_text(
            "async def _handler(payload):\n    return None\n\n"
            "def register(registry):\n"
            "    registry.signals.register('ok.signal', _handler)\n"
        )
        import sys

        sys.path.insert(0, tmpdir)
        try:
            load_plugins(["ok_plugin"], plugin_registry)
            assert any(
                s.name == "ok.signal" for s in plugin_registry.signals.list_signals()
            )
        finally:
            sys.path.remove(tmpdir)
