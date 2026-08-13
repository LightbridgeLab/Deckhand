"""Fetch Cursor plan/spend bars via the IDE dashboard Connect RPC.

Reads the Cursor access JWT from the local IDE state DB
(``state.vscdb`` → ``cursorAuth/accessToken``) — the same credential
community status tools use — then polls:

``POST https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage``

That is the source behind https://cursor.com/dashboard/spending:

* Cursor Models % → ``planUsage.autoPercentUsed``
* Other Models % → ``planUsage.apiPercentUsed``
* On-Demand $ / max → ``spendLimitUsage`` (cents)

There is no official personal spending API; this is an undocumented
IDE/dashboard endpoint. Deckhand widgets use **used** percent (0–100),
matching Claude and Antigravity plan bars.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_USAGE_URL = "https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage"
_TOKEN_URL = "https://api2.cursor.sh/oauth/token"
# Public Cursor IDE OAuth client id (installed-app refresh).
_CLIENT_ID = "KbZUR41cY7W6zRSdpSUJ7I7mLYBKOCmB"
_AUTH_ACCESS_KEY = "cursorAuth/accessToken"
_AUTH_REFRESH_KEY = "cursorAuth/refreshToken"
_KEY_PREFIX = "usage.cursor"
_MODELS_KEY = f"{_KEY_PREFIX}.models"
_OTHER_KEY = f"{_KEY_PREFIX}.other"
_ON_DEMAND_KEY = f"{_KEY_PREFIX}.on_demand"
_DB_LOCK_RETRIES = 5
_DB_LOCK_SLEEP_SEC = 0.05

# Process-local override after a successful refresh (avoids requiring a
# write back into Cursor's open state DB on every 401).
_runtime_access_token: str | None = None


class CursorUsageError(RuntimeError):
    """Raised when credentials are missing or the usage API rejects us."""


@dataclass(frozen=True)
class PlanBar:
    """One Cursor spend bar ready for the state store."""

    key: str
    label: str
    short_label: str
    percent: float | None
    resets_at: str | None
    available: bool


def default_state_db_path() -> Path:
    """Platform path to Cursor's ``state.vscdb`` (macOS-first)."""
    override = os.getenv("DECKHAND_CURSOR_STATE_DB")
    if override:
        return Path(override).expanduser()
    home = Path.home()
    system = os.name
    if system == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Cursor" / "User" / "globalStorage" / "state.vscdb"
    # Linux XDG-style (and fallback).
    linux = home / ".config" / "Cursor" / "User" / "globalStorage" / "state.vscdb"
    mac = (
        home
        / "Library"
        / "Application Support"
        / "Cursor"
        / "User"
        / "globalStorage"
        / "state.vscdb"
    )
    if mac.exists():
        return mac
    if linux.exists():
        return linux
    # Prefer macOS path on Darwin even when the file is not present yet.
    if Path("/System/Library").exists():
        return mac
    return linux


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path}?mode=ro"
    last_err: Exception | None = None
    for attempt in range(_DB_LOCK_RETRIES):
        try:
            return sqlite3.connect(uri, uri=True, timeout=1.0)
        except sqlite3.OperationalError as exc:
            last_err = exc
            if attempt + 1 < _DB_LOCK_RETRIES:
                time.sleep(_DB_LOCK_SLEEP_SEC * (attempt + 1))
    raise CursorUsageError(
        f"Cannot open Cursor state DB (locked or missing): {db_path}"
    ) from last_err


def _read_item_values(
    keys: tuple[str, ...], *, db_path: Path | None = None
) -> dict[str, str]:
    path = db_path or default_state_db_path()
    if not path.exists():
        raise CursorUsageError(
            f"Cursor state DB not found at {path}; launch Cursor and sign in"
        )
    try:
        con = _connect_ro(path)
    except CursorUsageError:
        raise
    except sqlite3.Error as exc:
        raise CursorUsageError(f"Cannot open Cursor state DB: {exc}") from exc
    try:
        placeholders = ",".join("?" for _ in keys)
        rows = con.execute(
            f"SELECT key, value FROM ItemTable WHERE key IN ({placeholders})",
            keys,
        ).fetchall()
    except sqlite3.Error as exc:
        raise CursorUsageError(f"Failed reading Cursor auth keys: {exc}") from exc
    finally:
        con.close()
    out: dict[str, str] = {}
    for key, value in rows:
        if isinstance(key, str) and isinstance(value, str) and value.strip():
            out[key] = value
    return out


