"""CLI configuration: resolve URL, API key, and event-log path.

Precedence (highest first):
1. CLI flags (``--url``, ``--api-key``)
2. Environment variables (``DECKHAND_URL``, ``DECKHAND_API_KEY``, ``DECKHAND_EVENT_LOG``)
3. Live runtime file (``~/.config/deckhand/runtime.toml``) — URL only,
   and only while Core's pid is still running
4. ``config.toml`` ``[client]`` section (preferred — same field any other
   Deckhand client reads from)
5. ``config.toml`` ``[service]`` / ``[auth]`` legacy extraction (URL from
   ``[service]`` host+port, key from ``[auth].api_keys[0]``)
6. Built-in defaults

Config file discovery matches Deckhand Core: ``DECKHAND_CONFIG_FILE`` env
var → ``./config.toml`` → ``~/.config/deckhand/config.toml``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from deckhand.config.loader import load_config, resolve_project_path
from deckhand.config.runtime import read_live_url
from deckhand.config.settings import DEFAULT_PORT

DEFAULT_URL = f"http://127.0.0.1:{DEFAULT_PORT}"
DEFAULT_EVENT_LOG = ".deckhand/events.log"


@dataclass
class CliConfig:
    url: str
    api_key: str | None
    event_log_path: Path
    config_file_path: str | None = None


def load(
    url_flag: str | None = None,
    api_key_flag: str | None = None,
    config_file: str | None = None,
) -> CliConfig:
    file_url: str | None = None
    file_key: str | None = None
    file_event_log: str | None = None

    config_path = config_file or os.getenv("DECKHAND_CONFIG_FILE")
    if not config_path and Path("config.toml").exists():
        config_path = "config.toml"
    if not config_path:
        home_config = Path(os.path.expanduser("~/.config/deckhand/config.toml"))
        if home_config.exists():
            config_path = str(home_config)

    resolved_config_path: str | None = None
    if config_path and Path(config_path).exists():
        resolved_config_path = config_path
        config = load_config(config_path)

        # Preferred: explicit [client] section. Same shape any other
        # Deckhand client reads from.
        client_section = config.get("client", {})
        if isinstance(client_section, dict):
            if isinstance(client_section.get("url"), str):
                file_url = client_section["url"]
            if isinstance(client_section.get("api_key"), str):
                file_key = client_section["api_key"]

        # Fallback: infer URL from the service's listen address and the
        # key from the first entry of [auth].api_keys. Kept so existing
        # configs that don't have a [client] section still work.
        if file_url is None:
            service = config.get("service", {})
            host = service.get("host", "127.0.0.1")
            port = service.get("port", DEFAULT_PORT)
            if host or port:
                file_url = f"http://{host}:{port}"

        if file_key is None:
            auth = config.get("auth", {})
            if isinstance(auth.get("api_keys"), list) and auth["api_keys"]:
                first = auth["api_keys"][0]
                if isinstance(first, dict) and "key" in first:
                    file_key = first["key"]

        el = config.get("event_log", {})
        if isinstance(el.get("path"), str):
            file_event_log = el["path"]

    url = (
        url_flag
        or os.getenv("DECKHAND_URL")
        or read_live_url()
        or file_url
        or DEFAULT_URL
    )
    api_key = api_key_flag or os.getenv("DECKHAND_API_KEY") or file_key
    event_log_raw = (
        os.getenv("DECKHAND_EVENT_LOG") or file_event_log or DEFAULT_EVENT_LOG
    )
    event_log_path = resolve_project_path(event_log_raw, resolved_config_path)

    return CliConfig(
        url=url,
        api_key=api_key,
        event_log_path=event_log_path,
        config_file_path=resolved_config_path or config_path,
    )
