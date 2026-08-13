"""Resolve OpenDeck plugin connection settings (URL + API key).

Precedence (first hit wins per value):

1. ``DECKHAND_URL`` / ``DECKHAND_API_KEY`` environment variables — the
   explicit override path. OpenDeck on macOS launches plugins as GUI
   subprocesses that don't inherit a login shell, so these usually only
   come from an explicit ``launchctl setenv`` or from being injected by
   wrapper scripts.
2. Live runtime file (``~/.config/deckhand/runtime.toml``, or
   ``DECKHAND_RUNTIME_FILE``). Core writes the bound URL + pid on
   startup. Used for the URL only, and only while that pid is alive —
   so a port change in the checkout ``config.toml`` reaches OpenDeck
   without editing ``deckhand.env``.
3. ``[client]`` section of the shared ``config.toml``. Discovery order
   matches Deckhand Core's: ``DECKHAND_CONFIG_FILE`` env var →
   ``./config.toml`` (relative to the plugin's working dir) →
   ``~/.config/deckhand/config.toml``. The home-dir fallback is the
   intended path for OpenDeck-only users who don't have a Deckhand
   service checkout. ``[service]`` / ``[auth]`` fill omitted fields.
4. Legacy ``deckhand.env`` file next to ``plugin.py`` (the pre-#34
   install pattern). When present, the file is parsed for
   ``DECKHAND_URL`` / ``DECKHAND_API_KEY`` lines and a deprecation
   warning is logged. Slated for removal in the release after #34.
5. Defaults: ``DECKHAND_URL=http://localhost:18765``, ``api_key=None``.

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

DEFAULT_PORT = 18765
DEFAULT_URL = f"http://localhost:{DEFAULT_PORT}"


def resolve_connection(plugin_dir: Path) -> tuple[str, str | None]:
    """Return ``(url, api_key)`` resolved per the precedence above.

    ``plugin_dir`` is the directory containing ``plugin.py`` — used to
    locate the legacy ``deckhand.env`` file.
    """
    url = os.getenv("DECKHAND_URL")
    api_key = os.getenv("DECKHAND_API_KEY")

    if url is None:
        url = _load_live_runtime_url()

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


def _runtime_file_path() -> Path:
    explicit = os.getenv("DECKHAND_RUNTIME_FILE")
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / ".config" / "deckhand" / "runtime.toml"


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _load_live_runtime_url() -> str | None:
    """URL from Core's runtime.toml if the writer pid is still running."""
    path = _runtime_file_path()
    if not path.is_file():
        return None
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logger.warning("Could not read runtime file %s: %s", path, exc)
        return None
    url = data.get("url")
    pid = data.get("pid")
    if not isinstance(url, str) or not url.strip():
        return None
    if not isinstance(pid, int) or not _pid_is_alive(pid):
        return None
    return url.strip()


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


_DEFAULT_USAGE_RESET_FLASH_SECONDS = 5


def _load_shared_client_section() -> dict[str, str]:
    """Parse connection settings out of the shared config file.

    Prefers ``[client]`` url/api_key. If those are omitted, infers URL
    from ``[service]`` host+port and the key from the first
    ``[auth].api_keys`` entry (same fallback as the CLI).

    Returns an empty dict if no config file is found or the file is
    unparseable. Errors are logged but never raised.
    """
    path = _shared_config_path()
    if path is None:
        return {}
    data = _load_shared_config(path)
    if data is None:
        return {}
    client = data.get("client")
    result: dict[str, str] = {}
    if isinstance(client, dict):
        if isinstance(client.get("url"), str):
            result["url"] = client["url"]
        if isinstance(client.get("api_key"), str):
            result["api_key"] = client["api_key"]
    if "url" not in result:
        inferred = _url_from_service_section(data)
        if inferred:
            result["url"] = inferred
    if "api_key" not in result:
        inferred_key = _api_key_from_auth_section(data)
        if inferred_key:
            result["api_key"] = inferred_key
    return result


