"""Session-hook install/ingest helpers for first-party coding agents.

Claude Code and Cursor are the only first-party lifecycle adapters. This
module owns payload normalization, idempotent hook-file merges, and the
hook error log used by ``deckhand hooks status``.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
import time
from pathlib import Path
from typing import Any

# Stable substring in installed hook commands — used for idempotent merge.
INGEST_MARKER = "hooks ingest"

CLAUDE_HOOK_EVENTS: tuple[str, ...] = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "Notification",
    "Stop",
    "SessionEnd",
)

# (cursor_event_name, deckhand_status_override | None)
CURSOR_HOOK_EVENTS: tuple[tuple[str, str | None], ...] = (
    ("sessionStart", None),
    ("beforeSubmitPrompt", None),
    ("preToolUse", None),
    ("postToolUse", None),
    ("postToolUseFailure", None),
    ("stop", "awaiting_input"),
    ("sessionEnd", None),
)


def resolve_deckhand_binary() -> str:
    """Absolute path to the ``deckhand`` executable for hook commands.

    GUI-launched agents (Cursor.app) often lack a useful PATH, so install
    must write an absolute path.
    """
    found = shutil.which("deckhand")
    if found:
        return str(Path(found).resolve())
    # Fallback: same interpreter's scripts dir (editable / venv installs)
    scripts = Path(sys.executable).resolve().parent / "deckhand"
    if scripts.is_file():
        return str(scripts)
    return "deckhand"


def default_hooks_log_path() -> Path:
    """``~/.deckhand/hooks.log`` (or ``$DECKHAND_HOME/hooks.log``)."""
    home = os.environ.get("DECKHAND_HOME")
    if home:
        return Path(home).expanduser() / "hooks.log"
    return Path.home() / ".deckhand" / "hooks.log"


def append_hook_log(
    message: str,
    *,
    path: Path | None = None,
    agent_type: str | None = None,
) -> Path:
    """Append one line to the hook log. Returns the log path."""
    log_path = path or default_hooks_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    prefix = f"{ts}"
    if agent_type:
        prefix = f"{prefix} [{agent_type}]"
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"{prefix} {message}\n")
    return log_path


def read_last_hook_log_line(path: Path | None = None) -> str | None:
    log_path = path or default_hooks_log_path()
    if not log_path.is_file():
        return None
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if line.strip():
            return line.strip()
    return None


def hook_log_line_is_ok(line: str | None) -> bool:
    """True when the last log line is a successful ingest (``… ok``)."""
    if not line:
        return False
    return line.rstrip().endswith(" ok")


def normalize_claude_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Attach ``iterm_session_id`` from the environment when present."""
    payload = dict(raw)
    iterm = os.environ.get("ITERM_SESSION_ID")
    if iterm and not payload.get("iterm_session_id"):
        payload["iterm_session_id"] = iterm
    return payload


def normalize_cursor_payload(
    raw: dict[str, Any],
    *,
    event: str | None = None,
    deckhand_status: str | None = None,
) -> dict[str, Any]:
    """Map Cursor hook stdin onto Deckhand's cursor hook schema.

    Accepts already-normalized payloads (``hook_event_name`` + ``cwd``) and
    raw Cursor shapes (``workspace_roots``, ``prompt``).
    """
    event_name = event or raw.get("hook_event_name")
    if not isinstance(event_name, str) or not event_name:
        raise ValueError(
            "cursor ingest needs --event or a payload with hook_event_name"
        )

    session_id = raw.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("cursor hook payload missing session_id")

    cwd = raw.get("cwd")
    if not cwd:
        roots = raw.get("workspace_roots")
        if isinstance(roots, list) and roots and isinstance(roots[0], str):
            cwd = roots[0]

    title = raw.get("title")
    if not title:
        prompt = raw.get("prompt")
        if isinstance(prompt, str) and prompt:
            title = prompt

    status = deckhand_status
    if status is None:
        status = raw.get("deckhand_status")
        if not isinstance(status, str):
            status = None
        # Default for stop matches examples/cursor_hooks.json
        if status is None and event_name == "stop":
            status = "awaiting_input"

    out: dict[str, Any] = {
        "session_id": session_id,
        "hook_event_name": event_name,
    }
    if isinstance(cwd, str) and cwd:
        out["cwd"] = cwd
    if isinstance(title, str) and title:
        out["title"] = title
    if status:
        out["deckhand_status"] = status
    return out


