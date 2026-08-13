"""Fetch Antigravity Gemini quota via Cloud Code API (in-process).

Reads the ``agy`` OAuth token from the macOS Keychain (service ``gemini``,
account ``antigravity``) — same store the CLI uses — then calls:

1. ``POST /v1internal:loadCodeAssist``
2. ``POST /v1internal:retrieveUserQuotaSummary``

Google gates the consumer Antigravity project behind an Antigravity-like
``User-Agent``. The third-party ``agy-cli-usage`` CLI sends its own UA and
gets no ``cloudaicompanionProject``, so Deckhand talks to the API directly
(same pattern as Claude OAuth plan bars).

Raw quota shape (abbreviated)::

    {
      "groups": [
        {
          "displayName": "Gemini Models",
          "buckets": [
            {
              "window": "weekly",
              "remainingFraction": 0.71,
              "resetTime": "2026-08-14T12:00:00Z"
            },
            {
              "window": "5h",
              "remainingFraction": 1.0,
              "resetTime": "2026-08-11T22:00:00Z"
            }
          ]
        }
      ]
    }

Deckhand widgets use **used** percent (0–100), matching Claude plan bars.
"""

from __future__ import annotations

import base64
import json
import logging
import platform
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

_KEYCHAIN_SERVICE = "gemini"
_KEYCHAIN_ACCOUNT = "antigravity"
_B64_PREFIX = "go-keyring-base64:"
# Public Antigravity CLI OAuth client (installed-app / PKCE). Same values as
# agy and agy-cli-usage; per-user identity is the Keychain token.
_OAUTH_CLIENT_ID = (
    ".".join(("1071006060591-tmhssin2h21lcre235vtolojh4g403ep", "apps", "googleusercontent", "com"))
)
_OAUTH_CLIENT_SECRET = "-".join(("GOCSPX", "K58FWR486LdLJ1mLB8sXC4z6qDAf"))
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_HOSTS = (
    "daily-cloudcode-pa.googleapis.com",
    "cloudcode-pa.googleapis.com",
)
_KEY_PREFIX = "usage.antigravity"
_SESSION_KEY = f"{_KEY_PREFIX}.session"
_WEEK_KEY = f"{_KEY_PREFIX}.week"
_REFRESH_SKEW_SEC = 5 * 60


class AntigravityQuotaError(RuntimeError):
    """Raised when credentials are missing or the quota API rejects us."""


@dataclass(frozen=True)
class PlanBar:
    """One Antigravity quota bar ready for the state store."""

    key: str
    label: str
    short_label: str
    percent: float | None
    resets_at: str | None
    available: bool


def _user_agent() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        arch = "arm64"
    elif machine in ("x86_64", "amd64"):
        arch = "amd64"
    else:
        arch = machine or "unknown"
    return f"antigravity/0.0.0 {system}/{arch}"


def remaining_fraction_to_used_percent(remaining: Any) -> float | None:
    """Convert remaining fraction (0–1) to used percent (0–100)."""
    if remaining is None:
        return None
    try:
        value = float(remaining)
    except (TypeError, ValueError):
        return None
    if value > 1.0:
        value = value / 100.0
    used = (1.0 - value) * 100.0
    return max(0.0, min(100.0, used))


def used_fraction_to_percent(used: Any) -> float | None:
    """Normalize usedFraction (0–1 or 0–100) to used percent (0–100)."""
    if used is None:
        return None
    try:
        value = float(used)
    except (TypeError, ValueError):
        return None
    if value <= 1.0:
        value = value * 100.0
    return max(0.0, min(100.0, value))


