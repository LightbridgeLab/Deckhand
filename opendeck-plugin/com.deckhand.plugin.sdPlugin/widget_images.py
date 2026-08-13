"""Resolve OpenDeck plugin button images for Data Widget catalog entries."""

from __future__ import annotations

import base64
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_PLUGIN_DIR = Path(__file__).resolve().parent
_ASSETS = _PLUGIN_DIR / "assets"
_PROVIDERS = _ASSETS / "providers"

# Built-in provider marks shipped with the plugin.
_BUILTIN: dict[str, Path] = {
    "claude": _PROVIDERS / "claude.png",
    "cursor": _PROVIDERS / "cursor.png",
    "antigravity": _PROVIDERS / "antigravity.png",
    "blank": _ASSETS / "widget-blank.png",
}


def resolve_image_path(image: str | None) -> Path:
    """Map a catalog ``image`` value to a PNG on disk.

    Accepts built-in names (``claude``, ``cursor``, ``antigravity``, ``blank``),
    absolute/user paths, or paths relative to the plugin ``assets/`` folder.
    Falls back to the blank face when missing or unreadable.
    """
    blank = _BUILTIN["blank"]
    if not image or not image.strip():
        return blank
    name = image.strip()
    if name in _BUILTIN:
        path = _BUILTIN[name]
        return path if path.is_file() else blank

    path = Path(name).expanduser()
    if path.is_file():
        return path

    under_assets = _ASSETS / name
    if under_assets.is_file():
        return under_assets
    under_providers = _PROVIDERS / name
    if under_providers.is_file():
        return under_providers
    if not name.endswith(".png"):
        candidate = _PROVIDERS / f"{name}.png"
        if candidate.is_file():
            return candidate

    logger.warning("Catalog image %r not found; using blank", image)
    return blank


def image_data_uri(path: Path) -> str:
    """Return a ``data:image/png;base64,...`` URI for OpenDeck ``setImage``."""
    data = path.read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def catalog_image_for_key(
    state_key: str, catalog_entries: list[dict[str, str]]
) -> str | None:
    """Return the ``image`` field for ``state_key`` from catalog entries."""
    for entry in catalog_entries:
        if entry.get("key") == state_key:
            img = entry.get("image")
            return img if isinstance(img, str) and img.strip() else None
    # Prefix fallback when catalog row has no image yet
    if state_key.startswith("usage.claude_code."):
        return "claude"
    if state_key.startswith("usage.antigravity."):
        return "antigravity"
    if state_key.startswith("usage.cursor.") or state_key.startswith("cursor."):
        return "cursor"
    return None
