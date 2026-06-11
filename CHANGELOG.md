# Changelog

All notable changes to Deckhand will be documented in this file.

## [1.0.0] - 2024-12-XX

### Added

- **Stable HTTP + WebSocket API**
  - RESTful endpoints for agents, actions, signals, and state
  - WebSocket event streaming for real-time updates
  - Comprehensive error handling with standardized error events

- **Plugin System**
  - Plugin loader for registering custom actions and signals
  - Builtin plugin with `ui.open_url` action and `camera.motion` signal
  - Plugin registry for accessing core components

- **Action and Signal Registries**
  - Named action routing with payload validation
  - Signal webhook ingestion
  - Metadata support (description, payload schema) for self-documenting APIs
  - Discovery endpoints (`GET /actions`, `GET /signals`)

- **State Store**
  - In-memory key-value store for UI indicators
  - TTL (time-to-live) support for temporary state
  - Automatic expiration and purging
  - `state.changed` and `state.cleared` events

- **Event Bus**
  - WebSocket-based pub/sub system
  - Versioned event envelope (`version: "1.0"`)
  - Standardized error event format
  - Source attribution for all events

- **Configuration Support**
  - TOML configuration file loading
  - Environment variable overrides
  - Bindings file loading (JSON)
  - Priority: defaults → config file → environment variables

- **Testing Infrastructure**
  - pytest-based test suite
  - Tests for actions, signals, state, events, and plugins
  - Test fixtures for easy plugin testing

- **Documentation**
  - Plugin author guide (`docs/PLUGIN_GUIDE.md`)
  - Cursor Stream Deck profiles guide (`docs/CURSOR_STREAM_DECK_PROFILES.md`)
  - Complete API reference (`docs/API.md`)
  - Event schema reference (`docs/EVENTS.md`)
  - Reference hook configurations (`examples/claude_code_hooks.json`, `examples/cursor_hooks.json`)

- **Agent Abstraction**
  - Base agent interface
  - Mock agent implementation for testing
  - Agent lifecycle management (start, cancel, input)

### Architecture

- **Thin Client, Smart Core**: UI clients are dumb terminals; orchestration lives in service
- **Bidirectional by Default**: Events streamed via WebSocket; no polling required
- **Plugin-Friendly**: Extensible via Python modules
- **Local-First**: Service runs locally; prefer LAN/local APIs
- **Composable Actions**: Buttons trigger named actions; signals ingest external events

### API Stability

- Event schema versioned (`version: "1.0"`)
- API endpoints frozen for v1.0.0
- Backward-compatible changes only in future minor versions

### Breaking Changes

None (initial release)

### Migration Guide

N/A (initial release)
