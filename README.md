# Deckhand

> Tactile Stream Deck / OpenDeck control for Claude Code, Cursor, and your dev shell. Local-first, Python plugins, no cloud.

Deckhand is a local service that watches your AI coding sessions and turns one Stream Deck button into a real action: jump to whichever Claude session needs input, show live plan usage, fire a project-startup macro. It runs on `127.0.0.1`, talks to [OpenDeck](https://github.com/niclasmattsson/OpenDeck) (and soon the official Elgato Stream Deck), and stays out of your way the rest of the time.

It is *not* a generic home-automation hub, a cross-device button platform, or a marketplace. If you're looking for that, [Bitfocus Companion](https://bitfocus.io/companion) or [Touch Portal](https://www.touch-portal.com/) probably fit better.

## Scope (v0.3)

- **macOS-first.** The iTerm focuser uses AppleScript via `osascript`. Linux + Windows ports are possible but unbuilt.
- **OpenDeck-first.** An Elgato Stream Deck plugin port is planned. Until then, OpenDeck is the only client.
- **iTerm-first** for the focus loop. Claude sessions outside iTerm (Terminal.app, Alacritty, plain ssh) are still tracked — they just can't be focused yet.
- **Usage adapters today:** Claude Code (in-process OAuth plan bars), Antigravity (in-process `agy` Keychain OAuth → Gemini session/week), and Cursor (local IDE JWT → Spending dashboard pools). Cursor focus is tracked at [#24](https://github.com/LightbridgeLab/Deckhand/issues/24).

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/LightbridgeLab/Deckhand && cd Deckhand
uv sync --all-extras
make config                              # copies config.example.toml → config.toml if missing
# edit the [plugins] block — see Quick start below
make dev                                 # foreground + hot reload on http://127.0.0.1:18765
# or: make start / make stop / make status   # background server (PID + log under .deckhand/)
```

On first start the service auto-generates a write-scoped API key and logs it. Set `[auth] api_keys` in `config.toml` to persist a key you control.

## Quick start: live Claude Code plan usage on a button

The end state is one Stream Deck button that shows your Claude `/usage` session percentage, updating live as you work. **Usage widgets do not need session hooks** — that is a separate loop (see below).

**1. Enable the usage plugin** in `config.toml`:

```toml
[plugins]
modules = [
  "deckhand.plugins.claude_code_usage",
]
```

**2. Install OpenDeck and the Deckhand plugin:**

```bash
# macOS
cp -r opendeck-plugin/com.deckhand.plugin.sdPlugin \
  ~/Library/Application\ Support/OpenDeck/Plugins/

# Linux
cp -r opendeck-plugin/com.deckhand.plugin.sdPlugin \
  ~/.config/OpenDeck/Plugins/
```

The plugin reads its `DECKHAND_URL` and `DECKHAND_API_KEY` from the same `config.toml` the service uses — put them under a `[client]` section. If you don't have a service checkout (OpenDeck-plugin-only install), put the file at `~/.config/deckhand/config.toml`; the service and the plugin both look there as a fallback. See `config.example.toml` for the section shape. The `DECKHAND_URL` / `DECKHAND_API_KEY` env vars override the file if you'd rather set them at the shell level.

While Core is running it also writes `~/.config/deckhand/runtime.toml` with the URL it actually bound. Clients prefer that file over a stale `[client] url` or leftover `deckhand.env`, so changing `[service] port` and restarting Core is enough — you do not have to edit the OpenDeck install. After Core exits, clients fall back to `config.toml`.

**3. Restart OpenDeck.** A "Deckhand" category appears in the action list.

**4. Bind a Data Widget to a button:**

- Drag **Data Widget** onto a button.
- In the Property Inspector, pick a state key from the dropdown (from `[catalog.state_keys]` in `config.toml`, sorted by `dropdown_label`). Catalog rows can include a suggested `format` and `button_title`; selecting a key auto-fills Display Format and Button title (you can still override). For usage bars use `percentage` (two-line title like `Session` / `36%`). Keep `button_title` short (~6 characters) so it fits the key.
- If the dropdown is empty, copy the `[catalog.state_keys]` block from `config.example.toml`, or run `deckhand catalog sync`, then click **Refresh**.
- Stay signed in with Claude Code (`claude auth login`). Within ~60 seconds the button updates from Anthropic's live `/usage` endpoint.

That's the usage loop: enable one plugin → bind a Data Widget.

## Quick start: Agent Status (live sessions)

Agent Status pins one **live session**. Sessions appear only after a coding agent pings Deckhand — open IDE windows alone are not listed.

```bash
uv run deckhand hooks install   # Claude Code + Cursor (writes an absolute deckhand path, no curl/jq)
# start a session in that tool, then:
uv run deckhand agents list     # or Refresh on the Property Inspector
# optional: try the button without IDE hooks
uv run deckhand agents demo
```

Diagnose with `uv run deckhand hooks status`. Full story (Codex / Antigravity register examples, contract for other tools): [docs/SESSION_HOOKS.md](docs/SESSION_HOOKS.md).

Then drag **Agent Status** onto a button and pick the session from the dropdown.

## Features

### Live usage widgets — plan bars

Usage plugins publish percentage bars as `{ label, short_label, current, max, percent, unit, resets_at, updated_at, title }` with `title` like `Session\n36%`. Bind Data Widgets with display format `percentage` (or `summary`). **`percent` is used % (0–100)** for every provider.

**Breaking change:** local Claude JSONL token totals (`usage.claude_code.session_tokens` / `.week_tokens` / `.week_sonnet_tokens`) were removed. Use Claude OAuth plan bars below, or a companion CLI such as [ccusage](https://ccusage.com/) for historical burn analytics.

#### Claude Code — `usage.claude_code.*`

The `claude_code_usage` plugin polls Anthropic `GET /api/oauth/usage` with the Claude Code Keychain OAuth token (same source as `/usage` in the CLI):

| state key | Claude `/usage` bar |
|---|---|
| `usage.claude_code.session` | Current session |
| `usage.claude_code.week` | Current week (all models) |
| `usage.claude_code.week_fable` | Current week (Fable), when your plan has that bar |
| `usage.claude_code.credits` | Usage credits, when enabled |

Requires `claude auth login` on this Mac.

#### Antigravity — `usage.antigravity.*`

The `antigravity_usage` plugin reads the `agy` OAuth token from the macOS Keychain (same credentials as the `/usage` panel) and polls Google Cloud Code `retrieveUserQuotaSummary` in-process — no extra CLI install.

Requires `agy` signed in on this Mac.

| state key | `agy` `/usage` bar |
|---|---|
| `usage.antigravity.session` | Gemini five-hour limit (used %) |
| `usage.antigravity.week` | Gemini weekly limit (used %) |

#### Cursor — `usage.cursor.*`

The `cursor_usage` plugin reads the Cursor IDE access JWT from `state.vscdb` and polls `GetCurrentPeriodUsage` on `api2.cursor.sh` — the same source as [cursor.com/dashboard/spending](https://cursor.com/dashboard/spending).

Requires Cursor signed in on this machine. Enable in `config.toml`:

```toml
[plugins]
modules = [
  "deckhand.plugins.claude_code_usage",
  "deckhand.plugins.antigravity_usage",
  "deckhand.plugins.cursor_usage",
]
```

| state key | Spending dashboard |
|---|---|
| `usage.cursor.models` | Cursor Models pool (used %) |
| `usage.cursor.other` | Other Models pool (used %) |
| `usage.cursor.on_demand` | On-demand spend vs hard limit (used %) |

Bind the same way as Claude (`percentage`). Press a usage button to briefly flash time-until-reset (`Xd Yh` or `Xh Ym`); duration is `[client].usage_reset_flash_seconds` (default 5).

### Usage widgets roadmap

| Status | Surface |
|---|---|
| Shipped | Claude OAuth plan bars |
| Shipped | Antigravity in-process OAuth (Gemini session/week) |
| Shipped | Cursor Spending adapter → `usage.cursor.*` ([#40](https://github.com/LightbridgeLab/Deckhand/issues/40)) |
| Non-goals | Multi-provider federation, caut/CodexBar as a submodule, local JSONL/ccusage burn analytics inside Deckhand |

For historical cost dashboards across many CLIs, use companions such as [CodexBar](https://github.com/steipete/CodexBar), [caut](https://github.com/Dicklesworthstone/coding_agent_usage_tracker), or [ccusage](https://ccusage.com/) — Deckhand stays a Stream Deck state publisher for the tools you bind buttons to.

### Pending-input focus

While session hooks are running, two state keys aggregate "needs input" across tracked sessions:

- `agents.pending_input_count` → `{ "count": N }` for a numeric Data Widget
- `agents.pending_input` → `{ "agent_ids": [...] }` (oldest first) for advanced use

Bind a **Run Action** button to `agents.focus_next_pending` (no payload). On press it pops the oldest pending session and brings iTerm to that tab. Press again to jump to the next. Empty queue → no-op success.

Sessions outside iTerm still appear in the count but the focus action skips them. Cursor focus and browser focus are tracked at [#24](https://github.com/LightbridgeLab/Deckhand/issues/24) and [#25](https://github.com/LightbridgeLab/Deckhand/issues/25).

### Macros — coming soon

A button that opens iTerm tabs, runs `claude`, and fires a `/status` slash command in one press. Tracked at [#26](https://github.com/LightbridgeLab/Deckhand/issues/26). Not shipped yet.

## OpenDeck plugin

Six actions install with the plugin. Drag them onto buttons from the Deckhand category:

| Action | What it does |
|---|---|
| **Data Widget** | Display a live state value (numeric, percentage, boolean, text). |
| **Run Action** | Execute any Deckhand action on press (e.g. `agents.focus_next_pending`). |
| **Signal Trigger** | Fire a Deckhand signal on press. |
| **Agent Status** | Monitor + start/cancel/input a specific agent. |
| **Agent Slot** | Dynamic slot bound to a priority-ranked agent. Useful when you want a fixed button that always shows the most attention-worthy session. |
| **Agent Dashboard** | One-button summary of every tracked agent (counts by status, focuses attention on press). |

See [opendeck-plugin/README.md](opendeck-plugin/README.md) for property-inspector internals.

## CLI

`make dev` (or `make start` for background) starts the service. In another shell, the `deckhand` CLI talks to it over the same HTTP/WebSocket API as the OpenDeck plugin:

```bash
uv run deckhand --help
uv run deckhand state list
uv run deckhand state watch usage.claude_code.session
uv run deckhand events tail --type agent.status_changed --type state.changed
uv run deckhand actions list
uv run deckhand actions call agents.focus_next_pending
uv run deckhand catalog list
make catalog-sync                        # live merge if Core is up; else --no-live seeds
uv run deckhand catalog sync             # same, via CLI
uv run deckhand agents list
uv run deckhand hooks install
uv run deckhand hooks status
uv run deckhand agents demo
echo '{"session_id":"abcdef0123456789","hook_event_name":"SessionStart","cwd":"/tmp"}' \
  | uv run deckhand hooks simulate claude-code
```

Connection settings come from `--url` / `--api-key`, then `DECKHAND_URL` / `DECKHAND_API_KEY`, then the live runtime file (if Core is up), then `config.toml`. The on-disk event log is opt-in; turn it on with `[event_log] enabled = true` to enable `deckhand events tail --from-log`.

`deckhand catalog sync` merges curated first-party keys (based on enabled plugins) and live `GET /state` keys into `[catalog.state_keys]` without overwriting `dropdown_label` / `image` / `format` / `button_title` you already set. The OpenDeck Data Widget dropdown reads that section from the same `config.toml` when it can see the file; if OpenDeck's working directory cannot (common for the Plugins install), the plugin falls back to `GET /catalog/state_keys` on the running Core service.

## Configuration

`config.toml` is the source of truth. Environment variables override individual keys:

| Setting | Env var | Default |
|---|---|---|
| Listen host | `DECKHAND_HOST` | `127.0.0.1` |
| Listen port | `DECKHAND_PORT` | `18765` |
| Live client URL file | `DECKHAND_RUNTIME_FILE` | `~/.config/deckhand/runtime.toml` |
| API key | `DECKHAND_API_KEY` | auto-generated write key (logged at startup) |
| Plugin modules | `DECKHAND_PLUGINS` | none (opt in via `config.toml`) |
| State persistence file | `DECKHAND_STATE_FILE` | none (in-memory) |
| Event log | `DECKHAND_EVENT_LOG_ENABLED` / `DECKHAND_EVENT_LOG` | off; `.deckhand/events.log` |
| Config file path | `DECKHAND_CONFIG_FILE` | `./config.toml`, then `~/.config/deckhand/config.toml` |

`config.example.toml` is the annotated reference for every section.

## Documentation

- **[Session hooks](docs/SESSION_HOOKS.md)** — live agents on Stream Deck (install, verify, other-agent examples).
- **[OpenDeck plugin internals](opendeck-plugin/README.md)** — install + develop the bridge.
- **[Plugin Guide](docs/PLUGIN_GUIDE.md)** — write your own action / signal / state plugin.
- **[Cursor Stream Deck profiles](docs/CURSOR_STREAM_DECK_PROFILES.md)** — layout patterns for Cursor sessions.
- **[API Reference](docs/API.md)** — HTTP routes.
- **[Event Schema](docs/EVENTS.md)** — event types and payload shapes.

## Run the tests

```bash
make check         # ruff lint + format + pytest, currently 213 passing
```

## Roadmap

The shipped feature surface is small by design. Tracked work:

- [#24](https://github.com/LightbridgeLab/Deckhand/issues/24) — Cursor focus (blocked on Cursor exposing more session metadata).
- [#25](https://github.com/LightbridgeLab/Deckhand/issues/25) — Browser-tab focus for Claude / Gemini web.
- [#26](https://github.com/LightbridgeLab/Deckhand/issues/26) — Macro runner with iTerm primitives.
- [#22](https://github.com/LightbridgeLab/Deckhand/issues/22) — Progress-ring image format for usage buttons.
- [#28](https://github.com/LightbridgeLab/Deckhand/issues/28) — Hero screenshots + demo video.

## License

[TBD]
