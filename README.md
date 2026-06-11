# Deckhand

Deckhand is a local-first orchestration service for Stream Deck hardware. It pairs with [OpenDeck](https://github.com/niclasmattsson/OpenDeck) — OpenDeck handles hardware, buttons, and profiles; Deckhand adds agent monitoring, live data widgets, and signal-driven automation.

## Install

**Prerequisites:** Python 3.11+, [uv](https://docs.astral.sh/uv/) (recommended) or pip.

```bash
git clone <this-repo> && cd Deckhand
uv sync --all-extras   # installs all dependencies into .venv
```

<details><summary>pip alternative</summary>

```bash
pip install -e ".[test]"
```
</details>

## Quick start (no Stream Deck needed)

You can try Deckhand without any hardware — the Core service runs standalone with two mock agents.

**1. Configure auth** (recommended before first run):

```bash
cp config.example.toml config.toml
cp .env.example .env
# Edit both files and set the same DECKHAND_API_KEY / [auth] api_keys value
```

If you skip this step, Core auto-generates a temporary write key on startup and logs it to the console.

**2. Start the service:**

```bash
make dev
# or: uv run uvicorn deckhand.main:app --app-dir src --reload
```

**3. List the mock agents:**

```bash
source .env   # if you created one
curl -H "Authorization: Bearer $DECKHAND_API_KEY" http://127.0.0.1:8000/agents
```

You should see `mock-1` and `mock-2`, both `"status": "idle"`.

**4. Start an agent and watch it work:**

```bash
# Start mock-1 — it will run for ~0.5s, then wait for input
curl -X POST -H "Authorization: Bearer $DECKHAND_API_KEY" \
  http://127.0.0.1:8000/agents/mock-1/start

# Check status (should be "awaiting_input" after ~0.5s)
curl -H "Authorization: Bearer $DECKHAND_API_KEY" http://127.0.0.1:8000/agents

# Provide input — agent finishes and returns to idle (~0.5s after input)
curl -X POST -H "Authorization: Bearer $DECKHAND_API_KEY" \
  -H "Content-Type: application/json" -d '{"text": "hello"}' \
  http://127.0.0.1:8000/agents/mock-1/input
```

**5. Try the state store:**

```bash
# Send a signal that writes state with a 30s TTL
curl -X POST -H "Authorization: Bearer $DECKHAND_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"key": "camera.front_door.motion", "active": true, "ttl_seconds": 30}' \
  http://127.0.0.1:8000/signals/webhook/camera.motion

# Read it back
curl -H "Authorization: Bearer $DECKHAND_API_KEY" \
  http://127.0.0.1:8000/state/camera.front_door.motion
```

**6. Run the tests:**

```bash
make check
```

All Core tests should pass (currently 81+).

## CLI

With `make dev` running in another terminal, use the `deckhand` CLI to inspect and drive the service:

```bash
uv run deckhand --help

# State
uv run deckhand state list
uv run deckhand state get camera.front_door.motion
uv run deckhand state watch                        # live state.changed stream

# Events (live WebSocket or on-disk JSONL log)
uv run deckhand events tail
uv run deckhand events tail --type agent.status_changed --type state.changed
uv run deckhand events tail --from-log             # replay from .deckhand/events.log

# Actions / signals
uv run deckhand actions list
uv run deckhand actions call agent.start --payload '{"agent_id": "mock-1"}'
uv run deckhand signals list
uv run deckhand signals fire camera.motion --payload '{"key": "camera.front_door.motion", "active": true, "ttl_seconds": 30}'

# Agents
uv run deckhand agents list
uv run deckhand agents start mock-1
uv run deckhand agents input mock-1 "hello"

# Simulate Claude Code / Cursor hooks without a live session
cat examples/claude_code_hooks.json | jq '.hooks.SessionStart[0]' | uv run deckhand hooks simulate claude-code
```

The CLI reads `DECKHAND_URL` and `DECKHAND_API_KEY` from the environment, then falls back to `config.toml`, and finally to `http://127.0.0.1:8000`. Override with `--url` / `--api-key`.

**Event log:** turn on `[event_log] enabled = true` in `config.toml` (or set `DECKHAND_EVENT_LOG_ENABLED=1`) to append every event as JSONL to `.deckhand/events.log`. Off by default. `deckhand events tail --from-log` reads it.

**Cursor Stream Deck layouts:** see [docs/CURSOR_STREAM_DECK_PROFILES.md](docs/CURSOR_STREAM_DECK_PROFILES.md).

## Connect to a Stream Deck

Once you're comfortable with the API and CLI, add hardware via OpenDeck:

**1. Install [OpenDeck](https://github.com/niclasmattsson/OpenDeck)** for your platform.

**2. Install the Deckhand plugin:**

```bash
# macOS
cp -r opendeck-plugin/com.deckhand.plugin.sdPlugin \
  ~/Library/Application\ Support/OpenDeck/Plugins/

# Linux
cp -r opendeck-plugin/com.deckhand.plugin.sdPlugin \
  ~/.config/OpenDeck/Plugins/
```

**3. Configure the plugin** to use the same API key as Core:

```bash
cd ~/Library/Application\ Support/OpenDeck/Plugins/com.deckhand.plugin.sdPlugin
cp deckhand.env.example deckhand.env
# Edit deckhand.env — set DECKHAND_API_KEY to match config.toml / .env
```

The plugin's `run.sh` creates a local `.venv` and installs `aiohttp` + `websockets` on first launch.

**4. Restart OpenDeck.** A "Deckhand" category appears with six actions:

| Action | What it does |
|--------|-------------|
| **Agent Status** | Monitor + interact with an agent (start/cancel/input) |
| **Agent Slot** | Dynamic slot for priority-ranked agents (Cursor) |
| **Data Widget** | Display a live state value on a button |
| **Run Action** | Execute any Deckhand action on press |
| **Signal Trigger** | Fire a Deckhand signal on press |
| **Agent Dashboard** | Agent summary; press focuses attention |

Drag **Agent Status** onto a button, pick `mock-1` in the Property Inspector, and press it to start the agent.

## Configuration

Copy `config.example.toml` to `config.toml`, or use environment variables:

| Setting | Env var | Default |
|---------|---------|---------|
| Listen host | `DECKHAND_HOST` | `127.0.0.1` |
| Listen port | `DECKHAND_PORT` | `8000` |
| Plugin modules | `DECKHAND_PLUGINS` | `deckhand.plugins.builtin` |
| State persistence file | `DECKHAND_STATE_FILE` | none (in-memory) |
| API key | `DECKHAND_API_KEY` | auto-generated write key (logged at startup) |
| Event log | `DECKHAND_EVENT_LOG_ENABLED` / `DECKHAND_EVENT_LOG` | off; path defaults to `.deckhand/events.log` |
| Config file path | `DECKHAND_CONFIG_FILE` | `./config.toml` if present |

The OpenDeck plugin reads `DECKHAND_URL` (default `http://localhost:8000`) and `DECKHAND_API_KEY` from `deckhand.env` (loaded by `run.sh`).

## Documentation

- **[Plugin Guide](docs/PLUGIN_GUIDE.md)** — Extend Deckhand Core with custom actions and signals
- **[Integrations](docs/INTEGRATIONS.md)** — Home Assistant webhook and RSS poller patterns (signals → state → Data Widget)
- **[OpenDeck Plugin](opendeck-plugin/README.md)** — Install and develop the OpenDeck bridge
- **[API Reference](docs/API.md)** — HTTP API documentation
- **[Event Schema](docs/EVENTS.md)** — Event types and schema reference
- **[Example Plugin](examples/example_plugin.py)** — Complete plugin with actions, signals, and state

## License

[Add your license here]
