# Dev console ↔ OpenDeck parity checklist

Manual verification at [http://127.0.0.1:8000/dev/](http://127.0.0.1:8000/dev/) with `make dev` running. Virtual tiles use the same settings fields as Property Inspectors ([`opendeck-action-settings.json`](opendeck-action-settings.json)).

## Setup

1. Paste API key from startup log / `.env` / `config.toml`.
2. Confirm **Health** and **Events** badges are green.
3. Open **Virtual buttons → Settings** on each tile as needed.

## Agent Status (`com.deckhand.agent.status`)

| Step | Action | Expected |
|------|--------|----------|
| Configure | Select agent `mock-1` | Tile shows agent label when idle |
| Press (idle) | Click face | `POST /agents/mock-1/start`; status → running; title "Running" |
| Press (running) | Click face | `POST .../cancel`; status → idle |
| Input | Start agent, wait for `awaiting_input` | Title "Input!"; 🔊 if sounds enabled |
| Press (input) | Click face | `POST .../input` with default input text |
| Error | Force error state | Title "Error"; red border |
| Auto-retry | Enable auto-retry, max 3 | On error: "Retry 1" then linear delay (5s, 10s, 15s) and `POST .../start` |
| WS | Watch event log | `agent.status_changed` refreshes tile |

## Data Widget (`com.deckhand.widget`)

| Step | Action | Expected |
|------|--------|----------|
| Configure | `state_key` = `camera.front_door.motion`, format `boolean` | Shows ✓/✗ from state |
| Live | Fire camera.motion preset or signal | Tile updates on `state.changed` |
| Press | Optional `action_on_press` | `POST /actions/{name}` with `{}` |

## Signal Trigger (`com.deckhand.signal.trigger`)

| Step | Action | Expected |
|------|--------|----------|
| Configure | Pick signal from list; optional JSON payload | Idle title = last segment of signal name |
| Press | Click face | `POST /signals/webhook/{name}`; flash "Sent!" ~0.5s |

## Run Action (`com.deckhand.action.run`)

| Step | Action | Expected |
|------|--------|----------|
| Configure | Pick action; optional JSON payload | Idle title = last segment of action name |
| Press | Click face | `POST /actions/{name}` with payload; flash "OK!" ~0.5s |

## Agent Dashboard (`com.deckhand.agent.dashboard`)

| Step | Action | Expected |
|------|--------|----------|
| Configure | `agent_filter` = `cursor` | Title reflects cursor agents only |
| Idle | No agents | Title "No Agents" |
| Press (attention) | Any `awaiting_input` / `error` | `POST /actions/ui.focus_cursor_agent` for cursor agents |
| Press (otherwise) | Click face | Refreshes from `GET /agents` |
| WS | Change any agent status | Title updates without press |

## Agent Slot (`com.deckhand.agent.slot`)

| Step | Action | Expected |
|------|--------|----------|
| Configure | `slot_index` 1, `agent_filter` cursor | Binds highest-priority cursor agent |
| Empty | No matching agents | Title `—` |
| Running | Cursor agent working | CSS spinner on tile |
| Press | Cursor agent bound | `POST /actions/ui.focus_cursor_agent` |
| WS | Register/unregister agent | Slot rebinding updates title |

## Animated graphics (Phase 6)

Dev console: running tiles use CSS spinner (`.tile-running-active`). OpenDeck Agent Slot cycles title frames while running.