def _url_from_service_section(data: dict) -> str | None:
    service = data.get("service")
    if not isinstance(service, dict):
        return None
    host = service.get("host", "127.0.0.1")
    port = service.get("port", DEFAULT_PORT)
    if not host and port is None:
        return None
    return f"http://{host or '127.0.0.1'}:{port}"


def _api_key_from_auth_section(data: dict) -> str | None:
    auth = data.get("auth")
    if not isinstance(auth, dict):
        return None
    keys = auth.get("api_keys")
    if not isinstance(keys, list) or not keys:
        return None
    first = keys[0]
    if isinstance(first, dict) and isinstance(first.get("key"), str):
        return first["key"]
    return None


def load_usage_reset_flash_seconds() -> int:
    """Seconds to flash time-until-reset on usage widget press.

    Reads ``[client].usage_reset_flash_seconds``. Default 5. ``0`` disables.
    Values below 0 are treated as 0; positive values are floored at 1.
    """
    path = _shared_config_path()
    if path is None:
        return _DEFAULT_USAGE_RESET_FLASH_SECONDS
    data = _load_shared_config(path)
    if data is None:
        return _DEFAULT_USAGE_RESET_FLASH_SECONDS
    client = data.get("client")
    if not isinstance(client, dict) or "usage_reset_flash_seconds" not in client:
        return _DEFAULT_USAGE_RESET_FLASH_SECONDS
    raw = client.get("usage_reset_flash_seconds")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid [client].usage_reset_flash_seconds=%r; using default %s",
            raw,
            _DEFAULT_USAGE_RESET_FLASH_SECONDS,
        )
        return _DEFAULT_USAGE_RESET_FLASH_SECONDS
    if value <= 0:
        return 0
    return max(1, value)


def load_state_key_catalog() -> tuple[list[dict[str, str]], str | None]:
    """Return ``([entries], config_path_or_None)`` for the Data Widget PI.

    Each entry is ``{"key": ..., "dropdown_label": ...}`` plus optional
    ``image``, ``format``, and ``button_title``. ``dropdown_label`` falls
    back to ``key`` when omitted. Empty list when the section is missing
    or unreadable.
    """
    path = _shared_config_path()
    if path is None:
        return [], None
    data = _load_shared_config(path)
    if data is None:
        return [], str(path)
    catalog = data.get("catalog")
    if not isinstance(catalog, dict):
        return [], str(path)
    state_keys = catalog.get("state_keys")
    raw_entries: object
    if isinstance(state_keys, dict):
        raw_entries = state_keys.get("entries", [])
    else:
        raw_entries = state_keys
    if not isinstance(raw_entries, list):
        return [], str(path)

    _valid_formats = frozenset(
        {"raw", "currency", "percentage", "boolean", "number", "summary"}
    )
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_entries:
        image = ""
        fmt = ""
        button_title = ""
        if isinstance(item, str):
            key = item.strip()
            dropdown_label = key
        elif isinstance(item, dict):
            key_val = item.get("key")
            if not isinstance(key_val, str) or not key_val.strip():
                continue
            key = key_val.strip()
            dropdown_val = item.get("dropdown_label")
            if isinstance(dropdown_val, str) and dropdown_val.strip():
                dropdown_label = dropdown_val.strip()
            else:
                dropdown_label = key
            image_val = item.get("image")
            image = (
                image_val.strip()
                if isinstance(image_val, str) and image_val.strip()
                else ""
            )
            format_val = item.get("format")
            if (
                isinstance(format_val, str)
                and format_val.strip().lower() in _valid_formats
            ):
                fmt = format_val.strip().lower()
            title_val = item.get("button_title")
            button_title = (
                title_val.strip()
                if isinstance(title_val, str) and title_val.strip()
                else ""
            )
        else:
            continue
        if key in seen:
            continue
        seen.add(key)
        row = {"key": key, "dropdown_label": dropdown_label}
        if image:
            row["image"] = image
        if fmt:
            row["format"] = fmt
        if button_title:
            row["button_title"] = button_title
        entries.append(row)
    return entries, str(path)


def _load_shared_config(path: Path) -> dict | None:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logger.warning("Could not read shared config at %s: %s", path, exc)
        return None


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
