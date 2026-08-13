"""Editable state-key catalog in ``config.toml``.

The Data Widget Property Inspector lists keys from
``[catalog.state_keys].entries`` rather than live ``GET /state``. Humans and
``deckhand catalog sync`` both write the same list.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deckhand.config.loader import load_config

# Display formats accepted by the Data Widget Property Inspector.
VALID_FORMATS = frozenset(
    {"raw", "currency", "percentage", "boolean", "number", "summary"}
)

# (key, dropdown_label, image, format, button_title)
# image / format / button_title may be empty.
_CORE_SEEDS: tuple[tuple[str, str, str, str, str], ...] = (
    ("agents.pending_input_count", "Pending input count", "", "number", ""),
    ("agents.pending_input", "Pending input agents", "", "summary", ""),
    ("cursor.summary", "Cursor: Summary", "cursor", "summary", ""),
)

_PLUGIN_SEEDS: dict[str, tuple[tuple[str, str, str, str, str], ...]] = {
    "deckhand.plugins.claude_code_usage": (
        (
            "usage.claude_code.session",
            "Claude: Session (5h)",
            "claude",
            "percentage",
            "Session",
        ),
        ("usage.claude_code.week", "Claude: Week", "claude", "percentage", "Week"),
        (
            "usage.claude_code.week_fable",
            "Claude: Week (Fable)",
            "claude",
            "percentage",
            "Fable",
        ),
        (
            "usage.claude_code.credits",
            "Claude: Credits remaining",
            "claude",
            "percentage",
            "Credits",
        ),
    ),
    "deckhand.plugins.antigravity_usage": (
        (
            "usage.antigravity.session",
            "Antigravity: Session (5h)",
            "antigravity",
            "percentage",
            "Session",
        ),
        (
            "usage.antigravity.week",
            "Antigravity: Week",
            "antigravity",
            "percentage",
            "Week",
        ),
    ),
    "deckhand.plugins.cursor_usage": (
        ("usage.cursor.models", "Cursor: Models", "cursor", "percentage", "Models"),
        ("usage.cursor.other", "Cursor: Other Models", "cursor", "percentage", "Other"),
        (
            "usage.cursor.on_demand",
            "Cursor: On-demand",
            "cursor",
            "percentage",
            "Demand",
        ),
    ),
}

# Built-in names resolved by the OpenDeck plugin under assets/providers/.
BUILTIN_IMAGES = frozenset({"claude", "cursor", "antigravity", "blank"})


@dataclass(frozen=True)
class StateKeyEntry:
    """One catalog row for the Data Widget Property Inspector.

    ``dropdown_label`` is the State Key menu name. ``button_title`` is the
    first line drawn on the key (overrides live ``short_label`` when set).
    """

    key: str
    dropdown_label: str | None = None
    image: str | None = None
    format: str | None = None
    button_title: str | None = None

    def display_label(self) -> str:
        return self.dropdown_label or self.key

    def as_dict(self) -> dict[str, str]:
        out: dict[str, str] = {"key": self.key}
        if self.dropdown_label:
            out["dropdown_label"] = self.dropdown_label
        if self.image:
            out["image"] = self.image
        if self.format:
            out["format"] = self.format
        if self.button_title:
            out["button_title"] = self.button_title
        return out


def discover_config_path(explicit: str | Path | None = None) -> Path | None:
    """Resolve config.toml path (same order as Settings / clients).

    Returns ``None`` when nothing exists yet. Callers that need to create a
    file should fall back to ``default_writable_config_path()``.
    """
    if explicit is not None:
        path = Path(explicit).expanduser()
        return path if path.exists() else None

    env = os.getenv("DECKHAND_CONFIG_FILE")
    if env and Path(env).expanduser().exists():
        return Path(env).expanduser()
    if Path("config.toml").exists():
        return Path("config.toml")
    home = Path(os.path.expanduser("~/.config/deckhand/config.toml"))
    if home.exists():
        return home
    return None


def default_writable_config_path(explicit: str | Path | None = None) -> Path:
    """Path to write when syncing and no config file exists yet."""
    if explicit is not None:
        return Path(explicit).expanduser()
    env = os.getenv("DECKHAND_CONFIG_FILE")
    if env:
        return Path(env).expanduser()
    if Path("config.toml").exists() or Path("config.example.toml").exists():
        return Path("config.toml")
    return Path(os.path.expanduser("~/.config/deckhand/config.toml"))


def _normalize_format(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    fmt = raw.strip().lower()
    return fmt if fmt in VALID_FORMATS else None


def _optional_str(raw: Any) -> str | None:
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def parse_state_key_entries(raw: Any) -> list[StateKeyEntry]:
    """Normalize ``[catalog.state_keys].entries`` (or a bare list) to entries."""
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = raw.get("entries", [])
    if not isinstance(raw, list):
        return []

    entries: list[StateKeyEntry] = []
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, str):
            key = item.strip()
            dropdown_label = None
            image = None
            fmt = None
            button_title = None
        elif isinstance(item, dict):
            key_val = item.get("key")
            if not isinstance(key_val, str) or not key_val.strip():
                continue
            key = key_val.strip()
            dropdown_label = _optional_str(item.get("dropdown_label"))
            image = _optional_str(item.get("image"))
            fmt = _normalize_format(item.get("format"))
            button_title = _optional_str(item.get("button_title"))
        else:
            continue
        if key in seen:
            continue
        seen.add(key)
        entries.append(
            StateKeyEntry(
                key=key,
                dropdown_label=dropdown_label,
                image=image,
                format=fmt,
                button_title=button_title,
            )
        )
    return entries


def load_state_key_entries(config_path: str | Path | None) -> list[StateKeyEntry]:
    """Load catalog entries from a config file (empty if missing/absent)."""
    if config_path is None:
        return []
    path = Path(config_path)
    if not path.exists():
        return []
    config = load_config(path)
    catalog = config.get("catalog")
    if not isinstance(catalog, dict):
        return []
    return parse_state_key_entries(catalog.get("state_keys"))


def seed_entries_for_plugins(plugin_modules: Iterable[str]) -> list[StateKeyEntry]:
    """Curated first-party keys for enabled plugins (+ always-on core keys)."""
    modules = set(plugin_modules)
    rows: list[tuple[str, str, str, str, str]] = list(_CORE_SEEDS)
    for module, seeds in _PLUGIN_SEEDS.items():
        if module in modules:
            rows.extend(seeds)
    return [
        StateKeyEntry(
            key=k,
            dropdown_label=dropdown or None,
            image=image or None,
            format=fmt or None,
            button_title=title or None,
        )
        for k, dropdown, image, fmt, title in rows
    ]


def merge_state_key_entries(
    existing: Sequence[StateKeyEntry],
    *sources: Sequence[StateKeyEntry],
) -> list[StateKeyEntry]:
    """Merge catalogs: keep first-seen order; fill missing presentation fields.

    Existing non-empty dropdown_label/image/format/button_title are never
    overwritten.
    """
    by_key: dict[str, StateKeyEntry] = {}
    order: list[str] = []
    for source in (existing, *sources):
        for entry in source:
            cur = by_key.get(entry.key)
            if cur is None:
                by_key[entry.key] = entry
                order.append(entry.key)
                continue
            by_key[entry.key] = StateKeyEntry(
                key=cur.key,
                dropdown_label=cur.dropdown_label or entry.dropdown_label,
                image=cur.image or entry.image,
                format=cur.format or entry.format,
                button_title=cur.button_title or entry.button_title,
            )
    return [by_key[k] for k in order]


def plugin_modules_from_config(config_path: str | Path | None) -> list[str]:
    """Read ``[plugins].modules`` module paths from config."""
    if config_path is None or not Path(config_path).exists():
        return []
    config = load_config(config_path)
    plugins = config.get("plugins")
    if not isinstance(plugins, dict):
        return []
    modules = plugins.get("modules") or []
    out: list[str] = []
    for entry in modules:
        if isinstance(entry, str):
            module = entry.split(":", 1)[0].strip()
            if module:
                out.append(module)
        elif isinstance(entry, dict):
            module = entry.get("module")
            if isinstance(module, str) and module.strip():
                out.append(module.strip())
    return out


def live_keys_to_entries(keys: Iterable[str]) -> list[StateKeyEntry]:
    """Turn live store key names into unlabeled catalog rows."""
    entries: list[StateKeyEntry] = []
    seen: set[str] = set()
    for key in keys:
        if not key or key in seen:
            continue
        seen.add(key)
        # Guess provider image from key prefix when merging live keys.
        image: str | None = None
        if key.startswith("usage.claude_code."):
            image = "claude"
        elif key.startswith("usage.antigravity."):
            image = "antigravity"
        elif key.startswith(("cursor.", "usage.cursor.")):
            image = "cursor"
        entries.append(StateKeyEntry(key=key, image=image))
    return entries


def sort_catalog_dicts_by_label(
    entries: Sequence[dict[str, str]],
) -> list[dict[str, str]]:
    """Return catalog dict rows sorted by dropdown label (case-insensitive)."""
    return sorted(
        entries,
        key=lambda e: (e.get("dropdown_label") or e.get("key") or "").casefold(),
    )


_CATALOG_SECTION_RE = re.compile(
    r"(?m)^\[catalog\.state_keys\][^\n]*\n(?:(?!^\[[^\]]+\]).*\n)*"
)


def _escape_toml_str(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _format_catalog_section(entries: Sequence[StateKeyEntry]) -> str:
    lines = [
        "[catalog.state_keys]",
        "# Keys listed here appear in the Data Widget Property Inspector.",
        "# Dropdown is sorted alphabetically by dropdown_label (file order kept).",
        "# dropdown_label: name in the State Key menu (not drawn on the key).",
        "# button_title: first line on the key; leave unset to use live short_label.",
        "# image: built-in provider mark (claude | cursor | antigravity | blank)",
        "#       or a filesystem path to a PNG.",
        "# format: suggested Display Format (raw | currency | percentage |",
        "#         boolean | number | summary); applied when the key is selected.",
        "# Edit by hand or run: deckhand catalog sync",
        "entries = [",
    ]
    for entry in entries:
        parts = [f'key = "{entry.key}"']
        if entry.dropdown_label:
            parts.append(f'dropdown_label = "{_escape_toml_str(entry.dropdown_label)}"')
        if entry.image:
            parts.append(f'image = "{_escape_toml_str(entry.image)}"')
        if entry.format:
            parts.append(f'format = "{entry.format}"')
        if entry.button_title:
            parts.append(f'button_title = "{_escape_toml_str(entry.button_title)}"')
        lines.append(f"  {{ {', '.join(parts)} }},")
    lines.append("]")
    lines.append("")
    return "\n".join(lines)


def write_state_key_catalog(
    config_path: str | Path,
    entries: Sequence[StateKeyEntry],
) -> Path:
    """Write ``[catalog.state_keys]`` into config.toml, preserving other sections."""
    path = Path(config_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    section = _format_catalog_section(entries)

    if path.exists():
        text = path.read_text(encoding="utf-8")
        if _CATALOG_SECTION_RE.search(text):
            new_text = _CATALOG_SECTION_RE.sub(section, text, count=1)
        else:
            new_text = text.rstrip() + "\n\n" + section
    else:
        new_text = (
            "# Deckhand configuration\n"
            "# Generated by `deckhand catalog sync`.\n\n" + section
        )

    path.write_text(new_text, encoding="utf-8")
    return path


def sync_state_key_catalog(
    config_path: str | Path | None = None,
    *,
    live_keys: Sequence[str] | None = None,
    create_if_missing: bool = True,
) -> tuple[Path, list[StateKeyEntry]]:
    """Seed + merge + write the state-key catalog.

    Returns ``(path_written, merged_entries)``.
    """
    existing_path = discover_config_path(config_path)
    write_path = (
        existing_path
        if existing_path is not None
        else (default_writable_config_path(config_path) if create_if_missing else None)
    )
    if write_path is None:
        raise FileNotFoundError("No config.toml found; pass --config or create one.")

    existing = load_state_key_entries(existing_path or write_path)
    seeds = seed_entries_for_plugins(
        plugin_modules_from_config(existing_path or write_path)
    )
    live = live_keys_to_entries(live_keys or [])
    merged = merge_state_key_entries(existing, seeds, live)
    written = write_state_key_catalog(write_path, merged)
    return written, merged
