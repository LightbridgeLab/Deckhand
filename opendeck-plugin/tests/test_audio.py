"""Tests for host-side system-sound playback helpers."""

from __future__ import annotations

import platform
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).parent.parent / "com.deckhand.plugin.sdPlugin"
sys.path.insert(0, str(PLUGIN_DIR))

from audio import resolve_sound_path


def test_resolve_sound_path_rejects_empty_and_traversal() -> None:
    assert resolve_sound_path("") is None
    assert resolve_sound_path("../etc/passwd") is None
    assert resolve_sound_path("Glass/../../x") is None
    assert resolve_sound_path("..") is None


def test_resolve_sound_path_glass_on_macos() -> None:
    path = resolve_sound_path("Glass")
    if platform.system() == "Darwin":
        assert path is not None
        assert path.name == "Glass.aiff"
    else:
        assert path is None
