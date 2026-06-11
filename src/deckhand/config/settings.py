"""Configuration placeholders for the local service."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from deckhand.config.loader import load_config, resolve_project_path
from deckhand.plugins.capabilities import VALID_CAPABILITIES, PluginSpec
from deckhand.security import ApiKeyEntry, generate_api_key

logger = logging.getLogger(__name__)


def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"Invalid boolean: {value!r}")


def _parse_plugin_entry(entry: Any) -> PluginSpec:
    """Parse a single plugin config entry into a PluginSpec.

    Accepts either a bare module path string (defaults to ``full``
    capability) or a dict with ``module`` and optional ``capability``.
    Supports ``"module:capability"`` shorthand for env-var usage.
    """
    if isinstance(entry, PluginSpec):
        return entry
    if isinstance(entry, str):
        if ":" in entry:
            module, _, cap = entry.partition(":")
            capability = cap or "full"
        else:
            module, capability = entry, "full"
        if capability not in VALID_CAPABILITIES:
            raise ValueError(f"Invalid plugin capability '{capability}' for {module}")
        return PluginSpec(module=module, capability=capability)  # type: ignore[arg-type]
    if isinstance(entry, dict):
        module = entry.get("module")
        if not module or not isinstance(module, str):
            raise ValueError("Plugin entry dict requires a 'module' key")
        capability = entry.get("capability", "full")
        if capability not in VALID_CAPABILITIES:
            raise ValueError(f"Invalid plugin capability '{capability}' for {module}")
        return PluginSpec(module=module, capability=capability)
    raise ValueError(f"Unsupported plugin entry: {entry!r}")


class Settings:
    """Application settings with environment variable and config file support."""

    def __init__(self) -> None:
        # Default values
        self.service_name = "deckhand"
        self.host = "127.0.0.1"
        self.port = 8000
        self.plugin_specs: list[PluginSpec] = [
            PluginSpec(module="deckhand.plugins.builtin", capability="full")
        ]
        self.config_file_path: str | None = None
        self.state_file_path: str | None = None
        self.rate_limit_rpm: int = 60
        self.log_level: str = "INFO"
        self.log_format: str = "plain"  # "plain" or "json"
        self.event_log_enabled: bool = False
        self._event_log_path_raw: str = ".deckhand/events.log"

        # Auth: list of {key, scope} dicts
        self._raw_api_keys: list[dict[str, str]] = []

        # Load from config file: explicit env var, or auto-discover ./config.toml
        config_file = os.getenv("DECKHAND_CONFIG_FILE")
        if not config_file and os.path.exists("config.toml"):
            config_file = "config.toml"
        if config_file:
            self.config_file_path = config_file
            self._load_from_config_file(config_file)

        # Environment variables override config file
        self._load_from_env()

        # Auto-generate a write key if none configured
        self._generated_key: str | None = None
        if not self._raw_api_keys:
            key = generate_api_key()
            self._raw_api_keys = [{"key": key, "scope": "write"}]
            self._generated_key = key

        # Build typed key list
        self.api_keys: list[ApiKeyEntry] = [
            ApiKeyEntry(key=k["key"], scope=k.get("scope", "write"))
            for k in self._raw_api_keys
        ]

        # Resolve project-relative paths once config_file_path is known.
        self.event_log_path: Path = resolve_project_path(
            self._event_log_path_raw, self.config_file_path
        )

    @property
    def plugin_modules(self) -> list[str]:
        """Backwards-compatible view: just the module paths."""
        return [spec.module for spec in self.plugin_specs]

    # ------------------------------------------------------------------
    # Config file loading
    # ------------------------------------------------------------------

    def _load_from_config_file(self, file_path: str) -> None:
        """Load settings from TOML config file."""
        config = load_config(file_path)

        # Service settings
        if "service" in config:
            service_config = config["service"]
            self.service_name = service_config.get("name", self.service_name)
            self.host = service_config.get("host", self.host)
            self.port = service_config.get("port", self.port)

        # Plugin settings
        if "plugins" in config:
            plugin_config = config["plugins"]
            modules = plugin_config.get("modules")
            if modules:
                self.plugin_specs = [_parse_plugin_entry(m) for m in modules]

        # Path settings
        if "paths" in config:
            paths_config = config["paths"]
            if state_file := paths_config.get("state_file"):
                self.state_file_path = state_file

        # Auth settings
        if "auth" in config:
            auth_config = config["auth"]
            self._load_auth(auth_config)

        # Rate limiting
        if "rate_limit" in config:
            rl_config = config["rate_limit"]
            self.rate_limit_rpm = rl_config.get("rpm", self.rate_limit_rpm)

        # Logging
        if "logging" in config:
            log_config = config["logging"]
            self.log_level = log_config.get("level", self.log_level)
            self.log_format = log_config.get("format", self.log_format)

        if "event_log" in config:
            el_config = config["event_log"]
            if "enabled" in el_config:
                self.event_log_enabled = _parse_bool(el_config["enabled"])
            if "path" in el_config:
                self._event_log_path_raw = str(el_config["path"])

    def _load_auth(self, auth_config: dict[str, Any]) -> None:
        """Parse the [auth] section."""
        if "api_keys" in auth_config:
            self._raw_api_keys = auth_config["api_keys"]

    # ------------------------------------------------------------------
    # Environment variable overrides
    # ------------------------------------------------------------------

    def _load_from_env(self) -> None:
        """Load settings from environment variables (highest priority)."""
        if host := os.getenv("DECKHAND_HOST"):
            self.host = host

        if port_str := os.getenv("DECKHAND_PORT"):
            try:
                self.port = int(port_str)
            except ValueError:
                pass

        if config_file := os.getenv("DECKHAND_CONFIG_FILE"):
            self.config_file_path = config_file

        if plugins_str := os.getenv("DECKHAND_PLUGINS"):
            self.plugin_specs = [
                _parse_plugin_entry(p.strip())
                for p in plugins_str.split(",")
                if p.strip()
            ]

        if state_file := os.getenv("DECKHAND_STATE_FILE"):
            self.state_file_path = state_file

        # DECKHAND_API_KEY env var → write-scoped key (overrides config file)
        if api_key := os.getenv("DECKHAND_API_KEY"):
            self._raw_api_keys = [{"key": api_key, "scope": "write"}]

        if rpm_str := os.getenv("DECKHAND_RATE_LIMIT_RPM"):
            try:
                self.rate_limit_rpm = int(rpm_str)
            except ValueError:
                pass

        if log_level := os.getenv("DECKHAND_LOG_LEVEL"):
            self.log_level = log_level

        if log_format := os.getenv("DECKHAND_LOG_FORMAT"):
            self.log_format = log_format

        if event_log_enabled := os.getenv("DECKHAND_EVENT_LOG_ENABLED"):
            self.event_log_enabled = _parse_bool(event_log_enabled)

        if event_log_path := os.getenv("DECKHAND_EVENT_LOG"):
            self._event_log_path_raw = event_log_path
