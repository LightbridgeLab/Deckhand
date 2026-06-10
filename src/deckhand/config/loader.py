"""Configuration file loading utilities."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any


def resolve_project_path(raw: str | Path, config_file: str | Path | None) -> Path:
    """Resolve a possibly-relative project path.

    Absolute paths are returned as-is. Relative paths anchor to the directory
    containing ``config_file`` when one was loaded, otherwise to the current
    working directory. The server and CLI use this so the same relative path
    in ``config.toml`` resolves to the same location regardless of where
    each process is started from.
    """
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    if config_file:
        return (Path(config_file).expanduser().resolve().parent / path).resolve()
    return (Path.cwd() / path).resolve()


def load_config(file_path: str | Path | None) -> dict[str, Any]:
    """
    Load configuration from TOML file.

    Args:
        file_path: Path to TOML config file, or None to return empty dict

    Returns:
        Configuration dictionary, or empty dict if file not found
    """
    if file_path is None:
        return {}

    path = Path(file_path)
    if not path.exists():
        return {}

    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception as e:
        raise ValueError(f"Failed to load config file {file_path}: {e}") from e
