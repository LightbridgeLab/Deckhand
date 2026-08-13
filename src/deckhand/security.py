"""Authentication, authorization, rate limiting, and payload validation."""

from __future__ import annotations

import secrets
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

# Scope hierarchy: write implies read
SCOPE_LEVELS = {"read": 1, "write": 2}


@dataclass(frozen=True)
class ApiKeyEntry:
    """An API key with an associated authorization scope."""

    key: str
    scope: str  # "read" or "write"


def generate_api_key() -> str:
    """Generate a cryptographically secure API key."""
    return secrets.token_urlsafe(32)


def resolve_key(token: str, api_keys: list[ApiKeyEntry]) -> ApiKeyEntry | None:
    """Look up an API key entry by token value.

    Uses constant-time comparison to prevent timing attacks.
    Returns the matching entry or None.
    """
    for entry in api_keys:
        if secrets.compare_digest(entry.key, token):
            return entry
    return None


def has_scope(entry: ApiKeyEntry, required: str) -> bool:
    """Check whether *entry* meets or exceeds *required* scope."""
    return SCOPE_LEVELS.get(entry.scope, 0) >= SCOPE_LEVELS.get(required, 99)


# ---------------------------------------------------------------------------
# Payload validation against registered schemas
# ---------------------------------------------------------------------------

_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def validate_payload(
    payload: dict[str, Any], schema: dict[str, Any] | None
) -> list[str]:
    """Validate *payload* against a registered action/signal schema.

    Returns a list of human-readable error strings (empty when valid).
    """
    if not schema:
        return []

    errors: list[str] = []
    for field_name, field_def in schema.items():
        value = payload.get(field_name)
        is_required = field_def.get("required", False)

        if value is None:
            if is_required:
                errors.append(f"Missing required field: {field_name}")
            continue

        expected_type = field_def.get("type")
        if expected_type:
            python_type = _TYPE_MAP.get(expected_type)
            if python_type and not isinstance(value, python_type):
                errors.append(
                    f"Field '{field_name}' expected type '{expected_type}', "
                    f"got '{type(value).__name__}'"
                )

    return errors


# ---------------------------------------------------------------------------
# Rate limiter (fixed-window per client IP)
# ---------------------------------------------------------------------------


class RateLimiter:
    """Simple fixed-window rate limiter keyed by client IP address."""

    def __init__(self, requests_per_minute: int = 600) -> None:
        self.rpm = requests_per_minute
        self._windows: dict[str, list[float]] = defaultdict(list)

    def check(self, client_ip: str) -> bool:
        """Return True if the request is allowed, False if rate-limited."""
        now = time.monotonic()
        window_start = now - 60.0

        hits = self._windows[client_ip]
        hits[:] = [t for t in hits if t > window_start]

        if len(hits) >= self.rpm:
            return False

        hits.append(now)
        return True
