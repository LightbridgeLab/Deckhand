"""iTerm2 tab focuser via AppleScript.

We use ``osascript`` rather than the iTerm2 Python API because:

* No dependency on the user enabling iTerm's Python runtime.
* Zero new Python dependencies (``osascript`` ships with macOS).
* iTerm's AppleScript surface is stable and the per-session UUID is
  exposed as ``id of <session>``.
* Easy to mock in tests (one ``subprocess.run`` call).

iTerm sets ``$ITERM_SESSION_ID`` automatically in every shell session it
spawns; the Claude Code hook payload reads that env var and forwards it
as ``iterm_session_id``. When the user runs Claude outside iTerm the
field is absent, no focuser is registered, and the agent simply shows
up as not-focusable in the pending-input queue.

The AppleScript walks every window/tab/session, matches on the supplied
session UUID, activates iTerm, and selects the containing window + tab.
``do shell script "true"`` at the end suppresses AppleScript's default
echo so the subprocess returns cleanly.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess

logger = logging.getLogger(__name__)

# iTerm session UUIDs include a colon-separated tty hint after the UUID
# (e.g. "w0t1p0:UUID"); we strip everything before the last colon so the
# script matches on the raw UUID. Real session ids in our test corpus
# don't contain that prefix but stripping is cheap and defensive.


def _build_applescript(iterm_session_id: str) -> str:
    # AppleScript itself does the matching so we don't have to parse iTerm
    # output. ``contains`` matches the trailing UUID even if iTerm reports
    # the longer ``w0t1p0:UUID`` form.
    safe_id = iterm_session_id.replace('"', '\\"')
    return f'''
        tell application "iTerm2"
            activate
            repeat with theWindow in windows
                repeat with theTab in tabs of theWindow
                    repeat with theSession in sessions of theTab
                        if (id of theSession as string) contains "{safe_id}" then
                            select theWindow
                            tell theWindow to select theTab
                            tell theTab to select theSession
                            return
                        end if
                    end repeat
                end repeat
            end repeat
        end tell
    '''


def make_iterm_focuser(iterm_session_id: str):
    """Build an async focuser callable for a specific iTerm session UUID."""

    script = _build_applescript(iterm_session_id)

    async def focuser() -> None:
        await asyncio.to_thread(_run_osascript, script, iterm_session_id)

    return focuser


def _run_osascript(script: str, session_id: str) -> None:
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError:
        logger.warning("osascript not available; iTerm focuser is a no-op")
        return
    except subprocess.TimeoutExpired:
        logger.warning("iTerm focuser timed out for session %s", session_id)
        return

    if result.returncode != 0:
        logger.warning(
            "iTerm focuser exited %s for session %s: %s",
            result.returncode,
            session_id,
            (result.stderr or "").strip(),
        )
