"""Cursor IDE focuser via the macOS ``open`` command.

We use ``open -a Cursor <workspace_path>`` rather than AppleScript
window-walking because Cursor exposes no per-workspace identifier
through its AppleScript surface — the only available signal is the
window title, which mutates (unsaved-indicator dots, multi-root names,
arbitrary user-set tab text) and is unreliable for matching. ``open -a``
hands the routing decision to Cursor itself: if a window is already
showing the workspace, that window is raised; otherwise Cursor opens
one. The call is one short subprocess spawn with no script to template
and no escaping concerns.

Precision actually achieved:

* **Cursor running + workspace already open:** the existing window is
  raised. Common case during normal use.
* **Cursor running + workspace not open:** Cursor opens a new window
  for it. Arguably surprising in a "focus" action, but doing nothing
  is worse for the ``focus_next_pending`` flow than reopening.
* **Cursor not running:** it launches with the workspace open.
* **No ``project_root`` available:** the focuser falls back to a bare
  ``open -a Cursor`` which raises Cursor's frontmost window. Useful
  when the originating hook payload omitted ``cwd``.

The focuser never raises: missing ``open`` binary, subprocess timeout,
and non-zero exit codes are all logged and swallowed.
``agents.focus_next_pending`` moves on to the next pending agent if a
focuser fails or hangs.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess

logger = logging.getLogger(__name__)

_OPEN_TIMEOUT_SECONDS = 5.0


def make_cursor_focuser(project_root: str | None):
    """Build an async focuser callable for a Cursor session.

    ``project_root`` is the workspace path the focuser will target on
    invocation. Passing ``None`` falls back to activating the Cursor
    app without a workspace switch.
    """

    async def focuser() -> None:
        await asyncio.to_thread(_open_cursor, project_root)

    return focuser


def _open_cursor(project_root: str | None) -> None:
    cmd = ["open", "-a", "Cursor"]
    if project_root:
        cmd.append(project_root)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_OPEN_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        logger.warning("`open` not available; cursor focuser is a no-op")
        return
    except subprocess.TimeoutExpired:
        logger.warning("cursor focuser timed out for project_root=%s", project_root)
        return

    if result.returncode != 0:
        logger.warning(
            "cursor focuser exited %s for project_root=%s: %s",
            result.returncode,
            project_root,
            (result.stderr or "").strip(),
        )
