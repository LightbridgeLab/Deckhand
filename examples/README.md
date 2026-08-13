# Deckhand Examples

Reference configuration for wiring coding agents into Deckhand.

**Prefer the installer** for first-party tools:

```bash
uv run deckhand hooks install          # Claude Code + Cursor
uv run deckhand hooks status
```

Hand-edited templates (same shape install writes; replace `DECKHAND_BIN` with an absolute path if merging manually):

- **`claude_code_hooks.json`** — Claude Code → `~/.claude/settings.json`
- **`cursor_hooks.json`** — Cursor → `~/.cursor/hooks.json`

Session setup (what a “live session” is, Codex / Antigravity register examples, verify steps): [docs/SESSION_HOOKS.md](../docs/SESSION_HOOKS.md).

For writing your own server-side plugin (custom actions, signals, state, or pollers), see [docs/PLUGIN_GUIDE.md](../docs/PLUGIN_GUIDE.md). For the OpenDeck plugin (Stream Deck bridge), see [opendeck-plugin/](../opendeck-plugin/).
