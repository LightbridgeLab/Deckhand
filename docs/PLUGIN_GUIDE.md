# Plugin Author Guide

This guide explains how to create **Deckhand Core plugins** — Python modules that extend the orchestration service with custom actions, signals, and state management.

> **Note**: This is about extending Deckhand Core (the FastAPI service), not about the OpenDeck plugin. Deckhand Core plugins add server-side capabilities that automatically become available to the OpenDeck bridge and any other connected client. For the OpenDeck plugin, see [opendeck-plugin/README.md](../opendeck-plugin/README.md).

## Introduction

Deckhand Core plugins are Python modules that register actions and signals with the service. Actions are named commands that can be triggered via `POST /actions/{name}` (e.g., from an OpenDeck button press). Signals ingest external events via `POST /signals/webhook/{name}` (e.g., webhooks from cameras or sensors).

### Architecture Overview

- **Actions**: Named commands triggered via `POST /actions/{name}`
- **Signals**: Named handlers for external events via `POST /signals/webhook/{name}`
- **State Store**: Key-value store for UI indicators with optional TTL
- **Event Bus**: Pub/sub system for emitting events to connected clients (including the OpenDeck plugin)

Plugins register their capabilities during service startup. Any registered action or signal automatically becomes available to the OpenDeck bridge — meaning a single plugin registration surfaces functionality on Stream Deck buttons.

## Quick Start

Here's a minimal plugin example:

```python
from deckhand.plugins.registry import PluginRegistry

def register(registry: PluginRegistry) -> None:
    async def turn_on_lights(payload: dict[str, object]) -> None:
        room = payload.get("room")
        if not room:
            raise ValueError("room is required")
        # Your logic here
        await registry.state.set_state(
            f"lights.{room}.state",
            {"on": True},
            source={"kind": "action", "id": "lights.turn_on"},
        )

    registry.actions.register(
        "lights.turn_on",
        turn_on_lights,
        description="Turn on lights in a room",
        payload_schema={"room": {"type": "string", "required": True}},
    )
```

Save this as `my_plugin.py` and add `"my_plugin"` to your `Settings.plugin_modules` list or configuration file.

## Plugin Structure

### Required Function

Every plugin module must define a `register()` function with this signature:

```python
from deckhand.plugins.registry import PluginRegistry

def register(registry: PluginRegistry) -> None:
    # Register actions and signals here
    pass
```

The `register()` function is called once during service startup. If your module doesn't have this function, the plugin loader will raise a `ValueError`.

## Registering Actions

Actions are async functions that accept a payload dictionary and return `None`.

### Action Handler Signature

```python
async def action_handler(payload: dict[str, object]) -> None:
    # Validate payload
    # Perform action
    # Update state or emit events
    pass
```

### Payload Validation

Always validate required fields early and raise `ValueError` for invalid input:

```python
async def my_action(payload: dict[str, object]) -> None:
    required_field = payload.get("required_field")
    if not required_field:
        raise ValueError("required_field is required")
    
    optional_field = payload.get("optional_field", "default_value")
    # Use validated fields...
```

### Error Handling

- **`ValueError`**: For validation errors (missing required fields, invalid types)
- **`KeyError`**: For missing resources (e.g., device not found)

These exceptions are automatically converted to HTTP 400/404 responses and error events.

### Metadata Registration

Register actions with metadata to enable self-documenting APIs:

```python
registry.actions.register(
    "lights.turn_on",
    turn_on_lights,
    description="Turn on lights in a room",
    payload_schema={
        "room": {"type": "string", "required": True},
        "brightness": {"type": "number", "required": False, "default": 100},
    },
)
```

The `payload_schema` helps clients understand what fields are expected. Use descriptive action names with namespaces (e.g., `plugin_name.action_name`).

## Registering Signals

Signals have the same handler signature as actions:

```python
async def signal_handler(payload: dict[str, object]) -> None:
    # Process external event
    # Update state
    pass
```

### State Updates from Signals

Signals often update state to drive indicator buttons:

```python
async def camera_motion(payload: dict[str, object]) -> None:
    key = str(payload.get("key") or "camera.front_door.motion")
    active = bool(payload.get("active", True))
    ttl_seconds = payload.get("ttl_seconds")
    
    await registry.state.set_state(
        key,
        {"active": active},
        ttl_seconds=float(ttl_seconds) if ttl_seconds is not None else None,
        source={"kind": "signal", "id": "camera.motion"},
    )
```

### TTL Usage

Use TTL (time-to-live) for temporary state that should expire:

