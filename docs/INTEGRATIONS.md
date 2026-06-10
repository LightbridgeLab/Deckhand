# External integrations (signals & state)

Deckhand separates **agents** from **everything else**:

| Source type | Core path | Stream Deck action |
|-------------|-----------|-------------------|
| Agents (Claude Code, mock, etc.) | Agent registry → `agent.status_changed` | **Agent Status** / **Agent Dashboard** |
| Sensors, HA, RSS, cameras, etc. | Plugin **signals** → **state** → `state.changed` | **Data Widget** (or **Signal Trigger** to fire signals on press) |

Non-agent integrations should **not** use `agent.status_changed` or the Agent Status action. Normalize external data into **namespaced state keys**, then bind buttons to those keys.

See also: [Plugin Guide](PLUGIN_GUIDE.md), [Example plugin](../examples/example_plugin.py), builtin `camera.motion` in `deckhand.plugins.builtin`.

## State key naming

Use stable, hierarchical keys so Property Inspector autocomplete and debugging stay predictable:

| Pattern | Example | Use case |
|---------|---------|----------|
| `ha.{domain}.{entity_id}` | `ha.sensor.living_room_temp` | Home Assistant entity mirror |
| `camera.{name}.motion` | `camera.front_door.motion` | Motion / alert flags |
| `feed.{slug}` | `feed.hn_front_page` | RSS headline or metadata |
| `lights.{room}.state` | `lights.living_room.state` | On/off + brightness blob |

Store structured JSON in `value` (not only strings) so Data Widget `display_format` options (`boolean`, `number`, `percentage`, etc.) can format the title.

Always pass `source` when writing state:

```python
source={"kind": "signal", "id": "ha.entity_changed"}
```

That attribution appears in `state.changed` events for debugging.

## Pattern A: Push webhook (Home Assistant)

**When to use:** An external system can HTTP POST to Deckhand when something changes (Home Assistant automations, webhooks from cameras, IFTTT, etc.).

**Flow:**

```mermaid
sequenceDiagram
  participant HA as Home Assistant
  participant DH as Deckhand Core
  participant SS as StateStore
  participant OD as OpenDeck Data Widget

  HA->>DH: POST /signals/webhook/{signal_name}
  DH->>SS: set_state(key, value)
  SS-->>OD: state.changed via WebSocket
  OD->>OD: Update button title
```

### 1. Register a signal in a plugin

Minimal handler (adapt entity id and fields to your needs):

```python
from __future__ import annotations

from typing import Any

from deckhand.plugins.registry import PluginRegistry


def register(registry: PluginRegistry) -> None:
    async def ha_entity_changed(payload: dict[str, Any]) -> None:
        entity_id = payload.get("entity_id")
        if not entity_id:
            raise ValueError("entity_id is required")

        entity_id = str(entity_id)
        state = payload.get("state")
        attributes = payload.get("attributes") or {}

        key = f"ha.{entity_id.replace('.', '_')}"
        await registry.state.set_state(
            key,
            {"state": state, "attributes": attributes},
            source={"kind": "signal", "id": "ha.entity_changed"},
        )

    registry.signals.register(
        "ha.entity_changed",
        ha_entity_changed,
        description="Mirror a Home Assistant entity state into Deckhand",
        payload_schema={
            "entity_id": {"type": "string", "required": True},
            "state": {"type": "string", "required": False},
            "attributes": {"type": "object", "required": False},
        },
    )
```

Add your module to `config.toml`:

```toml
[plugins]
modules = ["deckhand.plugins.builtin", "my_ha_plugin"]
```

Restart Deckhand Core.

### 2. Call the webhook from Home Assistant

In an automation or script, POST JSON to Deckhand (replace host, key, and payload):

```yaml
action: rest_command.deckhand_ha_entity
```

Define `rest_command` in `configuration.yaml`:

```yaml
rest_command:
  deckhand_ha_entity:
    url: "http://127.0.0.1:8000/signals/webhook/ha.entity_changed"
    method: POST
    headers:
      Authorization: "Bearer YOUR_DECKHAND_WRITE_KEY"
      Content-Type: "application/json"
    payload: >
      {
        "entity_id": "{{ trigger.entity_id }}",
        "state": "{{ states(trigger.entity_id) }}",
        "attributes": {{ state_attr(trigger.entity_id) | tojson }}
      }
```

Trigger that `rest_command` from an automation on `state_changed` for the entities you care about.

**curl test (no HA required):**

```bash
curl -X POST \
  -H "Authorization: Bearer $DECKHAND_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"entity_id": "sensor.living_room_temperature", "state": "21.5", "attributes": {"unit_of_measurement": "°C"}}' \
  http://127.0.0.1:8000/signals/webhook/ha.entity_changed
```

Verify:

```bash
curl -H "Authorization: Bearer $DECKHAND_API_KEY" \
  http://127.0.0.1:8000/state/ha.sensor_living_room_temperature
```

### 3. Bind a Stream Deck button

1. Add a **Data Widget** action in OpenDeck.
2. Set **State key** to `ha.sensor_living_room_temperature` (or your key).
3. Choose a **Display format** (e.g. `raw` or `number` depending on your value shape).

The widget loads the current value on appear and updates on every matching `state.changed` event.

### Optional: custom events

If multiple buttons care about the same *room* or *area*, you can emit a domain event **in addition to** state (widgets only need state):

