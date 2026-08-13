"""Tests for Data Widget catalog image resolution."""

from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).parent.parent / "com.deckhand.plugin.sdPlugin"
sys.path.insert(0, str(PLUGIN_DIR))

from widget_images import (
    catalog_image_for_key,
    image_data_uri,
    resolve_image_path,
)


def test_resolve_builtin_claude() -> None:
    path = resolve_image_path("claude")
    assert path.name == "claude.png"
    assert path.is_file()
    uri = image_data_uri(path)
    assert uri.startswith("data:image/png;base64,")


def test_resolve_missing_falls_back_to_blank() -> None:
    path = resolve_image_path("not-a-real-provider")
    assert path.name == "widget-blank.png"


def test_catalog_image_for_key_and_prefix() -> None:
    entries = [{"key": "usage.claude_code.session", "image": "claude"}]
    assert catalog_image_for_key("usage.claude_code.session", entries) == "claude"
    assert catalog_image_for_key("usage.claude_code.week", []) == "claude"
    assert catalog_image_for_key("cursor.summary", []) == "cursor"
    assert catalog_image_for_key("usage.cursor.models", []) == "cursor"
    assert catalog_image_for_key("usage.cursor.on_demand", []) == "cursor"
