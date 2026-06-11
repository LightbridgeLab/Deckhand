# Deckhand – Development Guidelines

Deckhand is a local-first control plane for Stream Deck and other thin clients. The UI is a
client; orchestration lives in a local service. Agents are one kind of plugin, but the platform
is broader: signals + actions + state are the primary integration surface.

## Core Principles

1. **Thin UI, Smart Core**
   - Stream Deck is a dumb terminal for display and button presses.
   - Orchestration, state, and decisions live in the local Deckhand service.

2. **Bidirectional by Default**
   - The core emits events over WebSocket; clients should avoid polling.
   - State changes are streamed to enable indicator buttons.

3. **Plugin-Friendly, Agent-Agnostic**
   - Integrations register actions and signals via local Python modules.
   - Agents are optional plugins, not a special-case UI concern.

4. **Local-First**
   - The service runs locally; prefer LAN/local APIs before cloud dependencies.
   - No remote execution or cloud orchestration in core.

5. **Composable Actions**
   - Buttons trigger named actions (e.g., `agent.start`, `ui.open_url`).
   - Signals ingest external events (e.g., camera motion webhooks).
   - State keys drive indicator buttons (e.g., `camera.front_door.motion`).

## Architecture Snapshot

- **Service**: FastAPI HTTP + WebSocket API.
- **Event Bus**: In-memory pub/sub with a versionable event envelope.
- **State Store**: In-memory key/value with optional TTL; emits `state.changed` events.
- **Actions**: Named handlers registered in an action registry.
- **Signals**: Named handlers registered in a signal registry.
- **Plugins**: Local Python modules only (see `deckhand.plugins.loader`).
- **Bindings**: Button-to-action mappings live in OpenDeck profiles (not in Core config).

## Event Envelope

Events use a generic shape so agents and non-agent signals look the same to clients:
- `type`: event type string (e.g., `state.changed`, `agent.status_changed`, `ui.open_url`)
- `source`: `{kind, id}` for attribution
- `payload`: event data
- `ts`: UNIX timestamp

## Client Expectations

- UI clients decide how to open URLs or native apps.
- Clients can query `GET /actions` and `GET /signals` for discovery.
- Clients should listen to `/events` and update indicators from `state.changed`.

## Constraints (for now)

- Optional state persistence (JSON file) and API key auth; no multi-user support.
- No Stream Deck SDK plugin in core; keep client implementations thin.
- Avoid agent-specific logic in shared infrastructure.