def read_auth_tokens(*, db_path: Path | None = None) -> dict[str, str]:
    """Return ``access`` / ``refresh`` strings from ``state.vscdb``."""
    raw = _read_item_values((_AUTH_ACCESS_KEY, _AUTH_REFRESH_KEY), db_path=db_path)
    access = raw.get(_AUTH_ACCESS_KEY)
    if not access:
        raise CursorUsageError(
            "Cursor access token missing; open Cursor and sign in, then retry"
        )
    result = {"access": access}
    refresh = raw.get(_AUTH_REFRESH_KEY)
    if refresh:
        result["refresh"] = refresh
    return result


def read_access_token(*, db_path: Path | None = None) -> str:
    """Return the current Bearer token (runtime override, else state DB)."""
    if _runtime_access_token:
        return _runtime_access_token
    return read_auth_tokens(db_path=db_path)["access"]


def _write_access_token(token: str, *, db_path: Path | None = None) -> None:
    """Best-effort persist a refreshed access token into ``state.vscdb``."""
    path = db_path or default_state_db_path()
    try:
        con = sqlite3.connect(str(path), timeout=1.0)
        try:
            con.execute(
                "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                (_AUTH_ACCESS_KEY, token),
            )
            con.commit()
        finally:
            con.close()
    except sqlite3.Error as exc:
        logger.warning("Failed to write refreshed Cursor access token: %s", exc)


def refresh_access_token(
    refresh_token: str,
    *,
    client: httpx.Client | None = None,
    db_path: Path | None = None,
    persist: bool = True,
) -> str:
    """Exchange a refresh token for a new access token."""
    global _runtime_access_token
    if not refresh_token.strip():
        raise CursorUsageError("Cursor refresh token empty; re-sign in to Cursor")
    body = {
        "grant_type": "refresh_token",
        "client_id": _CLIENT_ID,
        "refresh_token": refresh_token,
    }
    owns_client = client is None
    http = client or httpx.Client(timeout=30.0)
    try:
        resp = http.post(_TOKEN_URL, json=body)
    except httpx.HTTPError as exc:
        raise CursorUsageError(f"token refresh failed: {exc}") from exc
    finally:
        if owns_client:
            http.close()
    if resp.status_code >= 400:
        raise CursorUsageError(
            f"token refresh HTTP {resp.status_code}: {resp.text[:200]}"
        )
    try:
        payload = resp.json()
    except ValueError as exc:
        raise CursorUsageError("token refresh returned non-JSON") from exc
    access = payload.get("access_token")
    if not isinstance(access, str) or not access.strip():
        raise CursorUsageError("token refresh missing access_token")
    _runtime_access_token = access
    if persist:
        _write_access_token(access, db_path=db_path)
    return access


def _clamp_percent(value: Any) -> float | None:
    if value is None:
        return None
    try:
        pct = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(100.0, pct))


def _billing_cycle_end_iso(payload: dict[str, Any]) -> str | None:
    raw = payload.get("billingCycleEnd")
    if raw is None:
        return None
    try:
        # API returns epoch milliseconds as a string (or number).
        ms = int(str(raw).strip())
    except (TypeError, ValueError):
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        return None
    if ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC).isoformat()


def _on_demand_used_percent(spend: dict[str, Any]) -> float | None:
    """Compute on-demand used % of the individual hard limit."""
    limit = spend.get("individualLimit")
    try:
        limit_cents = int(limit) if limit is not None else 0
    except (TypeError, ValueError):
        limit_cents = 0
    if limit_cents <= 0:
        return None

    used = spend.get("individualUsed")
    if used is not None:
        try:
            used_cents = int(used)
        except (TypeError, ValueError):
            used_cents = None
        if used_cents is not None:
            return _clamp_percent((used_cents / limit_cents) * 100.0)

    remaining = spend.get("individualRemaining")
    if remaining is not None:
        try:
            remaining_cents = int(remaining)
        except (TypeError, ValueError):
            return None
        used_cents = max(0, limit_cents - remaining_cents)
        return _clamp_percent((used_cents / limit_cents) * 100.0)

    return None


