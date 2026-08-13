# Event Schema Reference

Complete reference for Deckhand event types and schema.

## Event Envelope

All events follow a standard envelope structure:

```json
{
  "type": "event.type.name",
  "source": {
    "kind": "source_kind",
    "id": "source_id"
  },
  "payload": {
    // Event-specific data
  },
  "ts": 1234567890.0,
  "version": "1.0"
}
```

### Fields

- **`type`** (string): Event type identifier (e.g., `state.changed`, `agent.status_changed`)
- **`source`** (object): Source attribution
  - **`kind`** (string): Source kind (e.g., `"action"`, `"signal"`, `"api"`, `"state"`)
  - **`id`** (string): Source identifier (e.g., action name, signal name, state key)
- **`payload`** (object): Event-specific data
- **`ts`** (number): UNIX timestamp (seconds since epoch)
- **`version`** (string): Event schema version (currently `"1.0"`)

## Built-in Event Types

### `state.changed`

Emitted when state is updated.

**Source:** `{"kind": "state", "id": "<state_key>"}` or custom source

**Payload:**
```json
{
  "key": "camera.front_door.motion",
  "value": {"active": true},
  "updated_at": 1234567890.0,
  "expires_at": 1234567920.0
}
```

**Fields:**
- **`key`** (string): State key
- **`value`** (any): State value
- **`updated_at`** (number): Timestamp when state was updated
- **`expires_at`** (number | null): Expiration timestamp (null if no TTL)

**Example:**
```json
{
  "type": "state.changed",
  "source": {"kind": "signal", "id": "camera.motion"},
  "payload": {
    "key": "camera.front_door.motion",
    "value": {"active": true},
    "updated_at": 1234567890.0,
    "expires_at": 1234567920.0
  },
  "ts": 1234567890.0,
  "version": "1.0"
}
```

### `state.cleared`

Emitted when state is cleared.

**Source:** `{"kind": "state", "id": "<state_key>"}` or custom source

**Payload:**
```json
{
  "key": "camera.front_door.motion"
}
```

**Example:**
```json
{
  "type": "state.cleared",
  "source": {"kind": "state", "id": "camera.front_door.motion"},
  "payload": {
    "key": "camera.front_door.motion"
  },
  "ts": 1234567890.0,
  "version": "1.0"
}
```

### `agent.status_changed`

Emitted when an agent's status changes.

**Source:** `{"kind": "agent", "id": "<agent_id>"}`

**Payload:**
```json
{
  "agent": {
    "id": "mock-1",
    "type": "mock",
    "status": "running",
    "capabilities": []
  }
}
```

**Fields:**
- **`agent`** (object): Agent data
  - **`id`** (string): Agent identifier
  - **`type`** (string): Agent type
  - **`status`** (string): Current status (see Status Values below)
  - **`capabilities`** (array): List of agent capabilities

**Status Values:**
- `"idle"`: Agent is not running
- `"running"`: Agent is actively running
- `"awaiting_input"`: Agent is waiting for user input
- `"error"`: Agent encountered an error

**Example:**
```json
{
  "type": "agent.status_changed",
  "source": {"kind": "agent", "id": "mock-1"},
  "payload": {
    "agent": {
      "id": "mock-1",
      "type": "mock",
      "status": "running",
      "capabilities": []
    }
  },
  "ts": 1234567890.0,
  "version": "1.0"
}
```

### `ui.open_url`

Request to open a URL in the client.

**Source:** `{"kind": "action", "id": "ui.open_url"}` or custom source

**Payload:**
```json
{
  "url": "https://example.com"
}
```

**Example:**
```json
{
  "type": "ui.open_url",
  "source": {"kind": "action", "id": "ui.open_url"},
  "payload": {
    "url": "https://example.com"
  },
  "ts": 1234567890.0,
  "version": "1.0"
}
```

Clients should open the URL in the default browser or appropriate application.

### `error`

Standardized error event.

**Source:** Varies by error source (e.g., `{"kind": "api", "id": "actions.run"}`)

**Payload:**
```json
{
  "error_type": "ValidationError",
  "message": "Missing required field: agent_id",
  "details": {
    "field": "agent_id",
    "action_name": "agent.start"
  }
}
```

**Error Types:**
- `"ValidationError"`: Invalid payload or missing required fields
- `"NotFoundError"`: Resource not found (agent, action, signal)
- `"InternalError"`: Internal server error

**Example:**
```json
{
  "type": "error",
  "source": {"kind": "api", "id": "actions.run"},
  "payload": {
    "error_type": "ValidationError",
    "message": "Missing required field: agent_id",
    "details": {
      "field": "agent_id",
      "action_name": "agent.start"
    }
  },
  "ts": 1234567890.0,
  "version": "1.0"
}
```

## Custom Events

Plugins can emit custom events using `build_event()`. Use descriptive event type names with namespaces:

- `lights.changed`
- `camera.motion_detected`
- `sensor.temperature_updated`

**Example:**
```python
from deckhand.orchestrator.events import build_event

await registry.events.emit(build_event(
    "lights.changed",
    {"kind": "action", "id": "lights.turn_on"},
    {"room": "living_room", "state": "on"},
))
```

## Source Attribution

The `source` field identifies where an event originated:

- **`kind`**: Category of source
  - `"action"`: Triggered by an action
  - `"signal"`: Triggered by a signal/webhook
  - `"api"`: Triggered by API call
  - `"state"`: Triggered by state operation
  - `"agent"`: Triggered by agent
  - `"plugin"`: Triggered by plugin

- **`id`**: Specific identifier
  - Action name (e.g., `"agent.start"`)
  - Signal name (e.g., `"camera.motion"`)
  - API endpoint (e.g., `"actions.run"`)
  - State key (e.g., `"camera.front_door.motion"`)
  - Agent ID (e.g., `"mock-1"`)

## Event Versioning

Events include a `version` field to support schema evolution. Current version is `"1.0"`.

Future versions may:
- Add optional fields to payloads
- Deprecate fields (with notice)
- Introduce new event types

Clients should:
- Ignore unknown event types
- Handle missing optional fields gracefully
- Log unknown event versions for debugging

## Receiving Events

Connect to the `/events` WebSocket endpoint to receive events:

```python
import asyncio
import websockets
import json

async def listen():
    uri = "ws://127.0.0.1:18765/events"
    async with websockets.connect(uri) as websocket:
        while True:
            message = await websocket.recv()
            event = json.loads(message)
            # Process event...
            if event["type"] == "state.changed":
                update_indicator(event["payload"]["key"], event["payload"]["value"])

asyncio.run(listen())
```

Events are emitted immediately when state changes, actions execute, or errors occur. No polling required.
