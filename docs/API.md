# Deckhand API Reference

Complete API reference for the Deckhand service.

## Base URL

Default: `http://127.0.0.1:18765`

Configure via `DECKHAND_HOST` and `DECKHAND_PORT` environment variables or config file. On startup Core writes the bound URL to `~/.config/deckhand/runtime.toml` so the OpenDeck plugin and CLI can find a non-default port without editing client config.

## Agents

### List Agents

Get all registered agents.

**Endpoint:** `GET /agents`

**Response:**
```json
[
  {
    "id": "mock-1",
    "type": "mock",
    "status": "idle",
    "capabilities": []
  }
]
```

**Example:**
```bash
curl http://127.0.0.1:18765/agents
```

### Start Agent

Start an agent by ID.

**Endpoint:** `POST /agents/{agent_id}/start`

**Response:**
```json
{"status": "started"}
```

**Example:**
```bash
curl -X POST http://127.0.0.1:18765/agents/mock-1/start
```

**Errors:**
- `404`: Agent not found

### Cancel Agent

Cancel a running agent.

**Endpoint:** `POST /agents/{agent_id}/cancel`

**Response:**
```json
{"status": "cancelled"}
```

**Example:**
```bash
curl -X POST http://127.0.0.1:18765/agents/mock-1/cancel
```

**Errors:**
- `404`: Agent not found

### Provide Input to Agent

Send input text to an agent.

**Endpoint:** `POST /agents/{agent_id}/input`

**Request Body:**
```json
{
  "text": "User input text"
}
```

**Response:**
```json
{"status": "input_sent"}
```

**Example:**
```bash
curl -X POST http://127.0.0.1:18765/agents/mock-1/input \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello agent"}'
```

**Errors:**
- `404`: Agent not found

### Register Agent

Register an external or mock agent.

**Endpoint:** `POST /agents/register`

**Request Body:**
```json
{
  "agent_id": "demo-1",
  "agent_type": "mock",
  "capabilities": ["accepts_text", "cancellable"],
  "project_root": "/tmp/deckhand-demo"
}
```

`agent_type` of `"mock"` creates a full MockAgent (start / cancel / input). Any other type creates a placeholder external agent. Prefer `deckhand agents demo` for Property Inspector testing.

**Errors:**
- `409`: Agent already registered

### Unregister Agent

**Endpoint:** `DELETE /agents/{agent_id}`

**Response:**
```json
{"status": "unregistered", "agent_id": "demo-1"}
```

## Actions

### List Actions

Get all registered actions with metadata.

**Endpoint:** `GET /actions`

**Response:**
```json
{
  "actions": [
    {
      "name": "agent.start",
      "description": "Start an agent by ID",
      "payload_schema": {
        "agent_id": {"type": "string", "required": true}
      }
    }
  ]
}
```

**Example:**
```bash
curl http://127.0.0.1:18765/actions
```

### Get Action Metadata

Get metadata for a specific action.

**Endpoint:** `GET /actions/{action_name}`

**Response:**
```json
{
  "name": "agent.start",
  "description": "Start an agent by ID",
  "payload_schema": {
    "agent_id": {"type": "string", "required": true}
  }
}
```

**Example:**
```bash
curl http://127.0.0.1:18765/actions/agent.start
```

**Errors:**
- `404`: Action not found

### Execute Action

Execute an action with payload.

**Endpoint:** `POST /actions/{action_name}`

**Request Body:**
```json
{
  "agent_id": "mock-1"
}
```

**Response:**
```json
{"status": "ok"}
```

**Example:**
```bash
curl -X POST http://127.0.0.1:18765/actions/agent.start \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "mock-1"}'
```

**Errors:**
- `404`: Action not found
- `400`: Validation error (missing required fields, invalid payload)

## Signals

### List Signals

Get all registered signals with metadata.

**Endpoint:** `GET /signals`

**Response:**
```json
{
  "signals": [
    {
      "name": "camera.motion",
      "description": "Handle camera motion detection webhook",
      "payload_schema": {
        "key": {"type": "string", "required": false},
        "active": {"type": "boolean", "required": false, "default": true}
      }
    }
  ]
}
```

**Example:**
```bash
curl http://127.0.0.1:18765/signals
```

### Get Signal Metadata

Get metadata for a specific signal.

**Endpoint:** `GET /signals/{signal_name}`

**Response:**
```json
{
  "name": "camera.motion",
  "description": "Handle camera motion detection webhook",
  "payload_schema": {
    "key": {"type": "string", "required": false},
    "active": {"type": "boolean", "required": false, "default": true}
  }
}
```

**Example:**
```bash
curl http://127.0.0.1:18765/signals/camera.motion
```

**Errors:**
- `404`: Signal not found

### Handle Webhook Signal

Ingest an external event via webhook.

**Endpoint:** `POST /signals/webhook/{signal_name}`

**Request Body:**
```json
{
  "key": "camera.front_door.motion",
  "active": true,
  "ttl_seconds": 30
}
```

**Response:**
```json
{"status": "ok"}
```

**Example:**
```bash
curl -X POST http://127.0.0.1:18765/signals/webhook/camera.motion \
  -H "Content-Type: application/json" \
  -d '{"key": "camera.front_door.motion", "active": true}'
```

**Errors:**
- `404`: Signal not found
- `400`: Validation error

## State

### List State

Get all state entries.

**Endpoint:** `GET /state`

**Response:**
```json
[
  {
    "key": "camera.front_door.motion",
    "value": {"active": true},
    "updated_at": 1234567890.0,
    "expires_at": 1234567920.0
  }
]
```

**Example:**
```bash
curl http://127.0.0.1:18765/state
```

### Get State

Get state for a specific key.

**Endpoint:** `GET /state/{state_key}`

**Response:**
```json
{
  "key": "camera.front_door.motion",
  "value": {"active": true},
  "updated_at": 1234567890.0,
  "expires_at": 1234567920.0
}
```

**Example:**
```bash
curl http://127.0.0.1:18765/state/camera.front_door.motion
```

**Errors:**
- `404`: State not found

## Events (WebSocket)

### Connect to Event Stream

Connect to real-time event stream via WebSocket.

**Endpoint:** `WS /events`

**Protocol:** WebSocket

**Message Format:** JSON event envelopes

**Example:**
```python
import asyncio
import websockets
import json

async def listen():
    uri = "ws://127.0.0.1:18765/events"
    async with websockets.connect(uri) as websocket:
        while True:
            event = await websocket.recv()
            data = json.loads(event)
            print(data)

asyncio.run(listen())
```

**Event Types:**
- `state.changed`: State was updated
- `state.cleared`: State was cleared
- `agent.status_changed`: Agent status changed
- `ui.open_url`: Request to open URL
- `error`: Error occurred

See `docs/EVENTS.md` for complete event schema documentation.

## Error Responses

All endpoints may return standard HTTP error codes:

- `400 Bad Request`: Validation error (missing required fields, invalid payload)
- `404 Not Found`: Resource not found (agent, action, signal, state)
- `500 Internal Server Error`: Server error
- `503 Service Unavailable`: Service not initialized

Error responses include a JSON body:
```json
{
  "detail": "Error message"
}
```

Error events are also emitted via WebSocket with type `error`:
```json
{
  "type": "error",
  "source": {"kind": "api", "id": "actions.run"},
  "payload": {
    "error_type": "ValidationError",
    "message": "Missing required field: agent_id",
    "details": {"field": "agent_id"}
  },
  "ts": 1234567890.0,
  "version": "1.0"
}
```
