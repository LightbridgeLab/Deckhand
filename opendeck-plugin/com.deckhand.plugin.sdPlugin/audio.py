"""Host-side sound playback for the Deckhand OpenDeck plugin.

Plays through the computer speakers (``afplay`` on macOS), not Stream Deck
hardware. Default sounds are macOS system alerts under
``/System/Library/Sounds``.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import shutil
from pathlib import Path

logger = logging.getLogger("deckhand-audio")

SYSTEM_SOUNDS_DIR = Path("/System/Library/Sounds")
DEFAULT_SOUND = "Glass"

# Names without extension; files are ``<name>.aiff`` on macOS.
SYSTEM_SOUNDS: tuple[str, ...] = (
    "Basso",
    "Blow",
    "Bottle",
    "Frog",
    "Funk",
    "Glass",
    "Hero",
    "Morse",
    "Ping",
    "Pop",
    "Purr",
    "Sosumi",
    "Submarine",
    "Tink",
)


def resolve_sound_path(name: str) -> Path | None:
    """Resolve a system-sound name to a local file, or None if unusable."""
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        return None
    path = SYSTEM_SOUNDS_DIR / f"{name}.aiff"
    if path.is_file():
        return path
    return None


async def play_sound(name: str) -> None:
    """Play a macOS system sound by name (e.g. ``Glass``).

    Uses platform-native commands so we don't block the event loop. No-op
    when the file is missing (typical on Linux).
    """
    path = resolve_sound_path(name)
    if path is None:
        logger.warning("Sound not found: %s", name)
        return

    system = platform.system()
    if system == "Darwin":
        cmd = ["afplay", str(path)]
    elif system == "Linux":
        if shutil.which("paplay"):
            cmd = ["paplay", str(path)]
        elif shutil.which("aplay"):
            cmd = ["aplay", str(path)]
        else:
            logger.warning("No audio player found on Linux (tried paplay, aplay)")
            return
    else:
        logger.warning("Unsupported platform for audio: %s", system)
        return

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
    except OSError:
        logger.exception("Failed to play sound: %s", name)
