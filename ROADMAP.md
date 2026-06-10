# Deckhand Roadmap

## Completed: OpenDeck Integration (v0.1)

- [x] Deckhand Core: stable HTTP + WebSocket API
- [x] Plugin system with action/signal/state registries
- [x] Agent abstraction with lifecycle management
- [x] Event bus with versioned envelopes
- [x] OpenDeck plugin bridge (plugin.py, bridge.py)
- [x] Agent Status action (monitor + interact with agents)
- [x] Data Widget action (display live state on buttons)
- [x] Property Inspector UIs for both actions
- [x] Cross-platform audio notifications
- [x] Plugin assets (icons, sounds)
- [x] End-to-end plugin tests

## Completed: Hardening (v0.2)

- [x] Reconnection logic with exponential backoff for Deckhand Core WebSocket
- [x] Property Inspector: live state key autocomplete for Data Widget
- [x] Additional display formats (percentage, boolean, number, currency)
- [x] Error state recovery (auto-retry failed agent starts with configurable attempts)
- [x] Plugin bridge diagnostics (event counts, connection status, error tracking)

## Completed: Extended Actions & Features

- [x] Signal Trigger action (fire a Deckhand signal on button press)
- [x] Run Action button (execute any Deckhand action with fixed payload)
- [x] Multi-agent dashboard (summary of all agents on one button)
- [x] Remote Deckhand Core support (DECKHAND_URL env var)
- [x] State persistence (JSON file, survives service restarts)
- [x] API key authentication (optional, for HTTP and WebSocket)

## Backlog

### Integrations & plugins

- [x] Integration recipes: Home Assistant webhook + RSS poller patterns ([docs/INTEGRATIONS.md](docs/INTEGRATIONS.md))
- [ ] Sample non-agent plugin in-repo (e.g. minimal RSS or HA webhook shim) — deferred

### OpenDeck client

- [ ] **Data Widget multi-state** — Map `state_key` values to multi-state button images (parity with Agent Status idle/running/input/error), e.g. JSONPath or rule-based state index from structured state values

### Core platform

- [ ] **Plugin shutdown hook** — Optional async cleanup when the service stops, for background pollers started from `register()` (RSS, MQTT, periodic sync)
