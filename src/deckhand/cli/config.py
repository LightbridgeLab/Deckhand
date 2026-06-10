"""CLI configuration: resolve URL, API key, and event-log path.

Precedence (highest first):
1. CLI flags (``--url``, ``--api-key``)
2. Environment variables (``DECKHAND_URL``, ``DECKHAND_API_KEY``, ``DECKHAND_EVENT_LOG``)
3. ``config.toml`` ``[service]`` / ``[auth]`` / ``[event_log]``
4. Built-in defaults
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from deckhand.config.loader import load_config

DEFAULT_URL = "http://127.0.0.1:8000"
DEFAULT_EVENT_LOG = ".deckhand/events.log"


@dataclass
class CliConfig:
    url: str
    api_key: str | None
    event_log_path: Path


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

    if config_path and Path(config_path).exists():
        config = load_config(config_path)

        service = config.get("service", {})
        host = service.get("host", "127.0.0.1")
        port = service.get("port", 8000)
        if host or port:
            file_url = f"http://{host}:{port}"

        auth = config.get("auth", {})
        if isinstance(auth.get("api_keys"), list) and auth["api_keys"]:
            first = auth["api_keys"][0]
            if isinstance(first, dict) and "key" in first:
                file_key = first["key"]

        el = config.get("event_log", {})
        if isinstance(el.get("path"), str):
            file_event_log = el["path"]

    url = url_flag or os.getenv("DECKHAND_URL") or file_url or DEFAULT_URL
    api_key = api_key_flag or os.getenv("DECKHAND_API_KEY") or file_key
    event_log_path = Path(
        os.getenv("DECKHAND_EVENT_LOG") or file_event_log or DEFAULT_EVENT_LOG
    )

    return CliConfig(url=url, api_key=api_key, event_log_path=event_log_path)
