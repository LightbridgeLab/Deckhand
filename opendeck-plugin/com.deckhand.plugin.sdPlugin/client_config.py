"""Resolve OpenDeck plugin connection settings (URL + API key).

Precedence (first hit wins per value):

1. ``DECKHAND_URL`` / ``DECKHAND_API_KEY`` environment variables — the
   explicit override path. OpenDeck on macOS launches plugins as GUI
   subprocesses that don't inherit a login shell, so these usually only
   come from an explicit ``launchctl setenv`` or from being injected by
   wrapper scripts.
2. ``[client]`` section of the shared ``config.toml``. Discovery order
   matches Deckhand Core's: ``DECKHAND_CONFIG_FILE`` env var →
   ``./config.toml`` (relative to the plugin's working dir) →
   ``~/.config/deckhand/config.toml``. The home-dir fallback is the
   intended path for OpenDeck-only users who don't have a Deckhand
   service checkout.
3. Legacy ``deckhand.env`` file next to ``plugin.py`` (the pre-#34
   install pattern). When present, the file is parsed for
   ``DECKHAND_URL`` / ``DECKHAND_API_KEY`` lines and a deprecation
   warning is logged. Slated for removal in the release after #34.
4. Defaults: ``DECKHAND_URL=http://localhost:8000``, ``api_key=None``.

Self-contained on purpose: this module is imported from the plugin
process running under OpenDeck's bundled venv, which does not have
``deckhand.*`` on its import path.
"""

from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_URL = "http://localhost:8000"


def resolve_connection(plugin_dir: Path) -> tuple[str, str | None]:
    """Return ``(url, api_key)`` resolved per the precedence above.

    ``plugin_dir`` is the directory containing ``plugin.py`` — used to
    locate the legacy ``deckhand.env`` file.
    """
    url = os.getenv("DECKHAND_URL")
    api_key = os.getenv("DECKHAND_API_KEY")

    if url is None or api_key is None:
        shared = _load_shared_client_section()
        if url is None:
            url = shared.get("url")
        if api_key is None:
            api_key = shared.get("api_key")

    if url is None or api_key is None:
        legacy = _load_legacy_env_file(plugin_dir / "deckhand.env")
        if legacy is not None:
            logger.warning(
                "Reading connection settings from deckhand.env — this fallback "
                "is deprecated and will be removed in the next release. Move "
                "the values to ~/.config/deckhand/config.toml under [client], "
                "or set DECKHAND_URL / DECKHAND_API_KEY in the environment."
            )
            if url is None:
                url = legacy.get("DECKHAND_URL")
            if api_key is None:
                api_key = legacy.get("DECKHAND_API_KEY")

    return (url or DEFAULT_URL, api_key)


def _shared_config_path() -> Path | None:
    """Discover the shared config.toml using the same order as Deckhand Core."""
    explicit = os.getenv("DECKHAND_CONFIG_FILE")
    if explicit and os.path.exists(explicit):
        return Path(explicit)
    if os.path.exists("config.toml"):
        return Path("config.toml")
    home = Path(os.path.expanduser("~/.config/deckhand/config.toml"))
    if home.exists():
        return home
    return None


def _load_shared_client_section() -> dict[str, str]:
    """Parse the ``[client]`` section out of the shared config file.

    Returns an empty dict if no config file is found, the file is
    unparseable, or it has no ``[client]`` section. Errors are logged
    but never raised — a malformed shared config must not prevent the
    plugin from at least trying the legacy path or the env vars.
    """
    path = _shared_config_path()
    if path is None:
        return {}
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logger.warning("Could not read shared config at %s: %s", path, exc)
        return {}
    client = data.get("client")
    if not isinstance(client, dict):
        return {}
    result: dict[str, str] = {}
    if isinstance(client.get("url"), str):
        result["url"] = client["url"]
    if isinstance(client.get("api_key"), str):
        result["api_key"] = client["api_key"]
    return result


def _load_legacy_env_file(path: Path) -> dict[str, str] | None:
    """Parse a deckhand.env-style file. Returns None if the file is absent."""
    if not path.exists():
        return None
    values: dict[str, str] = {}
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError as exc:
        logger.warning("Could not read legacy deckhand.env at %s: %s", path, exc)
        return None
    return values
