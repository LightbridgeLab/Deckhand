# Plugin Author Guide

This guide explains how to create **Deckhand Core plugins** — Python modules that extend the orchestration service with custom actions, signals, and state.

> **Note**: This is about extending Deckhand Core (the FastAPI service), not the OpenDeck plugin. Core plugins surface automatically to the OpenDeck bridge and CLI. For the Stream Deck bridge, see [opendeck-plugin/README.md](../opendeck-plugin/README.md).

## Introduction

Deckhand Core plugins register actions and signals at startup:

- **Actions** — named commands via `POST /actions/{name}` (e.g. from a Run Action button)
- **Signals** — webhook handlers via `POST /signals/webhook/{name}` (e.g. from external hooks)
- **State** — key/value store for Data Widget indicators, with optional TTL
- **Events** — WebSocket pub/sub to connected clients

See `src/deckhand/plugins/claude_code_usage.py` for a real poller plugin with `registry.on_shutdown(...)`.

## Quick start

Minimal plugin that publishes a computed state key:

```python
from deckhand.plugins.registry import PluginRegistry

def register(registry: PluginRegistry) -> None:
    async def refresh_summary(payload: dict[str, object]) -> None:
        agents = list(registry.orchestrator.list_agents())
        pending = sum(1 for a in agents if a.status == "awaiting_input")
        await registry.state.set_state(
            "my_plugin.summary",
            {"count": pending, "title": f"{pending}?"},
            source={"kind": "action", "id": "my_plugin.refresh_summary"},
        )

    registry.actions.register(
        "my_plugin.refresh_summary",
        refresh_summary,
        description="Recompute my_plugin.summary state",
        payload_schema={},
    )
```

Add the module path to `config.toml`:

```toml
[plugins]
modules = ["my_plugin"]
```

## Plugin structure

Every plugin must define:

```python
def register(registry: PluginRegistry) -> None:
    ...
```

The loader calls this once at startup. Missing `register()` raises `ValueError`.

## Registering actions

Actions are async functions that accept a payload dict and return `None`. Validate early and raise `ValueError` for bad input — Core maps that to HTTP 400.

```python
registry.actions.register(
    "my_plugin.do_thing",
    handler,
    description="What this action does",
    payload_schema={"agent_id": {"type": "string", "required": True}},
)
```

Namespace action names (`plugin_name.action_name`).

## Registering signals

Signals use the same handler shape. They often update state for indicator buttons:

```python
async def session_event(payload: dict[str, object]) -> None:
    agent_id = payload.get("agent_id")
    if not agent_id:
        raise ValueError("agent_id is required")
    await registry.state.set_state(
        f"my_plugin.last_event.{agent_id}",
        {"seen_at": payload.get("ts")},
        ttl_seconds=300.0,
        source={"kind": "signal", "id": "my_plugin.session_event"},
    )

registry.signals.register(
    "my_plugin.session_event",
    session_event,
    description="Ingest an external session event",
    payload_schema={"agent_id": {"type": "string", "required": True}},
)
```

## Background tasks

Pollers and watchers must register a shutdown hook so FastAPI tears them down cleanly:

```python
async def _poll_loop() -> None:
    ...

task = asyncio.create_task(_poll_loop())
registry.on_shutdown(lambda: task.cancel())
```

## Using registry components

| Component | Purpose |
|-----------|---------|
| `registry.actions` | Register and run actions |
| `registry.signals` | Register webhook handlers |
| `registry.state` | `set_state`, `get_state`, `clear_state` |
| `registry.events` | Emit via `build_event()` from `deckhand.orchestrator.events` |
| `registry.orchestrator` | Agent lifecycle (advanced) |

Emit events with `build_event()` — never construct envelopes by hand.

## Best practices

1. Validate payloads early; raise `ValueError` or `KeyError` as appropriate.
2. Namespace actions, signals, and state keys.
3. Document `payload_schema` for discovery (`GET /actions`, `GET /signals`).
4. List new state keys under `[catalog.state_keys]` or run `deckhand catalog sync`.
5. Register `on_shutdown` for any background task.
6. Keep handlers async.

## Loading plugins

```toml
[plugins]
modules = ["deckhand.plugins.claude_code_usage", "my_plugin"]
```

Or `DECKHAND_PLUGINS=deckhand.plugins.claude_code_usage,my_plugin`.

## Testing

```python
from deckhand.plugins.registry import PluginRegistry
from deckhand.orchestrator.actions import ActionRegistry
from deckhand.orchestrator.signals import SignalRegistry
from deckhand.orchestrator.events import EventBus
from deckhand.orchestrator.manager import Orchestrator

@pytest.mark.asyncio
async def test_my_plugin():
    orchestrator = Orchestrator()
    registry = PluginRegistry(
        actions=ActionRegistry(orchestrator),
        signals=SignalRegistry(),
        state=orchestrator.state_store,
        events=orchestrator.event_bus,
        orchestrator=orchestrator,
    )
    from my_plugin import register
    register(registry)
    await registry.actions.run("my_plugin.refresh_summary", {})
    assert registry.state.get_state("my_plugin.summary") is not None
```

See `tests/test_plugin_shutdown.py` and `src/deckhand/plugins/claude_code_usage.py` for working patterns.
