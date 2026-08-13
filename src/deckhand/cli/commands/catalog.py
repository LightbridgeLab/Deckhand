"""Catalog CLI commands (state-key list for Data Widget PI)."""

from __future__ import annotations

from deckhand.catalog.state_keys import (
    discover_config_path,
    load_state_key_entries,
    sync_state_key_catalog,
)
from deckhand.cli.client import DeckhandClient, DeckhandError
from deckhand.cli.formatters import emit_json


def list_(config_path: str | None) -> None:
    """Show [catalog.state_keys] entries from config.toml."""
    path = discover_config_path(config_path)
    entries = load_state_key_entries(path)
    emit_json(
        {
            "config": str(path) if path else None,
            "entries": [e.as_dict() for e in entries],
        }
    )


def sync(
    client: DeckhandClient | None,
    config_path: str | None,
    *,
    include_live: bool,
) -> None:
    live_keys: list[str] = []
    live_error: str | None = None
    if include_live and client is not None:
        try:
            for entry in client.list_state():
                key = entry.get("key") if isinstance(entry, dict) else None
                if isinstance(key, str) and key:
                    live_keys.append(key)
        except DeckhandError as exc:
            live_error = str(exc)

    existed = discover_config_path(config_path) is not None
    path, entries = sync_state_key_catalog(
        config_path,
        live_keys=live_keys,
        create_if_missing=True,
    )
    payload: dict[str, object] = {
        "config": str(path),
        "entries": [e.as_dict() for e in entries],
        "merged_live_keys": live_keys,
    }
    if live_error:
        payload["live_warning"] = live_error
        payload["hint"] = (
            "Start Deckhand (e.g. make dev), then re-run catalog sync to merge "
            "live keys — or use --no-live to skip."
        )
    if not existed:
        payload["created"] = True
    emit_json(payload)
