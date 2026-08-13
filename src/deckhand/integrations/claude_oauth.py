"""Read Claude Code OAuth credentials and fetch plan usage bars.

Claude Code stores OAuth tokens in the macOS Keychain under the service
``Claude Code-credentials``. The live ``/usage`` percentages come from
``GET https://api.anthropic.com/api/oauth/usage`` — the same endpoint the
CLI uses. Absolute token caps are never returned; utilization is already a
0–100 percentage.

Refresh uses ``POST https://platform.claude.com/v1/oauth/token`` with the
public Claude Code client id. Refreshed tokens are written back to the
Keychain only after both access and refresh tokens validate as non-empty,
so a failed refresh cannot wipe a working login.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass
from typing import Any

import httpx

from deckhand.integrations.usage_metrics import parse_retry_after_seconds

logger = logging.getLogger(__name__)

_KEYCHAIN_SERVICE = "Claude Code-credentials"
_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
# Public Claude Code OAuth client id (token_endpoint_auth_method: none).
_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
_USER_AGENT = "claude-cli/2.1.220 (external, deckhand)"
# Refresh when fewer than this many ms remain on the access token.
_REFRESH_SKEW_MS = 5 * 60 * 1000


class ClaudeOAuthError(RuntimeError):
    """Raised when credentials are missing or the usage API rejects us."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


@dataclass(frozen=True)
class PlanBar:
    """One Claude ``/usage`` bar ready for the state store."""

    key: str
    label: str
    short_label: str
    percent: float | None
    resets_at: str | None
    available: bool