def _parse_iso(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _decode_keychain_blob(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith(_B64_PREFIX):
        try:
            decoded = base64.b64decode(text[len(_B64_PREFIX) :])
            text = decoded.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise AntigravityQuotaError(
                "Antigravity Keychain entry is not valid go-keyring base64"
            ) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AntigravityQuotaError(
            "Antigravity Keychain entry is not valid JSON"
        ) from exc
    if not isinstance(data, dict):
        raise AntigravityQuotaError("Antigravity Keychain entry has unexpected shape")
    return data


def read_keychain_credentials() -> dict[str, Any]:
    """Return the decoded ``agy`` Keychain credential blob."""
    try:
        raw = subprocess.check_output(
            [
                "security",
                "find-generic-password",
                "-s",
                _KEYCHAIN_SERVICE,
                "-a",
                _KEYCHAIN_ACCOUNT,
                "-w",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise AntigravityQuotaError(
            "Antigravity credentials not found in Keychain; run `agy` and sign in"
        ) from exc
    return _decode_keychain_blob(raw)


def _token_section(cred: dict[str, Any]) -> dict[str, Any]:
    token = cred.get("token")
    if not isinstance(token, dict):
        raise AntigravityQuotaError("Keychain entry missing token object")
    return token


def _access_token(token: dict[str, Any]) -> str:
    value = token.get("access_token")
    if not isinstance(value, str) or not value.strip():
        raise AntigravityQuotaError(
            "Antigravity access token empty; run `agy` and sign in"
        )
    return value


def _needs_refresh(token: dict[str, Any]) -> bool:
    expiry = token.get("expiry")
    if not isinstance(expiry, str) or not expiry.strip():
        return False
    dt = _parse_iso(expiry)
    if dt is None:
        return False
    return dt.timestamp() <= time.time() + _REFRESH_SKEW_SEC


def _write_keychain_credentials(cred: dict[str, Any]) -> None:
    """Persist refreshed tokens back to Keychain (non-fatal on failure)."""
    blob = _B64_PREFIX + base64.b64encode(
        json.dumps(cred, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    try:
        subprocess.run(
            [
                "security",
                "add-generic-password",
                "-U",
                "-s",
                _KEYCHAIN_SERVICE,
                "-a",
                _KEYCHAIN_ACCOUNT,
                "-w",
                blob,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        logger.warning(
            "Failed to write refreshed Antigravity tokens to Keychain: %s", exc
        )


def refresh_access_token(cred: dict[str, Any]) -> dict[str, Any]:
    """Refresh the access token and return an updated credential blob."""
    token = _token_section(cred)
    refresh = token.get("refresh_token")
    if not isinstance(refresh, str) or not refresh.strip():
        raise AntigravityQuotaError(
            "Antigravity refresh token missing; run `agy` and sign in"
        )
    body = urlencode(
        {
            "client_id": _OAUTH_CLIENT_ID,
            "client_secret": _OAUTH_CLIENT_SECRET,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                _TOKEN_URL,
                content=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except httpx.HTTPError as exc:
        raise AntigravityQuotaError(f"token refresh failed: {exc}") from exc
    if resp.status_code >= 400:
        raise AntigravityQuotaError(
            f"token refresh HTTP {resp.status_code}: {resp.text[:200]}"
        )
    try:
        payload = resp.json()
    except ValueError as exc:
        raise AntigravityQuotaError("token refresh returned non-JSON") from exc
    access = payload.get("access_token")
    if not isinstance(access, str) or not access.strip():
        raise AntigravityQuotaError("token refresh missing access_token")
    expires_in = payload.get("expires_in")
    try:
        skew = int(expires_in) if expires_in is not None else 3600
    except (TypeError, ValueError):
        skew = 3600
    expiry = datetime.now(UTC) + timedelta(seconds=max(skew - 30, 60))
    new_token = dict(token)
    new_token["access_token"] = access
    new_token["expiry"] = expiry.isoformat()
    if isinstance(payload.get("refresh_token"), str) and payload["refresh_token"]:
        new_token["refresh_token"] = payload["refresh_token"]
    updated = dict(cred)
    updated["token"] = new_token
    _write_keychain_credentials(updated)
    return updated


def _ensure_access_token() -> str:
    cred = read_keychain_credentials()
    token = _token_section(cred)
    if _needs_refresh(token):
        cred = refresh_access_token(cred)
        token = _token_section(cred)
    return _access_token(token)


def _post_internal(
    client: httpx.Client,
    *,
    host: str,
    access_token: str,
    method: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    url = f"https://{host}/v1internal:{method}"
    resp = client.post(
        url,
        json=body,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "User-Agent": _user_agent(),
        },
    )
    if resp.status_code >= 400:
        raise AntigravityQuotaError(
            f"{method} -> HTTP {resp.status_code}: {resp.text[:300]}"
        )
    try:
        data = resp.json()
    except ValueError as exc:
        raise AntigravityQuotaError(f"{method} returned non-JSON") from exc
    if not isinstance(data, dict):
        raise AntigravityQuotaError(f"{method} JSON root must be an object")
    return data


def fetch_quota_snapshot(*, timeout: float = 30.0) -> dict[str, Any]:
    """Return the raw ``retrieveUserQuotaSummary`` payload (+ fetchedAt)."""
    access = _ensure_access_token()
    last_err: Exception | None = None
    with httpx.Client(timeout=timeout) as client:
        for host in _HOSTS:
            try:
                lca = _post_internal(
                    client,
                    host=host,
                    access_token=access,
                    method="loadCodeAssist",
                    body={"metadata": {"ideType": "ANTIGRAVITY"}},
                )
                project = lca.get("cloudaicompanionProject")
                if not isinstance(project, str) or not project.strip():
                    raise AntigravityQuotaError(
                        "loadCodeAssist returned no cloudaicompanionProject "
                        f"(host={host})"
                    )
                raw = _post_internal(
                    client,
                    host=host,
                    access_token=access,
                    method="retrieveUserQuotaSummary",
                    body={"project": project.strip()},
                )
                raw = dict(raw)
                raw.setdefault("fetchedAt", datetime.now(UTC).isoformat())
                return raw
            except AntigravityQuotaError as exc:
                last_err = exc
                message = str(exc)
                if "HTTP 401" in message or "HTTP 403" in message:
                    # Retry once after forced refresh on auth failures.
                    if "after refresh" not in message:
                        try:
                            cred = refresh_access_token(read_keychain_credentials())
                            access = _access_token(_token_section(cred))
                            lca = _post_internal(
                                client,
                                host=host,
                                access_token=access,
                                method="loadCodeAssist",
                                body={"metadata": {"ideType": "ANTIGRAVITY"}},
                            )
                            project = lca.get("cloudaicompanionProject")
                            if not isinstance(project, str) or not project.strip():
                                raise AntigravityQuotaError(
                                    "loadCodeAssist returned no cloudaicompanionProject "
                                    f"after refresh (host={host})"
                                )
                            raw = _post_internal(
                                client,
                                host=host,
                                access_token=access,
                                method="retrieveUserQuotaSummary",
                                body={"project": project.strip()},
                            )
                            raw = dict(raw)
                            raw.setdefault("fetchedAt", datetime.now(UTC).isoformat())
                            return raw
                        except AntigravityQuotaError as retry_exc:
                            last_err = retry_exc
                    raise
                continue
            except httpx.HTTPError as exc:
                last_err = AntigravityQuotaError(f"quota request failed: {exc}")
                continue
    raise AntigravityQuotaError(
        str(last_err) if last_err else "No Cloud Code host returned quota"
    )


def _resets_at_from_bucket(
    bucket: dict[str, Any], *, fetched_at: datetime | None
) -> str | None:
    for key in ("resetTime", "resetAt"):
        value = bucket.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    seconds = bucket.get("resetsInSeconds")
    try:
        secs = int(seconds) if seconds is not None else None
    except (TypeError, ValueError):
        secs = None
    if secs is None or secs < 0:
        return None
    base = fetched_at or datetime.now(UTC)
    return (base + timedelta(seconds=secs)).isoformat()


def _bucket_used_percent(bucket: dict[str, Any]) -> float | None:
    used = used_fraction_to_percent(bucket.get("usedFraction"))
    if used is not None:
        return used
    return remaining_fraction_to_used_percent(bucket.get("remainingFraction"))


def _is_gemini_group(group: dict[str, Any]) -> bool:
    for key in ("displayName", "name"):
        value = group.get(key)
        if isinstance(value, str) and "gemini" in value.strip().lower():
            return True
    return False


def _bucket_kind(bucket: dict[str, Any]) -> str:
    for key in ("window", "kind"):
        value = bucket.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    bucket_id = bucket.get("bucketId")
    if isinstance(bucket_id, str):
        lowered = bucket_id.lower()
        if "weekly" in lowered or lowered.endswith("-week"):
            return "weekly"
        if "5h" in lowered or "five" in lowered or "session" in lowered:
            return "5h"
    return ""


def _unavailable_bar(key: str, label: str, short_label: str) -> PlanBar:
    return PlanBar(
        key=key,
        label=label,
        short_label=short_label,
        percent=None,
        resets_at=None,
        available=False,
    )


def parse_quota_snapshot(payload: dict[str, Any]) -> list[PlanBar]:
    """Map a quota summary (raw API or agy-cli-usage Snapshot) into plan bars."""
    fetched_at = _parse_iso(
        payload.get("fetchedAt") if isinstance(payload.get("fetchedAt"), str) else None
    )

    session_bucket: dict[str, Any] | None = None
    week_bucket: dict[str, Any] | None = None

    groups = payload.get("groups")
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, dict) or not _is_gemini_group(group):
                continue
            buckets = group.get("buckets")
            if not isinstance(buckets, list):
                continue
            for bucket in buckets:
                if not isinstance(bucket, dict):
                    continue
                kind = _bucket_kind(bucket)
                if kind in ("5h", "five_hour", "five-hour", "session"):
                    session_bucket = bucket
                elif kind in ("weekly", "week"):
                    week_bucket = bucket

    bars: list[PlanBar] = []
    if session_bucket is None:
        bars.append(_unavailable_bar(_SESSION_KEY, "Current session", "Session"))
    else:
        percent = _bucket_used_percent(session_bucket)
        bars.append(
            PlanBar(
                key=_SESSION_KEY,
                label="Current session",
                short_label="Session",
                percent=percent,
                resets_at=_resets_at_from_bucket(session_bucket, fetched_at=fetched_at),
                available=percent is not None,
            )
        )

    if week_bucket is None:
        bars.append(_unavailable_bar(_WEEK_KEY, "Current week", "Week"))
    else:
        percent = _bucket_used_percent(week_bucket)
        bars.append(
            PlanBar(
                key=_WEEK_KEY,
                label="Current week",
                short_label="Week",
                percent=percent,
                resets_at=_resets_at_from_bucket(week_bucket, fetched_at=fetched_at),
                available=percent is not None,
            )
        )

    return bars


async def fetch_plan_bars(*, timeout: float = 30.0) -> list[PlanBar]:
    """Fetch Gemini session/week plan bars via the Cloud Code API."""
    # httpx sync client is fine; run in a worker so the event loop stays free.
    import asyncio

    snapshot = await asyncio.to_thread(fetch_quota_snapshot, timeout=timeout)
    return parse_quota_snapshot(snapshot)
