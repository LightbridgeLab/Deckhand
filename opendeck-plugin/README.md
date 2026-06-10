# Deckhand OpenDeck Plugin

An [OpenDeck](https://github.com/niclasmattsson/OpenDeck) plugin that bridges Stream Deck hardware to the Deckhand orchestration service.

## Prerequisites

- [OpenDeck](https://github.com/niclasmattsson/OpenDeck) installed and running
- [Deckhand Core](../README.md) service running on `http://localhost:8000`
- Python 3.11+ (used by `run.sh` to bootstrap a plugin-local venv)

## Installation

Copy the plugin directory into OpenDeck's plugins folder:

```bash
# macOS
cp -r com.deckhand.plugin.sdPlugin ~/Library/Application\ Support/OpenDeck/Plugins/

# Linux
cp -r com.deckhand.plugin.sdPlugin ~/.config/OpenDeck/Plugins/
```

Configure auth so the plugin can reach Deckhand Core:

```bash
cd ~/Library/Application\ Support/OpenDeck/Plugins/com.deckhand.plugin.sdPlugin
cp deckhand.env.example deckhand.env
# Set DECKHAND_API_KEY to the same value as Deckhand Core (config.toml or .env)
```

Then restart OpenDeck. A "Deckhand" category should appear with six actions:

| Action | UUID | Purpose |
|--------|------|---------|
| **Agent Status** | `com.deckhand.agent.status` | Monitor and interact with one agent |
| **Agent Slot** | `com.deckhand.agent.slot` | Dynamic slot bound to a priority-ranked agent |
| **Data Widget** | `com.deckhand.widget` | Display live state on a button |
| **Signal Trigger** | `com.deckhand.signal.trigger` | Fire a Deckhand signal on press |
| **Run Action** | `com.deckhand.action.run` | Execute any action with a fixed payload |
| **Agent Dashboard** | `com.deckhand.agent.dashboard` | Summary of agents; press focuses attention |

On first launch, `run.sh` creates a `.venv` in the plugin directory and installs `aiohttp` + `websockets`.

**Settings schema:** Field names and types for Property Inspectors and the dev console virtual button editor are documented in [`docs/opendeck-action-settings.json`](../docs/opendeck-action-settings.json). When adding or renaming a PI field, update that file and the matching HTML under `propertyInspector/`.

## Actions

### Agent Dashboard (`com.deckhand.agent.dashboard`)

Shows a compact summary of agents (counts by status). When any agent needs attention (`awaiting_input` or `error`), press focuses the highest-priority agent (Cursor agents open in Cursor via `ui.focus_cursor_agent`).

**Settings:** `agent_filter` (e.g. `cursor` or `*`), optional `default_input` for non-Cursor agents.

### Agent Slot (`com.deckhand.agent.slot`)

Binds a fixed slot index to a dynamically chosen agent. Agents are sorted by priority (attention → running → idle) and assigned to slots at runtime — no per-agent Property Inspector setup.

**Settings:** `slot_index` (1–15), `page` (1–2), `agent_filter` (default `cursor`), `default_input`, `sounds_enabled`.

**Press:** Cursor agents → focus in Cursor. Other agents → start/cancel/input like Agent Status.

See [Cursor Stream Deck profiles](../docs/CURSOR_STREAM_DECK_PROFILES.md) for recommended Ajazz 15 and Elgato 6 layouts.

### Agent Status (`com.deckhand.agent.status`)

Monitors a Deckhand agent's lifecycle. The button image and title change based on agent status:

| Status | Image | Title | Sound |
|--------|-------|-------|-------|
| Idle | `agent-idle.png` | Agent name | — |
| Running | `agent-running.png` | "Running" | — |
| Awaiting Input | `agent-input.png` | "Input!" | `need-input.wav` |
| Error | `agent-error.png` | "Error" | — |

**Button press behavior:**
- **Idle** → Start the agent
- **Running** → Cancel the agent
- **Awaiting Input** → Send the configured default input

**Settings (Property Inspector):**
- Agent selector (populated from Deckhand Core)
- Sound toggle (enable/disable audio notifications)
- Default input text
- Auto-retry on error (with max attempts)

### Data Widget (`com.deckhand.widget`)

Displays the current value of a Deckhand state key on the button title. Updates in real time when the state changes.

**Settings (Property Inspector):**
- State key with autocomplete (e.g., `camera.front_door.motion`)
- Display format: raw, currency, percentage, boolean, number, summary
- Action on press (optional Deckhand action to execute)

### Signal Trigger (`com.deckhand.signal.trigger`)

Fires a configured Deckhand signal when the button is pressed (e.g., `camera.motion` with a JSON payload).

### Run Action (`com.deckhand.action.run`)

Executes any registered Deckhand action with a fixed JSON payload when pressed (e.g., `agent.start` with `{"agent_id": "mock-2"}`).

## Development

### Running locally

Start Deckhand Core:

```bash
cd .. && make dev
```

Run the plugin directly (bypassing OpenDeck, for testing):

```bash
cd com.deckhand.plugin.sdPlugin
cp deckhand.env.example deckhand.env   # set DECKHAND_API_KEY
./run.sh -port 28196 -pluginUUID test -registerEvent registerPlugin -info '{}'
```

Run plugin tests:

```bash
cd .. && uv run pytest opendeck-plugin/tests/test_plugin.py -v --asyncio-mode=auto
```

### Adding new actions

1. Create a new handler in `actions/` following the pattern in `agent_status.py`
2. Register it in `plugin.py` (`ACTION_HANDLERS`)
3. Add the action definition to `manifest.json`
4. Create a Property Inspector HTML file if needed

### Asset requirements

- Plugin icon: 144x144 PNG
- Action icons: 72x72 PNG (with @2x variants at 144x144)
- Sounds: WAV format
