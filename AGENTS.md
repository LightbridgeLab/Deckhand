# Deckhand – Development Guidelines

Deckhand turns one Stream Deck button into a real action for AI coding workflows: jump to the Claude session that needs input, show how many tokens you've burned this week, fire a project-startup macro. The service runs locally on `127.0.0.1`, talks to [OpenDeck](https://github.com/niclasmattsson/OpenDeck) today and the official Elgato Stream Deck next, and is built for the specific problem of "I have multiple Claude / Cursor sessions and want tactile control over them" — not as a generic automation platform.

If you're touching the code, the principles below capture how the project is shaped today.

## Core Principles

1. **AI coding agents are the point, not an example.** The "agent" abstraction exists because Claude Code and Cursor sessions are the load-bearing first-party use case. Everything else (signals, custom plugins, raw state) is supporting cast. Don't reintroduce the framework-era framing where agents were "one kind of plugin." That stretched the platform thin.

2. **Thin client, smart core.** The Stream Deck (or OpenDeck) is a button surface for display and presses. Orchestration, state, decisions, and lifecycle live in the local Deckhand service. Clients should never re-implement business logic.

3. **Bidirectional by default.** The core emits events over WebSocket; clients subscribe rather than poll. State changes stream to enable indicator buttons that update without round-trips.

4. **Local-first.** The service runs on the developer's machine. Prefer local APIs, local files, and AppleScript over cloud round-trips. No remote execution, no cloud orchestration, no opt-in telemetry in core.

5. **Composable but specific.** Buttons trigger named actions (`agents.focus_next_pending`, `agent.start`, `ui.open_url`). Signals ingest external events. State keys drive indicator buttons (`usage.claude_code.session_tokens`, `agents.pending_input_count`). When in doubt about whether to ship something generic or specific, ship specific — the project's value is in solving the AI-coding-agent case well, not in being a marketplace.

## Architecture Snapshot

- **Service:** FastAPI HTTP + WebSocket on `127.0.0.1:8000`.
- **Event bus:** in-memory pub/sub with a versioned event envelope (`type`, `source`, `payload`, `ts`, `version`). In-process listeners and WebSocket subscribers receive the same stream.
- **State store:** in-memory key/value with optional TTL; emits `state.changed`. Optional JSON persistence across restarts.
- **Actions:** named async handlers (`ActionRegistry`). Built-ins cover agent lifecycle (`agent.start/cancel/input`), UI hints (`ui.open_url`, `ui.focus_cursor_agent`), and the pending-input focuser (`agents.focus_next_pending`).
- **Signals:** named webhook receivers (`SignalRegistry`). Used by hook-driven integrations (Claude Code / Cursor hooks post here).
- **Agents:** `AgentBase` subclasses that reflect external session state (Claude Code, Cursor). Created on demand from hook events; cleared on `SessionEnd`. Not framework objects.
- **Focusers:** per-agent async callables that bring an external window/tab to the foreground. Today: iTerm via AppleScript. Cursor and browser are tracked separately ([#24](https://github.com/LightbridgeLab/Deckhand/issues/24), [#25](https://github.com/LightbridgeLab/Deckhand/issues/25)).
- **Plugins:** local Python modules loaded via `deckhand.plugins.loader`. Each plugin's `register()` gets a `PluginRegistry` and can register actions, signals, event-bus listeners, and shutdown hooks. Background tasks (pollers, watchers) MUST register a shutdown hook via `registry.on_shutdown(coro)` so the FastAPI lifespan tears them down cleanly.
- **Bindings:** button-to-action mappings live in OpenDeck profiles, not in Core config.

## Event Envelope

```
type      string  (e.g. "state.changed", "agent.status_changed", "ui.open_url")
source    {kind, id}  attribution
payload   dict
ts        unix timestamp
version   schema version ("1.0")
```

Use `build_event(...)` / `build_error_event(...)` from `deckhand.orchestrator.events`. Never construct envelopes by hand.

## Client Expectations

- Clients open URLs / native apps themselves; the core emits `ui.open_url` and similar but does not shell out for the client.
- Discovery: `GET /actions`, `GET /signals`, `GET /agents`.
- Live updates: subscribe to `/events` WebSocket and update indicators from `state.changed`.

## Scope (deliberate non-goals)

- **macOS-first** in v0.3. The iTerm focuser is AppleScript-based. Linux and Windows ports are interesting but unscoped.
- **OpenDeck-first.** Elgato Stream Deck plugin port is planned; until it lands, OpenDeck is the only client.
- **One provider per integration surface.** Today: Claude Code for usage + focus, Cursor for status reflection. Don't fan out the abstraction until we have a concrete second provider to test against.
- **No multi-user, no cloud sync, no remote agents.** Service is single-user, single-machine.

## Constraints

- Optional state persistence via JSON file. Optional API key auth (auto-generated write key if none configured). No RBAC beyond `read` / `write` scopes.
- No Stream Deck SDK plugin in core; client implementations stay thin.
- Avoid agent-specific logic in shared infrastructure beyond what's already established. If you find yourself adding a `if agent_type == "claude_code"` branch to a generic registry, that's a smell — push it into the agent class.
