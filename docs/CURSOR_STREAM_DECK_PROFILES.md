# Cursor Stream Deck profiles

OpenDeck uses **profiles + Switch Profile** (not Elgato-style folders). Organize profiles with a folder prefix in the profile name, e.g. `Home/Compact` and `Cursor/Agents`.

## Ajazz 15 (3×5 interactive) — primary Cursor surface

**Profile:** `Cursor/Agents`

```
[ ← Home ] [ Slot 1 ] [ Slot 2 ] [ Slot 3 ] [ Slot 4 ] [ Slot 5 ]
[  More→ ] [ Slot 6 ] [ Slot 7 ] [  —   ] [  —   ] [  —   ]
```

| Button | Action | Settings |
|--------|--------|----------|
| ← Home | OpenDeck **Switch Profile** | Target: `Home/Compact` (or your home profile) |
| Slot 1–7 | **Agent Slot** | `slot_index` 1–7, `agent_filter`: `cursor`, `page`: 1 |
| More→ | **Switch Profile** | Target: `Cursor/Agents Page 2` |
| Empty slots | *(none)* | Leave blank or static `—` image |

**Page 2** (`Cursor/Agents Page 2`): slots 8–14 with `page`: 2 and `slot_index` 1–7.

### Display column (non-interactive)

Use **Data Widget** actions (display only on your Ajazz non-clickable column):

| State key | Display format | Shows |
|-----------|----------------|-------|
| `cursor.summary` | `summary` (or raw → `title` field) | e.g. `4> 1?` |
| `cursor.usage` | `percentage` or `raw` | Usage stats (manual / future API) |

`cursor.summary` is written automatically when Cursor agents register or change status.

## Elgato 6 — compact glance + entry

**Profile:** `Home/Compact`

```
[ Dashboard ] [ → Cursor ] [ HA / other ] [ other ] [ other ] [ other ]
```

| Button | Action | Settings |
|--------|--------|----------|
| Dashboard | **Agent Dashboard** | `agent_filter`: `cursor` |
| → Cursor | **Switch Profile** | Target: `Cursor/Agents` on Ajazz device profile, or a 3-slot mini layout on this deck |

**Mini Cursor view** (optional second profile on the 6-key deck):

```
[ Dashboard ] [ Slot 1 ] [ Slot 2 ] [ Slot 3 ] [ Slot 4 ] [ Back ]
```

Use **Agent Slot** with `slot_index` 1–4 and `agent_filter`: `cursor`. No separate back button needed if this profile is dedicated to Cursor.

## Press behavior summary

| Action | When | Press |
|--------|------|-------|
| **Agent Dashboard** | Any `awaiting_input` or `error` | Focus highest-priority agent (`ui.focus_cursor_agent` for Cursor) |
| **Agent Dashboard** | Otherwise | Refresh summary |
| **Agent Slot** | Cursor agent bound | Focus that agent in Cursor (macOS: `open -a Cursor <project>`) |
| **Agent Slot** | Other agent types | Start / cancel / input (same as Agent Status) |
| **Agent Slot** | Empty slot | No-op |

## Cursor hook setup

```bash
uv run deckhand hooks install cursor
uv run deckhand hooks status
```

Restart Cursor (or start a new agent session). Sessions appear as `cursor-{session_id[:8]}`. Install writes an absolute `deckhand` path so Cursor.app does not need shell `PATH` / env vars. See [SESSION_HOOKS.md](SESSION_HOOKS.md).

Test without hardware:

```bash
echo '{"session_id":"abcdef0123456789","hook_event_name":"sessionStart","cwd":"/tmp"}' \
  | uv run deckhand hooks simulate cursor
```

## v1.1 (experimental)

- **Tab focus:** True agent-tab selection in Cursor is not documented via deeplinks today. v1 opens the project folder in Cursor. Tab-level focus may require AppleScript or a future Cursor API.
- **Cloud agents:** Register as `cursor_cloud` type with the same status model; slots filter with `agent_filter`: `cursor` or `*`.