def read_keychain_credentials() -> dict[str, Any]:
    """Return the full Keychain JSON blob for Claude Code credentials."""
    try:
        raw = subprocess.check_output(
            ["security", "find-generic-password", "-s", _KEYCHAIN_SERVICE, "-w"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise ClaudeOAuthError(
            "Claude Code credentials not found in Keychain; run `claude auth login`"
        ) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ClaudeOAuthError("Claude Code Keychain entry is not valid JSON") from exc
    if not isinstance(data, dict):
        raise ClaudeOAuthError("Claude Code Keychain entry has unexpected shape")
    return data


def _oauth_section(cred: dict[str, Any]) -> dict[str, Any]:
    section = cred.get("claudeAiOauth")
    if not isinstance(section, dict):
        raise ClaudeOAuthError("Keychain entry missing claudeAiOauth")
    return section


def _access_token(oauth: dict[str, Any]) -> str:
    token = oauth.get("accessToken")
    if not isinstance(token, str) or not token.strip():
        raise ClaudeOAuthError(
            "Claude Code access token empty; run `claude auth login`"
        )
    return token


def _needs_refresh(oauth: dict[str, Any]) -> bool:
    expires_at = oauth.get("expiresAt")
    if not isinstance(expires_at, (int, float)) or expires_at <= 0:
        return False
    return expires_at <= time.time() * 1000 + _REFRESH_SKEW_MS


def _keychain_account() -> str:
    """Best-effort account name for the Claude Code Keychain item."""
    try:
        dump = subprocess.check_output(
            ["security", "find-generic-password", "-s", _KEYCHAIN_SERVICE],
            stderr=subprocess.STDOUT,
            text=True,
        )
    except subprocess.CalledProcessError:
        return "Claude Code"
    for line in dump.splitlines():
        if '"acct"' in line and '="' in line:
            start = line.index('="') + 2
            end = line.rfind('"')
            if end > start:
                return line[start:end]
    return "Claude Code"


def write_keychain_credentials(cred: dict[str, Any]) -> None:
    """Overwrite the Claude Code Keychain item. Caller must validate tokens."""
    oauth = _oauth_section(cred)
    access = oauth.get("accessToken")
    refresh = oauth.get("refreshToken")
    if not (isinstance(access, str) and access.strip()):
        raise ClaudeOAuthError("refusing to write empty accessToken to Keychain")
    if not (isinstance(refresh, str) and refresh.strip()):
        raise ClaudeOAuthError("refusing to write empty refreshToken to Keychain")

    payload = json.dumps(cred, separators=(",", ":"))
    account = _keychain_account()
    # Replace atomically: delete then add. `-U` alone can leave empty values
    # when the account attribute mismatches.
    subprocess.run(
        ["security", "delete-generic-password", "-s", _KEYCHAIN_SERVICE, "-a", account],
        capture_output=True,
        check=False,
    )
    proc = subprocess.run(
        [
            "security",
            "add-generic-password",
            "-s",
            _KEYCHAIN_SERVICE,
            "-a",
            account,
            "-w",
            payload,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise ClaudeOAuthError(
            f"failed to write Keychain credentials: {proc.stderr.strip() or proc.returncode}"
        )


async def refresh_oauth_token(
    client: httpx.AsyncClient, cred: dict[str, Any]
) -> dict[str, Any]:
    """Refresh the access token and return an updated credentials dict."""
    oauth = dict(_oauth_section(cred))
    refresh = oauth.get("refreshToken")
    if not isinstance(refresh, str) or not refresh.strip():
        raise ClaudeOAuthError("no refresh token; run `claude auth login`")

    response = await client.post(
        _TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": _CLIENT_ID,
        },
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
        },
    )
    if response.status_code >= 400:
        raise ClaudeOAuthError(
            f"token refresh failed HTTP {response.status_code}: {response.text[:200]}"
        )
    data = response.json()
    access = data.get("access_token")
    new_refresh = data.get("refresh_token")
    expires_in = data.get("expires_in")
    if not (isinstance(access, str) and access.strip()):
        raise ClaudeOAuthError("token refresh returned empty access_token")
    if not (isinstance(new_refresh, str) and new_refresh.strip()):
        raise ClaudeOAuthError("token refresh returned empty refresh_token")
    if not isinstance(expires_in, (int, float)) or expires_in <= 0:
        raise ClaudeOAuthError("token refresh missing expires_in")

    oauth["accessToken"] = access
    oauth["refreshToken"] = new_refresh
    oauth["expiresAt"] = int(time.time() * 1000) + int(expires_in) * 1000
    refresh_expires_in = data.get("refresh_token_expires_in")
    if isinstance(refresh_expires_in, (int, float)) and refresh_expires_in > 0:
        oauth["refreshTokenExpiresAt"] = (
            int(time.time() * 1000) + int(refresh_expires_in) * 1000
        )
    scope = data.get("scope")
    if isinstance(scope, str) and scope.strip():
        oauth["scopes"] = scope.split()

    updated = dict(cred)
    updated["claudeAiOauth"] = oauth
    return updated


async def ensure_access_token(client: httpx.AsyncClient) -> str:
    """Return a usable access token, refreshing + writing Keychain if needed."""
    cred = read_keychain_credentials()
    oauth = _oauth_section(cred)
    if _needs_refresh(oauth):
        logger.info("Claude Code access token near expiry; refreshing")
        cred = await refresh_oauth_token(client, cred)
        write_keychain_credentials(cred)
        oauth = _oauth_section(cred)
    return _access_token(oauth)


def _utilization_percent(value: Any) -> float | None:
    """Normalize API utilization to a 0–100 float.

    Observed responses already use 0–100. Guard against a future 0–1 scale.
    """
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if 0.0 <= num <= 1.0 and num not in (0.0, 1.0):
        # Ambiguous for exactly 0 and 1; treat mid-range fractions as 0–1.
        return num * 100.0
    return num


def parse_plan_bars(payload: dict[str, Any]) -> list[PlanBar]:
    """Map ``/api/oauth/usage`` JSON into the four Deckhand plan bars."""
    five = (
        payload.get("five_hour") if isinstance(payload.get("five_hour"), dict) else {}
    )
    week = (
        payload.get("seven_day") if isinstance(payload.get("seven_day"), dict) else {}
    )
    extra = (
        payload.get("extra_usage")
        if isinstance(payload.get("extra_usage"), dict)
        else {}
    )

    fable_percent: float | None = None
    fable_resets: str | None = None
    fable_available = False
    limits = payload.get("limits")
    if isinstance(limits, list):
        for item in limits:
            if not isinstance(item, dict):
                continue
            if item.get("kind") != "weekly_scoped":
                continue
            scope = item.get("scope") if isinstance(item.get("scope"), dict) else {}
            model = scope.get("model") if isinstance(scope.get("model"), dict) else {}
            display = str(model.get("display_name") or "")
            if "fable" not in display.lower():
                continue
            fable_available = True
            raw_pct = item.get("percent")
            if raw_pct is None:
                raw_pct = item.get("utilization")
            fable_percent = _utilization_percent(raw_pct)
            resets = item.get("resets_at")
            fable_resets = resets if isinstance(resets, str) else None
            break

    credits_enabled = bool(extra.get("is_enabled")) and not bool(
        extra.get("user_disabled")
    )
    credits_percent = (
        _utilization_percent(extra.get("utilization")) if credits_enabled else None
    )
    # Prefer spend.percent when present and credits enabled.
    spend = payload.get("spend") if isinstance(payload.get("spend"), dict) else {}
    if credits_enabled and spend.get("percent") is not None:
        credits_percent = _utilization_percent(spend.get("percent"))

    return [
        PlanBar(
            key="usage.claude_code.session",
            label="Current session",
            short_label="Session",
            percent=_utilization_percent(five.get("utilization")),
            resets_at=five.get("resets_at")
            if isinstance(five.get("resets_at"), str)
            else None,
            available=bool(five),
        ),
        PlanBar(
            key="usage.claude_code.week",
            label="Current week (all models)",
            short_label="Week",
            percent=_utilization_percent(week.get("utilization")),
            resets_at=week.get("resets_at")
            if isinstance(week.get("resets_at"), str)
            else None,
            available=bool(week),
        ),
        PlanBar(
            key="usage.claude_code.week_fable",
            label="Current week (Fable)",
            short_label="Fable",
            percent=fable_percent,
            resets_at=fable_resets,
            available=fable_available,
        ),
        PlanBar(
            key="usage.claude_code.credits",
            label="Usage credits",
            short_label="Credits",
            percent=credits_percent,
            resets_at=None,
            available=credits_enabled,
        ),
    ]


async def fetch_usage_payload(
    client: httpx.AsyncClient, access_token: str
) -> dict[str, Any]:
    """GET ``/api/oauth/usage`` and return the JSON body."""
    response = await client.get(
        _USAGE_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
        },
    )
    if response.status_code >= 400:
        retry_after = parse_retry_after_seconds(response.headers.get("Retry-After"))
        if response.status_code == 401:
            raise ClaudeOAuthError(
                "usage API returned 401; run `claude auth login`",
                status_code=401,
            )
        raise ClaudeOAuthError(
            f"usage API HTTP {response.status_code}: {response.text[:200]}",
            status_code=response.status_code,
            retry_after=retry_after,
        )
    data = response.json()
    if not isinstance(data, dict):
        raise ClaudeOAuthError("usage API returned non-object JSON")
    return data


async def fetch_plan_bars(client: httpx.AsyncClient | None = None) -> list[PlanBar]:
    """Convenience: ensure token, fetch usage, parse bars."""
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=15.0)
    try:
        token = await ensure_access_token(client)
        try:
            payload = await fetch_usage_payload(client, token)
        except ClaudeOAuthError as exc:
            if exc.status_code != 401:
                raise
            # One refresh retry on auth failure.
            cred = read_keychain_credentials()
            cred = await refresh_oauth_token(client, cred)
            write_keychain_credentials(cred)
            token = _access_token(_oauth_section(cred))
            payload = await fetch_usage_payload(client, token)
        return parse_plan_bars(payload)
    finally:
        if owns_client:
            await client.aclose()
