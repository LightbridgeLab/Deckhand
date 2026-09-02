# Stream Deck profile ideas

Example OpenDeck layouts for Cursor and multi-agent workflows. Adapt to your hardware — you do not need an Ajazz 15 or Elgato 6.

OpenDeck uses **profiles + Switch Profile** (not Elgato-style folders). Organize profiles with a folder prefix in the profile name, e.g. `Home/Compact` and `Cursor/Agents`.

## Example: 15-key deck (3×5) — Cursor sessions

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

### Optional display column

Use **Data Widget** actions on a non-interactive column:

| State key | Display format | Shows |
|-----------|----------------|-------|
| `cursor.summary` | `summary` | e.g. `4> 1?` |
| `usage.cursor.models` | `percentage` | Cursor Models pool |

`cursor.summary` is written automatically when Cursor agents register or change status.

## Example: 6-key deck — compact glance

**Profile:** `Home/Compact`

```
[ Dashboard ] [ → Cursor ] [ usage ] [ other ] [ other ] [ other ]
```

| Button | Action | Settings |
|--------|--------|----------|
| Dashboard | **Agent Dashboard** | `agent_filter`: `cursor` |
| → Cursor | **Switch Profile** | Target: `Cursor/Agents` on a larger deck, or a mini layout below |
| usage | **Data Widget** | `usage.cursor.models`, format `percentage` |

**Mini Cursor view** (optional second profile on the 6-key deck):

```
[ Dashboard ] [ Slot 1 ] [ Slot 2 ] [ Slot 3 ] [ Slot 4 ] [ Back ]
```

Use **Agent Slot** with `slot_index` 1–4 and `agent_filter`: `cursor`.

## Press behavior summary

| Action | When | Press |
|--------|------|-------|
| **Agent Dashboard** | Any `awaiting_input` or `error` | Focus highest-priority agent (`ui.focus_cursor_agent` for Cursor) |
| **Agent Dashboard** | Otherwise | Refresh summary |
| **Agent Slot** | Cursor agent bound | Focus that agent in Cursor |
| **Agent Slot** | Other agent types | Start / cancel / input (same as Agent Status) |
| **Agent Slot** | Empty slot | No-op |

## Cursor hook setup

```bash
uv run deckhand hooks install cursor
uv run deckhand hooks status
```

Restart Cursor (or start a new agent session). See [SESSION_HOOKS.md](SESSION_HOOKS.md).

Test without hardware:

```bash
echo '{"session_id":"abcdef0123456789","hook_event_name":"sessionStart","cwd":"/tmp"}' \
  | uv run deckhand hooks simulate cursor
```

## Limitations

- **Tab focus:** v1 opens the project folder in Cursor. Tab-level focus may require a future Cursor API ([#24](https://github.com/LightbridgeLab/Deckhand/issues/24)).
- **Cloud agents:** Register as `cursor_cloud` type with the same status model; slots filter with `agent_filter`: `cursor` or `*`.
