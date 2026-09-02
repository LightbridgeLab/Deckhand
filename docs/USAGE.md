# Usage widgets

Usage plugins publish percentage bars as state keys. Bind a **Data Widget** with display format `percentage` (or `summary`). Each entry looks like:

```json
{
  "label": "Session",
  "short_label": "36%",
  "current": 36,
  "max": 100,
  "percent": 36,
  "unit": "%",
  "resets_at": "2026-09-02T03:00:00Z",
  "updated_at": 1234567890.0,
  "title": "Session\n36%"
}
```

**`percent` is used % (0–100)** for every provider. `title` is the two-line face (`Session` / `36%`).

## Enable plugins

Add the providers you use under `[plugins].modules` in `config.toml`:

```toml
[plugins]
modules = [
  "deckhand.plugins.claude_code_usage",
  "deckhand.plugins.antigravity_usage",
  "deckhand.plugins.cursor_usage",
]
```

Seed the Property Inspector dropdown from `config.example.toml` `[catalog.state_keys]`, or run `uv run deckhand catalog sync`.

## Claude Code — `usage.claude_code.*`

Polls Anthropic `GET /api/oauth/usage` with the Claude Code Keychain OAuth token (same source as `/usage` in the CLI). Requires `claude auth login` on this Mac.

| State key | Claude `/usage` bar |
|-----------|---------------------|
| `usage.claude_code.session` | Current session |
| `usage.claude_code.week` | Current week (all models) |
| `usage.claude_code.week_fable` | Current week (Fable), when your plan has that bar |
| `usage.claude_code.credits` | Usage credits, when enabled |

## Antigravity — `usage.antigravity.*`

Reads the `agy` OAuth token from the macOS Keychain and polls Google Cloud Code `retrieveUserQuotaSummary` — same source as the `/usage` panel. Requires `agy` signed in on this Mac.

| State key | `agy` `/usage` bar |
|-----------|-------------------|
| `usage.antigravity.session` | Gemini five-hour limit (used %) |
| `usage.antigravity.week` | Gemini weekly limit (used %) |

## Cursor — `usage.cursor.*`

Reads the Cursor IDE access JWT from `state.vscdb` and polls `GetCurrentPeriodUsage` on `api2.cursor.sh` — same source as [cursor.com/dashboard/spending](https://cursor.com/dashboard/spending). Requires Cursor signed in on this machine.

| State key | Spending dashboard |
|-----------|-------------------|
| `usage.cursor.models` | Cursor Models pool (used %) |
| `usage.cursor.other` | Other Models pool (used %) |
| `usage.cursor.on_demand` | On-demand spend vs hard limit (used %) |

## Button behavior

- **Display format** `percentage` draws the two-line `title`. Keep `button_title` in the catalog short (~6 characters) so it fits the key.
- **On press** default is `peek`: briefly flash time-until-reset when `resets_at` is set. Duration: `[client].usage_reset_flash_seconds` (default 5; `0` disables).
- **Provider image** — set `image` in the catalog to `claude`, `cursor`, `antigravity`, or `blank`.

## Pending-input indicators

Separate from usage bars. With session hooks installed:

| State key | Value | Use |
|-----------|-------|-----|
| `agents.pending_input_count` | `{ "count": N }` | Numeric Data Widget |
| `agents.pending_input` | `{ "agent_ids": [...] }` | Advanced |

Bind **Run Action** to `agents.focus_next_pending` to cycle focus through sessions waiting on input (iTerm / Cursor where supported).

## Historical cost analytics

Deckhand publishes live plan bars only. For historical burn across many CLIs, use companions such as [ccusage](https://ccusage.com/), [CodexBar](https://github.com/steipete/CodexBar), or [caut](https://github.com/Dicklesworthstone/coding_agent_usage_tracker).

Local Claude JSONL token totals (`usage.claude_code.session_tokens` and related keys) were removed in favor of OAuth plan bars.