def _unavailable_bar(key: str, label: str, short_label: str) -> PlanBar:
    return PlanBar(
        key=key,
        label=label,
        short_label=short_label,
        percent=None,
        resets_at=None,
        available=False,
    )


def _bar_or_unavailable(
    *,
    key: str,
    label: str,
    short_label: str,
    percent: float | None,
    resets_at: str | None,
) -> PlanBar:
    if percent is None:
        return _unavailable_bar(key, label, short_label)
    return PlanBar(
        key=key,
        label=label,
        short_label=short_label,
        percent=percent,
        resets_at=resets_at,
        available=True,
    )


def parse_plan_bars(payload: dict[str, Any]) -> list[PlanBar]:
    """Map ``GetCurrentPeriodUsage`` JSON into three plan bars."""
    resets_at = _billing_cycle_end_iso(payload)
    plan = (
        payload.get("planUsage") if isinstance(payload.get("planUsage"), dict) else {}
    )
    spend = (
        payload.get("spendLimitUsage")
        if isinstance(payload.get("spendLimitUsage"), dict)
        else {}
    )

    return [
        _bar_or_unavailable(
            key=_MODELS_KEY,
            label="Cursor Models",
            short_label="Models",
            percent=_clamp_percent(plan.get("autoPercentUsed")),
            resets_at=resets_at,
        ),
        _bar_or_unavailable(
            key=_OTHER_KEY,
            label="Other Models",
            short_label="Other",
            percent=_clamp_percent(plan.get("apiPercentUsed")),
            resets_at=resets_at,
        ),
        _bar_or_unavailable(
            key=_ON_DEMAND_KEY,
            label="On-demand",
            short_label="On-demand",
            percent=_on_demand_used_percent(spend),
            resets_at=resets_at,
        ),
    ]


def fetch_usage_payload(
    client: httpx.Client,
    access_token: str,
) -> dict[str, Any]:
    """POST ``GetCurrentPeriodUsage`` and return the JSON object."""
    resp = client.post(
        _USAGE_URL,
        content=b"{}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
        },
    )
    if resp.status_code in (401, 403):
        raise CursorUsageError(f"usage HTTP {resp.status_code}: {resp.text[:200]}")
    if resp.status_code >= 400:
        raise CursorUsageError(
            f"GetCurrentPeriodUsage HTTP {resp.status_code}: {resp.text[:300]}"
        )
    try:
        data = resp.json()
    except ValueError as exc:
        raise CursorUsageError("GetCurrentPeriodUsage returned non-JSON") from exc
    if not isinstance(data, dict):
        raise CursorUsageError("GetCurrentPeriodUsage JSON root must be an object")
    return data


def fetch_usage_snapshot(
    *,
    timeout: float = 30.0,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Fetch usage JSON, refreshing the access token once on 401/403."""
    tokens = read_auth_tokens(db_path=db_path)
    access = _runtime_access_token or tokens["access"]
    with httpx.Client(timeout=timeout) as client:
        try:
            return fetch_usage_payload(client, access)
        except CursorUsageError as exc:
            message = str(exc)
            if "HTTP 401" not in message and "HTTP 403" not in message:
                raise
            refresh = tokens.get("refresh")
            if not refresh:
                raise CursorUsageError(
                    "Cursor access token rejected and no refresh token available; "
                    "re-sign in to Cursor"
                ) from exc
            access = refresh_access_token(
                refresh, client=client, db_path=db_path, persist=True
            )
            return fetch_usage_payload(client, access)


async def fetch_plan_bars(
    *,
    timeout: float = 30.0,
    db_path: Path | None = None,
) -> list[PlanBar]:
    """Fetch Cursor Models / Other / On-demand plan bars."""
    snapshot = await asyncio.to_thread(
        fetch_usage_snapshot, timeout=timeout, db_path=db_path
    )
    return parse_plan_bars(snapshot)


def _reset_runtime_token_for_tests() -> None:
    """Clear the process-local token override (tests only)."""
    global _runtime_access_token
    _runtime_access_token = None
