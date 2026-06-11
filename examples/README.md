# Deckhand Examples

Reference configuration files for wiring Deckhand into the supported agent runtimes.

- **`claude_code_hooks.json`** — Claude Code hook configuration that forwards session lifecycle events (start, awaiting input, stop) to Deckhand. Drop into `~/.claude/settings.json` (or merge with an existing file).
- **`cursor_hooks.json`** — Cursor hook configuration with the same shape for Cursor sessions.

For writing your own server-side plugin (custom actions, signals, state, or pollers), see [docs/PLUGIN_GUIDE.md](../docs/PLUGIN_GUIDE.md). For the OpenDeck plugin (Stream Deck bridge), see [opendeck-plugin/](../opendeck-plugin/).
