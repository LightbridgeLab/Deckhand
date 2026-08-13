# Session hooks — live agents on Stream Deck

Agent Status, Agent Slot, and Agent Dashboard show **live coding sessions**, not installed apps and not usage-bar widgets.

A session appears in Deckhand only after a coding agent **pings** the local Core service. When the session ends, the agent is unregistered and drops out of the dropdown. Open IDE windows alone are never listed.

## Two separate loops

| Goal | What you need |
|------|----------------|
| **Usage button** (plan %) | Enable a usage plugin → bind a Data Widget. **No session hooks.** |
| **Session button** (status / focus / input) | Install hooks (or register) → start a session → bind Agent Status / Slot / Dashboard. |

## First-party: one-command install

Claude Code and Cursor have full lifecycle adapters (status transitions, session end, focus where supported).

From a Deckhand checkout (after `uv sync`), prefix with `uv run`. There is no `uvw` wrapper.

```bash
# Core must be running (make dev / make start)
uv run deckhand hooks install          # both Claude Code + Cursor
# or: uv run deckhand hooks install claude-code
# or: uv run deckhand hooks install cursor

uv run deckhand hooks status           # Core up? hooks present? last ingest error?
```

`hooks install` merges Deckhand entries into:

- Claude Code: `~/.claude/settings.json`
- Cursor: `~/.cursor/hooks.json`

It writes an **absolute path** to the `deckhand` binary **and** `--config /abs/path/to/config.toml`. Agent hosts run hooks with cwd = your coding project, not the Deckhand checkout — without `--config`, ingest has no API key and Core returns `401 Missing API key`. Re-run `uv run deckhand hooks install` from the repo after changing this.

Do not put `DECKHAND_API_KEY` in the hook command; the key stays in `config.toml`.

Then:

1. Start a session in that tool.
2. `deckhand agents list` — or click **Refresh** on Agent Status.
3. Pick the session on the button.

### Try the button without IDE hooks

```bash
uv run deckhand agents demo            # registers mock agent demo-1
# … Refresh Agent Status, press the button …
uv run deckhand agents demo --remove
```

### What the hooks run

Each agent event pipes JSON on stdin to:

```text
/abs/path/to/deckhand --config /abs/path/to/config.toml hooks ingest claude-code
/abs/path/to/deckhand --config /abs/path/to/config.toml hooks ingest cursor --event sessionStart
```

Ingest failures are logged to `~/.deckhand/hooks.log` and exit 0 so they do not break the coding session. Use `uv run deckhand hooks status` to see the last error.

Reference JSON (same shape install writes): [`examples/claude_code_hooks.json`](../examples/claude_code_hooks.json), [`examples/cursor_hooks.json`](../examples/cursor_hooks.json).

## Other agents (examples, not a support matrix)

Full status lifecycle (running / awaiting input / session end) is **first-party for Claude Code and Cursor only**. Other tools can still put a row in the Agent Status dropdown by registering on session start.

**Contract:** on session start, `POST /agents/register` with a JSON body:

```json
{
  "agent_id": "codex-abc12345",
  "agent_type": "codex",
  "project_root": "/path/to/project"
}
```

Use a write-scoped API key (`Authorization: Bearer …`). The agent stays until you `DELETE /agents/{agent_id}` (or Core restarts without persistence). Status stays a simple placeholder unless you build a dedicated adapter.

### Codex (example — register only)

Codex CLI hooks live in `~/.codex/hooks.json` (feature may need enabling in Codex config). Example SessionStart command shape:

```bash
# Illustrative — map Codex stdin fields to agent_id / project_root for your version
jq -c '{agent_id: ("codex-" + .session_id[0:8]), agent_type: "codex", project_root: .cwd}' \
  | curl -sS -X POST "${DECKHAND_URL:-http://127.0.0.1:18765}/agents/register" \
      -H "Authorization: Bearer ${DECKHAND_API_KEY}" \
      -H 'Content-Type: application/json' \
      --data-binary @-
```

Prefer wrapping that in a small script that reads `config.toml` like `deckhand hooks ingest` does. Deckhand does not ship a Codex adapter.

### Antigravity (example — register only)

Antigravity / `agy` looks for hooks in `~/.gemini/config/hooks.json` or workspace `.agents/hooks.json`. Upstream support differs between CLI and IDE builds — verify hooks actually fire in your build before relying on them.

Same register contract as above with `agent_type: "antigravity"`. Usage bars (`usage.antigravity.*`) are a separate plugin and do not require session hooks.

### Anything else

If the tool can run a shell command on session start with JSON on stdin, point it at `POST /agents/register`. We will not document every coding agent.

## Verify

```bash
uv run deckhand hooks status
uv run deckhand agents list
# Agent Status Property Inspector → Refresh
```

| Symptom | Likely fix |
|---------|------------|
| Could not reach Deckhand | Start Core (`make dev` / `make start`) |
| No live sessions | `uv run deckhand hooks install`, start a session, or `uv run deckhand agents demo` |
| Hooks installed, still empty | `hooks status` → last ingest error; `401 Missing API key` means re-run `hooks install` so commands include `--config` |
| Session vanished | Normal — session ended; start again and Refresh |
