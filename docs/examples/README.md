# Hook configuration templates

Reference JSON for wiring coding agents into Deckhand. Prefer the installer for first-party tools:

```bash
uv run deckhand hooks install          # Claude Code + Cursor
uv run deckhand hooks status
```

Hand-edited templates (same shape install writes; replace `DECKHAND_BIN` with an absolute path if merging manually):

- **`claude_code_hooks.json`** — Claude Code → `~/.claude/settings.json`
- **`cursor_hooks.json`** — Cursor → `~/.cursor/hooks.json`

Session setup and verify steps: [SESSION_HOOKS.md](../SESSION_HOOKS.md).

For Core plugins (custom actions, signals, state): [PLUGIN_GUIDE.md](../PLUGIN_GUIDE.md). For the OpenDeck bridge: [opendeck-plugin/README.md](../../opendeck-plugin/README.md).
