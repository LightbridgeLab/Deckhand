"""Hook ingest, install, status, and simulate commands."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from deckhand.cli.client import DeckhandClient, DeckhandError
from deckhand.cli.formatters import emit_error, emit_json
from deckhand.integrations import session_hooks as sh


def _read_stdin_json() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        emit_error("expected a JSON hook payload on stdin")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        emit_error(f"invalid JSON on stdin: {exc}")
    if not isinstance(payload, dict):
        emit_error("hook payload must be a JSON object")
    return payload


def ingest(
    client: DeckhandClient,
    agent_type: str,
    *,
    event: str | None = None,
    status: str | None = None,
    quiet: bool = True,
) -> None:
    """Read hook JSON from stdin, normalize, POST to Core.

    On failure: append to ``~/.deckhand/hooks.log`` and exit 0 so coding
    sessions are not blocked by a dead Deckhand. Use ``hooks status`` to
    see the last error. Invalid stdin / unknown type still exit non-zero
    (config bugs should be visible).
    """
    payload = _read_stdin_json()
    body: dict[str, Any] = {}
    result: Any = None

    try:
        if agent_type == "claude-code":
            body = sh.normalize_claude_payload(payload)
            result = client.post_claude_code_hook(body)
        elif agent_type == "cursor":
            body = sh.normalize_cursor_payload(
                payload, event=event, deckhand_status=status
            )
            result = client.post_cursor_hook(body)
        else:
            emit_error(
                f"unknown agent type {agent_type!r} "
                "(expected 'claude-code' or 'cursor')"
            )
    except ValueError as exc:
        emit_error(str(exc))
    except DeckhandError as exc:
        log_path = sh.append_hook_log(str(exc), agent_type=agent_type)
        if not quiet:
            print(
                f"error: {exc} (logged to {log_path})",
                file=sys.stderr,
            )
        # Exit 0 so the agent host does not treat the hook as a hard failure.
        raise SystemExit(0) from None

    # Session bookends only — PreToolUse would flood the log. Clears a stale
    # 401 so ``hooks status`` stops warning after a successful ping.
    event_name = ""
    if isinstance(body, dict):
        raw_event = body.get("hook_event_name")
        if isinstance(raw_event, str):
            event_name = raw_event
    if event_name in ("SessionStart", "sessionStart", "SessionEnd", "sessionEnd"):
        sh.append_hook_log("ok", agent_type=agent_type)

    if not quiet:
        emit_json(result)


def simulate(client: DeckhandClient, agent_type: str) -> None:
    """Alias for ingest with JSON printed on success (dev / tests)."""
    ingest(client, agent_type, quiet=False)


def install(
    targets: list[str],
    *,
    binary: str | None = None,
    claude_path: Path | None = None,
    cursor_path: Path | None = None,
    config_path: str | None = None,
) -> None:
    """Merge Deckhand ingest hooks into Claude Code / Cursor config files."""
    bin_path = binary or sh.resolve_deckhand_binary()
    pinned_config = sh.resolve_config_for_hooks(config_path)
    wanted = set(targets)
    if "all" in wanted:
        wanted = {"claude-code", "cursor"}

    unknown = wanted - {"claude-code", "cursor"}
    if unknown:
        emit_error(
            f"unknown install target(s): {', '.join(sorted(unknown))} "
            "(expected claude-code, cursor, or all)"
        )
    if not wanted:
        emit_error("specify at least one of: claude-code, cursor, all")

    results: dict[str, Any] = {
        "binary": bin_path,
        "config": pinned_config,
        "installed": [],
    }

    if "claude-code" in wanted:
        path = claude_path or sh.claude_settings_path()
        before = sh.load_json_file(path)
        after = sh.merge_claude_settings(
            before, binary=bin_path, config_path=pinned_config
        )
        sh.write_json_file(path, after)
        results["installed"].append(
            {
                "agent": "claude-code",
                "path": str(path),
                "events": list(sh.CLAUDE_HOOK_EVENTS),
            }
        )

    if "cursor" in wanted:
        path = cursor_path or sh.cursor_hooks_path()
        before = sh.load_json_file(path)
        after = sh.merge_cursor_hooks(
            before, binary=bin_path, config_path=pinned_config
        )
        sh.write_json_file(path, after)
        results["installed"].append(
            {
                "agent": "cursor",
                "path": str(path),
                "events": [e for e, _ in sh.CURSOR_HOOK_EVENTS],
            }
        )

    results["next_steps"] = [
        "Start a coding session in the tool you installed hooks for.",
        "Run: uv run deckhand agents list   (or Refresh on Agent Status).",
        "To try Agent Status without IDE hooks: uv run deckhand agents demo",
    ]
    if not pinned_config:
        results["warning"] = (
            "No config.toml found to pin with --config. Hook subprocesses "
            "run from other project directories and will 401 unless "
            "~/.config/deckhand/config.toml exists."
        )
    emit_json(results)


def status(client: DeckhandClient | None, *, api_key: str | None) -> None:
    """Diagnose hook setup and Core connectivity."""
    last_line = sh.read_last_hook_log_line()
    last_ok = sh.hook_log_line_is_ok(last_line)
    report: dict[str, Any] = {
        "api_key_configured": bool(api_key),
        "hooks_log": str(sh.default_hooks_log_path()),
        "last_ingest_error": None if last_ok else last_line,
        "claude_settings": {
            "path": str(sh.claude_settings_path()),
            "exists": sh.claude_settings_path().is_file(),
            "has_deckhand_ingest": sh.file_has_deckhand_ingest(
                sh.claude_settings_path()
            ),
            "has_config_flag": sh.file_has_config_flag(sh.claude_settings_path()),
        },
        "cursor_hooks": {
            "path": str(sh.cursor_hooks_path()),
            "exists": sh.cursor_hooks_path().is_file(),
            "has_deckhand_ingest": sh.file_has_deckhand_ingest(sh.cursor_hooks_path()),
            "has_config_flag": sh.file_has_config_flag(sh.cursor_hooks_path()),
        },
    }

    if client is None:
        report["core"] = {"reachable": False, "error": "no client"}
        emit_json(report)
        return

    try:
        agents = client.list_agents()
        report["core"] = {
            "reachable": True,
            "agent_count": len(agents) if isinstance(agents, list) else 0,
        }
    except DeckhandError as exc:
        report["core"] = {"reachable": False, "error": str(exc)}

    hints: list[str] = []
    if not report["api_key_configured"]:
        hints.append(
            "No API key in config/env — set [client].api_key or DECKHAND_API_KEY."
        )
    if (
        not report["claude_settings"]["has_deckhand_ingest"]
        and not report["cursor_hooks"]["has_deckhand_ingest"]
    ):
        hints.append(
            "No Deckhand ingest hooks found — run: uv run deckhand hooks install"
        )
    core = report.get("core") or {}
    if core.get("reachable") and core.get("agent_count") == 0:
        hints.append(
            "Core is up but no live sessions. Start a hooked session, or: "
            "uv run deckhand agents demo"
        )
    if not core.get("reachable"):
        hints.append("Deckhand Core is not reachable — start it (e.g. make dev).")
    last_err = str(report.get("last_ingest_error") or "")
    missing_config_flag = (
        report["claude_settings"]["has_deckhand_ingest"]
        and not report["claude_settings"]["has_config_flag"]
    ) or (
        report["cursor_hooks"]["has_deckhand_ingest"]
        and not report["cursor_hooks"]["has_config_flag"]
    )
    if missing_config_flag and not core.get("agent_count"):
        hints.append(
            "Installed hooks are missing --config, so ingest 401s from other "
            "project directories. Re-run from the Deckhand repo: "
            "uv run deckhand hooks install"
        )
    elif last_err and not core.get("agent_count"):
        if "Missing API key" in last_err:
            hints.append(
                "Last ingest got 401 Missing API key. Re-run from the "
                "Deckhand repo: uv run deckhand hooks install"
            )
        else:
            hints.append("Last ingest error is in hooks_log — fix auth/URL and retry.")

    report["hints"] = hints
    emit_json(report)