```python
# Motion detection expires after 30 seconds
await registry.state.set_state(
    "camera.motion",
    {"active": True},
    ttl_seconds=30.0,
)
```

### Signal Metadata

Register signals with metadata:

```python
registry.signals.register(
    "camera.motion",
    camera_motion,
    description="Handle camera motion detection webhook",
    payload_schema={
        "key": {"type": "string", "required": False},
        "active": {"type": "boolean", "required": False, "default": True},
        "ttl_seconds": {"type": "number", "required": False},
    },
)
```

## Using Registry Components

The `PluginRegistry` provides access to all core components:

### `registry.actions` - ActionRegistry

Register actions and query existing ones:

```python
# Register action
registry.actions.register("my.action", handler)

# List all actions (returns ActionMetadata list)
all_actions = registry.actions.list_actions()

# Get metadata for specific action
metadata = registry.actions.get_action_metadata("my.action")
```

### `registry.signals` - SignalRegistry

Register signals and query existing ones:

```python
# Register signal
registry.signals.register("my.signal", handler)

# List all signals
all_signals = registry.signals.list_signals()

# Get metadata for specific signal
metadata = registry.signals.get_signal_metadata("my.signal")
```

### `registry.state` - StateStore

Read and write state:

```python
# Set state
await registry.state.set_state(
    "my.key",
    {"value": "data"},
    ttl_seconds=60.0,  # Optional
    source={"kind": "plugin", "id": "my_plugin"},
)

# Get state
entry = registry.state.get_state("my.key")

# List all state
all_state = registry.state.list_state()

# Clear state
await registry.state.clear_state("my.key")
```

### `registry.events` - EventBus

Emit custom events to connected clients:

```python
from deckhand.orchestrator.events import build_event

await registry.events.emit(build_event(
    "my.custom_event",
    {"kind": "plugin", "id": "my_plugin"},
    {"data": "value"},
))
```

### `registry.orchestrator` - Orchestrator

Access agent management (advanced use cases):

```python
# Start an agent
await registry.orchestrator.start_agent("agent-id")

# List agents
agents = list(registry.orchestrator.list_agents())
```

## Event Emission

Use `build_event()` to create properly formatted events:

```python
from deckhand.orchestrator.events import build_event

event = build_event(
    event_type="lights.changed",
    source={"kind": "action", "id": "lights.turn_on"},
    payload={"room": "living_room", "state": "on"},
)
await registry.events.emit(event)
```

Events are automatically versioned (currently "1.0") and include timestamps.

## Best Practices

1. **Validate payloads early**: Check required fields and types before processing
2. **Use descriptive names**: Namespace actions/signals (e.g., `lights.turn_on`, `camera.motion`)
3. **Document payload schemas**: Help clients understand expected fields
4. **Handle errors gracefully**: Raise appropriate exceptions (`ValueError`, `KeyError`)
5. **Update state for indicators**: Use state keys that clients can bind to button indicators. For the OpenDeck Data Widget dropdown, list keys under `[catalog.state_keys]` in `config.toml` (or run `deckhand catalog sync`).
6. **Use TTL for temporary state**: Motion detection, temporary alerts, etc.
7. **Emit events for important changes**: Notify clients of state changes or custom events
8. **Keep handlers async**: All handlers must be async functions

## Loading Plugins

Add your plugin module path to the configuration:

**Environment Variable:**
```bash
DECKHAND_PLUGINS=my_plugin,another_plugin
```

**Config File (`config.toml`):**
```toml
[plugins]
modules = ["my_plugin"]
```

**Python Settings:**
```python
from deckhand.config.settings import Settings

settings = Settings()
settings.plugin_modules = ["my_plugin"]
```

Plugins are loaded in order, so later plugins can depend on earlier ones.

## Testing Plugins

Test your plugins with a mock registry:

```python
import pytest
from deckhand.plugins.registry import PluginRegistry
from deckhand.orchestrator.actions import ActionRegistry
from deckhand.orchestrator.signals import SignalRegistry
from deckhand.orchestrator.events import EventBus
from deckhand.orchestrator.state import StateStore
from deckhand.orchestrator.manager import Orchestrator

def test_my_plugin():
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
    
    # Test action registration
    actions = registry.actions.list_actions()
    assert any(a.name == "my.action" for a in actions)
    
    # Test action execution
    await registry.actions.run("my.action", {"key": "value"})
```

See `tests/test_plugins.py` and `src/deckhand/plugins/claude_code_usage.py` for working plugin patterns — the latter shows a real poller plugin with background-task lifecycle management via `registry.on_shutdown(...)`.