```python
from deckhand.orchestrator.events import build_event

await registry.events.emit(build_event(
    "ha.entity_changed",
    {"kind": "signal", "id": "ha.entity_changed"},
    {"entity_id": entity_id, "state": state},
))
```

Custom event types require client handlers; prefer **state-first** unless you add a dedicated OpenDeck action.

### HA without a custom plugin

For a one-off, you can POST to the built-in **`camera.motion`** signal if motion-style TTL behavior is enough:

```bash
curl -X POST -H "Authorization: Bearer $DECKHAND_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"key": "camera.garage.motion", "active": true, "ttl_seconds": 60}' \
  http://127.0.0.1:8000/signals/webhook/camera.motion
```

For arbitrary entity shapes, a small plugin signal is the right approach.

---

## Pattern B: Pull / poll (RSS feeds)

**When to use:** The source has no webhook (RSS, Atom, periodic REST poll, batch import). Deckhand does not ship a scheduler; the **plugin starts a background asyncio task** from `register()`.

**Flow:**

```mermaid
sequenceDiagram
  participant Task as Plugin background task
  participant Feed as RSS URL
  participant DH as Deckhand Core
  participant OD as OpenDeck Data Widget

  loop Every interval
    Task->>Feed: HTTP GET
    Feed-->>Task: XML / JSON
    Task->>DH: set_state(feed.slug, value)
    DH-->>OD: state.changed
  end
```

### 1. Plugin with a poller

Use `state-only` capability if the plugin only ingests and writes state (no custom actions). Example skeleton:

```python
from __future__ import annotations

import asyncio
import logging
from typing import Any
from xml.etree import ElementTree

import httpx

from deckhand.plugins.registry import PluginRegistry

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 300
FEEDS = [
    {"slug": "hn", "url": "https://hnrss.org/frontpage"},
]


def register(registry: PluginRegistry) -> None:
    async def poll_feeds() -> None:
        while True:
            for spec in FEEDS:
                slug = spec["slug"]
                url = spec["url"]
                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        response = await client.get(url)
                        response.raise_for_status()
                    root = ElementTree.fromstring(response.text)
                    channel = root.find("channel")
                    item = channel.find("item") if channel is not None else None
                    title_el = item.find("title") if item is not None else None
                    title = (title_el.text or "").strip() if title_el is not None else ""
                    await registry.state.set_state(
                        f"feed.{slug}",
                        {"title": title, "url": url},
                        source={"kind": "plugin", "id": "rss_poller"},
                    )
                except Exception:
                    logger.exception("RSS poll failed for %s", slug)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    # Fire-and-forget background loop (see caveats below).
    # register() runs during service startup when the event loop is active.
    asyncio.create_task(poll_feeds())
```

**Dependencies:** Add `httpx` to your environment if not already present (`uv add httpx` in the Deckhand project, or install in the same venv that runs Core).

**Capability in config:**

```toml
[plugins]
modules = [
  "deckhand.plugins.builtin",
  { module = "my_rss_plugin", capability = "state-only" },
]
```

Or env: `DECKHAND_PLUGINS=my_rss_plugin:state-only`

### 2. Bind a Data Widget

- **State key:** `feed.hn`
- **Display format:** `raw` (shows formatted title from the value dict; adjust `_format_value` behavior via structured fields)

Press actions are optional: use **Run Action** or **Signal Trigger** on another button if you want to refresh on demand (call a separate `rss.refresh` action that performs one poll synchronously).

### 3. Caveats (current platform)

| Topic | Status |
|-------|--------|
| Background task lifecycle | Tasks started in `register()` are **not** stopped cleanly on service shutdown yet — see [ROADMAP.md](../ROADMAP.md) (plugin shutdown hook) |
| Error handling | Log and continue; avoid crashing the whole service on one bad feed |
| Interval / backoff | Implement in the plugin; core does not enforce rate limits |
| Duplicate polls | Use a single task per plugin, not one task per feed registration call |

For production RSS plugins, consider:

- Jitter on the sleep interval so restarts do not align all feeds
- ETag / `If-Modified-Since` if the feed supports it
- Writing `{"title": "", "error": "..."}` on failure so the button shows a visible failure state

---

## OpenDeck actions cheat sheet

| Goal | Action | Settings |
|------|--------|----------|
| Show live HA / RSS / sensor value | **Data Widget** | `state_key`, `display_format` |
| Flash motion then auto-clear | Built-in `camera.motion` signal + widget on same key | `ttl_seconds` in webhook payload |
| Fire webhook from a button | **Signal Trigger** | Signal name + JSON payload |
| Run Deckhand action on press | **Run Action** | Action name + payload |
| Show agent status | **Agent Status** | `agent_id` — **not** for HA/RSS |

## Auth

All webhook and action calls require a **write** API key:

```http
Authorization: Bearer <DECKHAND_API_KEY>
```

Use the same key in Home Assistant `rest_command` headers and in `.env` / `config.toml`. See [API.md](API.md) for scopes.

## Related examples

- **Push + state:** `lights.status_webhook` in [examples/example_plugin.py](../examples/example_plugin.py)
- **Push + TTL:** `camera.motion` in `src/deckhand/plugins/builtin.py`
- **CLI:** `deckhand signals fire <name> --payload '{...}'` for ad-hoc testing without OpenDeck.
