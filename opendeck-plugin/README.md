# Deckhand OpenDeck Plugin

An [OpenDeck](https://github.com/niclasmattsson/OpenDeck) plugin that bridges Stream Deck hardware to the Deckhand orchestration service.

## Prerequisites

- [OpenDeck](https://github.com/niclasmattsson/OpenDeck) installed and running
- [Deckhand Core](../README.md) running on `http://127.0.0.1:18765`
- Python 3.11+ (used by `run.sh` to bootstrap a plugin-local venv)

## Installation

```bash
# from the Deckhand repo root:
make opendeck-plugin-install

# or manually:
# macOS
cp -r opendeck-plugin/com.deckhand.plugin.sdPlugin \
  ~/Library/Application\ Support/OpenDeck/Plugins/
```

Configure auth in `~/.config/deckhand/config.toml`:

```toml
[client]
url = "http://127.0.0.1:18765"
api_key = "your-write-key"   # same value as one of [auth].api_keys
```

While Core is running, `~/.config/deckhand/runtime.toml` (the bound URL) wins over a stale `[client] url`. Restart OpenDeck after install.

A **Deckhand** category appears with six actions:

| Action | Purpose |
|--------|---------|
| **Agent Status** | Monitor and interact with one session |
| **Agent Slot** | Dynamic slot bound to a priority-ranked session |
| **Agent Dashboard** | Summary of all sessions; press to focus attention |
| **Data Widget** | Display live state on a button |
| **Run Action** | Execute any Deckhand action on press |
| **Signal Trigger** | Fire a Deckhand signal on press |

**Settings schema:** [`docs/opendeck-action-settings.json`](../docs/opendeck-action-settings.json) — update when adding Property Inspector fields.

## Actions (summary)

### Data Widget

Displays a Deckhand state key on the button face. Updates in real time via WebSocket.

- State key from `[catalog.state_keys]` in `config.toml` (or Core `GET /catalog/state_keys`)
- Display formats: `raw`, `percentage`, `boolean`, `number`, `summary`, `currency`
- On press: `peek` (flash time-until-reset), `action`, `both`, or `none`
- Until Core publishes the key, the button shows `—`. A 404 from `GET /state/{key}` on appear is expected (catalog ≠ live store); see [USAGE.md](../docs/USAGE.md#catalog-vs-live-values).

See [USAGE.md](../docs/USAGE.md) for plan-bar keys.

### Agent Status

Monitors one live session. Status drives image, title, and optional macOS alert sound.

**Prerequisite:** Session must ping Core — `uv run deckhand hooks install`, then start Claude Code or Cursor. Or `uv run deckhand agents demo` to try without hooks.

**Press:** idle → start; running → cancel; awaiting input → focus; error → restart.

### Agent Slot

Fixed slot index bound to the Nth session of a filter (`cursor`, `claude_code`, `*`). Press focuses Cursor agents or start/cancel/input for others.

### Agent Dashboard

Compact summary (counts by status). Press focuses the highest-priority session needing attention.

### Run Action / Signal Trigger

Execute a fixed Deckhand action or fire a signal on press. Discover names via `deckhand actions list` / `deckhand signals list`.

Example Run Action: `agents.focus_next_pending` with empty payload.

## Development

Start Core: `make dev` from the repo root.

Run the plugin outside OpenDeck (for testing):

```bash
cd com.deckhand.plugin.sdPlugin
export DECKHAND_URL=http://127.0.0.1:18765
export DECKHAND_API_KEY=<your-key>
./run.sh -port 28196 -pluginUUID test -registerEvent registerPlugin -info '{}'
```

Run plugin tests:

```bash
uv run pytest opendeck-plugin/tests/ -v --asyncio-mode=auto
```

To add a new action: create a handler in `actions/`, register in `plugin.py`, add to `manifest.json`, update `docs/opendeck-action-settings.json`.