def ingest_command(
    binary: str,
    agent_type: str,
    *,
    event: str | None = None,
    deckhand_status: str | None = None,
    config_path: str | None = None,
) -> str:
    """Shell command string written into agent hook config files.

    ``--config`` is a root CLI flag and must come before ``hooks ingest``.
    Agent hosts run hooks with cwd = the user's project, not the Deckhand
    checkout, so without an absolute config path ingest sends no API key.
    """
    parts = [binary]
    if config_path:
        parts.extend(["--config", config_path])
    parts.extend(["hooks", "ingest", agent_type])
    if event:
        parts.extend(["--event", event])
    if deckhand_status:
        parts.extend(["--status", deckhand_status])
    return " ".join(shlex.quote(p) for p in parts)


def _is_deckhand_command(command: str) -> bool:
    return (
        INGEST_MARKER in command
        or "agents/claude-code/hook" in command
        or ("agents/cursor/hook" in command)
    )


def merge_claude_settings(
    settings: dict[str, Any],
    *,
    binary: str,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Merge Deckhand Claude Code hooks into a settings.json document."""
    out = dict(settings)
    hooks = dict(out.get("hooks") or {}) if isinstance(out.get("hooks"), dict) else {}
    command = ingest_command(binary, "claude-code", config_path=config_path)
    entry = {"hooks": [{"type": "command", "command": command}]}

    for event in CLAUDE_HOOK_EVENTS:
        existing = hooks.get(event)
        groups: list[Any] = list(existing) if isinstance(existing, list) else []
        groups = [g for g in groups if not _claude_group_is_ours(g)]
        # PreToolUse historically carried a matcher in our examples
        if event == "PreToolUse":
            groups.append({"matcher": "", **entry})
        else:
            groups.append(dict(entry))
        hooks[event] = groups

    out["hooks"] = hooks
    return out


def _claude_group_is_ours(group: Any) -> bool:
    if not isinstance(group, dict):
        return False
    inner = group.get("hooks")
    if not isinstance(inner, list):
        return False
    for item in inner:
        if isinstance(item, dict) and _is_deckhand_command(
            str(item.get("command", ""))
        ):
            return True
    return False


def merge_cursor_hooks(
    document: dict[str, Any],
    *,
    binary: str,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Merge Deckhand Cursor hooks into a hooks.json document."""
    out = dict(document)
    if "version" not in out:
        out["version"] = 1
    hooks = dict(out.get("hooks") or {}) if isinstance(out.get("hooks"), dict) else {}

    for event, status in CURSOR_HOOK_EVENTS:
        command = ingest_command(
            binary,
            "cursor",
            event=event,
            deckhand_status=status,
            config_path=config_path,
        )
        existing = hooks.get(event)
        entries: list[Any] = list(existing) if isinstance(existing, list) else []
        entries = [
            e
            for e in entries
            if not (
                isinstance(e, dict) and _is_deckhand_command(str(e.get("command", "")))
            )
        ]
        entries.append({"command": command})
        hooks[event] = entries

    out["hooks"] = hooks
    return out


def claude_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def cursor_hooks_path() -> Path:
    return Path.home() / ".cursor" / "hooks.json"


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def file_has_deckhand_ingest(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return INGEST_MARKER in text


def file_has_config_flag(path: Path) -> bool:
    """True when installed ingest commands pin ``--config`` (cwd-safe auth)."""
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return INGEST_MARKER in text and "--config" in text


def resolve_config_for_hooks(config_file_path: str | None) -> str | None:
    """Absolute config.toml path to bake into hook commands, if the file exists."""
    if not config_file_path:
        return None
    path = Path(config_file_path).expanduser()
    try:
        path = path.resolve()
    except OSError:
        return None
    return str(path) if path.is_file() else None
