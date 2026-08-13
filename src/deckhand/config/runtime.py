"""Well-known runtime file: the URL Core actually bound.

Written on startup to ``~/.config/deckhand/runtime.toml`` (override with
``DECKHAND_RUNTIME_FILE``). Clients read it so a port change in the
checkout ``config.toml`` still reaches OpenDeck, whose working directory
cannot see that file.

The file is live only while ``pid`` is still running. After Core exits,
clients fall back to ``config.toml`` / defaults so a *planned* port
change is picked up on the next start.
"""

from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path

logger = logging.getLogger(__name__)

_WILDCARD_HOSTS = frozenset({"0.0.0.0", "::", "[::]"})


def runtime_file_path() -> Path:
    """Return the runtime.toml path (env override, else XDG-style home)."""
    explicit = os.getenv("DECKHAND_RUNTIME_FILE")
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / ".config" / "deckhand" / "runtime.toml"


def advertised_url(host: str, port: int) -> str:
    """Client-facing URL for a listen address (wildcards become loopback)."""
    if host in _WILDCARD_HOSTS:
        host = "127.0.0.1"
    return f"http://{host}:{port}"


def write_runtime(host: str, port: int, *, pid: int | None = None) -> Path | None:
    """Atomically write the live bind. Returns the path, or None on failure."""
    path = runtime_file_path()
    url = advertised_url(host, port)
    process_id = os.getpid() if pid is None else pid
    body = (
        "# Written by Deckhand Core on startup. Do not edit.\n"
        f'url = "{url}"\n'
        f"pid = {process_id}\n"
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
        logger.info("Wrote live client URL to %s", path)
        return path
    except OSError as exc:
        logger.warning("Could not write runtime file %s: %s", path, exc)
        return None


def read_live_url() -> str | None:
    """Return the advertised URL if the writer pid is still alive."""
    path = runtime_file_path()
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


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
