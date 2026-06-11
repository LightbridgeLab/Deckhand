# Deckhand

> Tactile Stream Deck / OpenDeck control for Claude Code, Cursor, and your dev shell. Local-first, Python plugins, no cloud.

Deckhand is a local service that watches your AI coding sessions and turns one Stream Deck button into a real action: jump to whichever Claude session needs input, show how many tokens you've burned this week, fire a project-startup macro. It runs on `127.0.0.1`, talks to [OpenDeck](https://github.com/niclasmattsson/OpenDeck) (and soon the official Elgato Stream Deck), and stays out of your way the rest of the time.

It is *not* a generic home-automation hub, a cross-device button platform, or a marketplace. If you're looking for that, [Bitfocus Companion](https://bitfocus.io/companion) or [Touch Portal](https://www.touch-portal.com/) probably fit better.

## Scope (v0.3)

- **macOS-first.** The iTerm focuser uses AppleScript via `osascript`. Linux + Windows ports are possible but unbuilt.
- **OpenDeck-first.** An Elgato Stream Deck plugin port is planned. Until then, OpenDeck is the only client.
- **iTerm-first** for the focus loop. Claude sessions outside iTerm (Terminal.app, Alacritty, plain ssh) are still tracked — they just can't be focused yet.
- **One real provider so far:** Claude Code. Cursor adapter ships in the baseline but the focus integration and usage plugin are Claude-only today. Cursor focus is tracked at [#24](https://github.com/LightbridgeLab/Deckhand/issues/24).

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/LightbridgeLab/Deckhand && cd Deckhand
uv sync --all-extras
cp config.example.toml config.toml      # edit the [plugins] block — see Quick start below
make dev                                 # starts the service on http://127.0.0.1:8000
```

On first start the service auto-generates a write-scoped API key and logs it. Set `[auth] api_keys` in `config.toml` to persist a key you control.

## Quick start: live Claude Code token count on a button

The end state is one Stream Deck button that shows how many tokens you've spent in the last 5 hours, updating live as Claude works.

**1. Enable the usage plugin** in `config.toml`:

```toml
[plugins]
modules = [
  "deckhand.plugins.claude_code_usage",
]
```

Optional — give it caps so the button can show a percentage too:

```toml
[plugins.claude_code_usage]
session_token_cap = 500000
week_token_cap = 10000000
week_sonnet_token_cap = 5000000
```

**2. Install the Claude Code hooks** so Deckhand can see your sessions:

```bash
# Merge examples/claude_code_hooks.json into ~/.claude/settings.json
# (the "hooks" block; existing hooks are preserved).
```

In your shell profile, export the Deckhand URL and the API key from `config.toml`:

```bash
export DECKHAND_URL=http://127.0.0.1:8000
export DECKHAND_API_KEY=<your-key>
```

The hook commands also forward `$ITERM_SESSION_ID` automatically — that's what enables the focus button later.

**3. Install OpenDeck and the Deckhand plugin:**

```bash
# macOS
cp -r opendeck-plugin/com.deckhand.plugin.sdPlugin \
  ~/Library/Application\ Support/OpenDeck/Plugins/

# Linux
cp -r opendeck-plugin/com.deckhand.plugin.sdPlugin \
  ~/.config/OpenDeck/Plugins/
```

The plugin reads its `DECKHAND_URL` and `DECKHAND_API_KEY` from the same `config.toml` the service uses — put them under a `[client]` section. If you don't have a service checkout (OpenDeck-plugin-only install), put the file at `~/.config/deckhand/config.toml`; the service and the plugin both look there as a fallback. See `config.example.toml` for the section shape. The `DECKHAND_URL` / `DECKHAND_API_KEY` env vars override the file if you'd rather set them at the shell level.

**4. Restart OpenDeck.** A "Deckhand" category appears in the action list.

**5. Bind a Data Widget to a button:**

- Drag **Data Widget** onto a button.
- In the Property Inspector, set the state key to `usage.claude_code.session_tokens` and the display format to `number` (or `percentage` if you set caps in step 1).
- Open Claude Code in iTerm and start chatting. Within 30 seconds the button updates with your real token count.

That's the full loop: install → enable one plugin → install hooks → bind one button.

## Features

### Live usage widgets — `usage.claude_code.*`

The `claude_code_usage` plugin polls `~/.claude/projects/**/*.jsonl` and publishes three state keys, each with the shape `{ label, current, max, percent, unit, updated_at }`:

| state key | window | model filter |
|---|---|---|
| `usage.claude_code.session_tokens` | last 5 hours | all |
| `usage.claude_code.week_tokens` | last 7 days | all |
| `usage.claude_code.week_sonnet_tokens` | last 7 days | Sonnet only |

Bind any of them to a Data Widget button. `max` and `percent` stay `null` unless you configure caps in `config.toml` — Anthropic's actual cap numbers aren't recorded anywhere on disk, so the plugin can compute totals authoritatively but only your configuration knows the denominator. Token counting is `input + cache_creation + output` (cache reads excluded). See the module docstring for the full set of heuristics.

### Pending-input focus

While the hooks are running, two state keys aggregate "needs input" across every local Claude Code session:

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

`make dev` starts the service. In another shell, the `deckhand` CLI talks to it over the same HTTP/WebSocket API as the OpenDeck plugin:

```bash
uv run deckhand --help
uv run deckhand state list
uv run deckhand state watch usage.claude_code.session_tokens
uv run deckhand events tail --type agent.status_changed --type state.changed
uv run deckhand actions list
uv run deckhand actions call agents.focus_next_pending
uv run deckhand agents list
cat examples/claude_code_hooks.json | jq '.hooks.SessionStart[0]' | uv run deckhand hooks simulate claude-code
```

Connection settings come from `--url` / `--api-key`, then `DECKHAND_URL` / `DECKHAND_API_KEY`, then `config.toml`. The on-disk event log is opt-in; turn it on with `[event_log] enabled = true` to enable `deckhand events tail --from-log`.

## Configuration

`config.toml` is the source of truth. Environment variables override individual keys:

| Setting | Env var | Default |
|---|---|---|
| Listen host | `DECKHAND_HOST` | `127.0.0.1` |
| Listen port | `DECKHAND_PORT` | `8000` |
| API key | `DECKHAND_API_KEY` | auto-generated write key (logged at startup) |
| Plugin modules | `DECKHAND_PLUGINS` | none (opt in via `config.toml`) |
| State persistence file | `DECKHAND_STATE_FILE` | none (in-memory) |
| Event log | `DECKHAND_EVENT_LOG_ENABLED` / `DECKHAND_EVENT_LOG` | off; `.deckhand/events.log` |
| Config file path | `DECKHAND_CONFIG_FILE` | `./config.toml`, then `~/.config/deckhand/config.toml` |

`config.example.toml` is the annotated reference for every section.

## Documentation

- **[OpenDeck plugin internals](opendeck-plugin/README.md)** — install + develop the bridge.
- **[Plugin Guide](docs/PLUGIN_GUIDE.md)** — write your own action / signal / state plugin.
- **[Cursor Stream Deck profiles](docs/CURSOR_STREAM_DECK_PROFILES.md)** — layout patterns for Cursor sessions.
- **[API Reference](docs/API.md)** — HTTP routes.
- **[Event Schema](docs/EVENTS.md)** — event types and payload shapes.

## Run the tests

```bash
make check         # ruff lint + format + pytest, currently 196 passing
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
