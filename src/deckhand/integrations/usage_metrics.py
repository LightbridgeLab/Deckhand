"""Shared helpers for publishing plan/quota bars to the state store."""

from __future__ import annotations

import time
from datetime import UTC
from email.utils import parsedate_to_datetime
from typing import Any

_DEFAULT_MAX_BACKOFF_SEC = 15 * 60.0


def plan_bar_value(
    *,
    label: str,
    short_label: str,
    percent: float | None,
    resets_at: str | None,
    updated_at: float,
    available: bool,
) -> dict[str, Any]:
    """Build the normalized widget value for a plan/quota percentage bar.

    ``percent`` is used % on a 0–100 scale. When unavailable, widgets get
    ``percent: null`` and a ``—`` title so they do not keep stale numbers.
    """
    if not available:
        return {
            "label": label,
            "short_label": short_label,
            "current": None,
            "max": 100,
            "percent": None,
            "unit": "percent",
            "resets_at": resets_at,
            "updated_at": updated_at,
            "title": f"{short_label}\n—",
        }
    return {
        "label": label,
        "short_label": short_label,
        "current": percent,
        "max": 100,
        "percent": percent,
        "unit": "percent",
        "resets_at": resets_at,
        "updated_at": updated_at,
        "title": (
            f"{short_label}\n{percent:.0f}%"
            if percent is not None
            else f"{short_label}\n—"
        ),
    }


def clamp_poll_interval(
    name: str,
    value: float,
    *,
    minimum: float,
    log,
    plugin_id: str,
) -> float:
    """Floor ``value`` at ``minimum`` and log when clamping fires."""
    if value < minimum:
        log.warning(
            "%s: %s=%s is below minimum %s; using %s instead",
            plugin_id,
            name,
            value,
            minimum,
            minimum,
        )
        return minimum
    return value


def parse_retry_after_seconds(
    header: str | None, *, now: float | None = None
) -> float | None:
    """Parse an HTTP ``Retry-After`` value into seconds from ``now``.

    Accepts a delay in seconds or an HTTP-date. Returns ``None`` when the
    header is missing or unusable.
    """
    if header is None:
        return None
    raw = header.strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    epoch = now if now is not None else time.time()
    return max(0.0, when.timestamp() - epoch)


def backoff_poll_delay(
    consecutive_failures: int,
    base_interval: float,
    retry_after: float | None = None,
    *,
    max_delay: float = _DEFAULT_MAX_BACKOFF_SEC,
) -> float:
    """Seconds to wait after a failed poll before the next attempt.

    Exponential backoff is capped at ``max_delay``. A positive
    ``retry_after`` from the server is honored even when larger than the
    cap, so a 429 window is not truncated.
    """
    failures = max(1, consecutive_failures)
    exponential = min(base_interval * (2 ** (failures - 1)), max_delay)
    delay = max(base_interval, exponential)
    if retry_after is not None and retry_after > 0:
        delay = max(delay, retry_after)
    return delay
