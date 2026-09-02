# Getting started

This guide gets Deckhand Core, the OpenDeck plugin, and your first usage button running.

## 1. Install Core

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/LightbridgeLab/Deckhand && cd Deckhand
uv sync --all-extras
make config                              # copies config.example.toml → config.toml if missing
```

Edit `config.toml`. At minimum, enable one usage plugin under `[plugins].modules`:

```toml
[plugins]
modules = [
  "deckhand.plugins.claude_code_usage",
]
```

Copy the `[catalog.state_keys]` block from `config.example.toml` if your dropdown is empty, or run `uv run deckhand catalog sync` after Core is up.

Start Core:

```bash
make dev                                 # foreground + hot reload
# or: make start / make stop / make status   # background (PID + log under .deckhand/)
# optional: make menubar                 # macOS menu-bar app for start/stop/health
```

On first start, Core auto-generates a write-scoped API key and logs it. Set `[auth].api_keys` in `config.toml` to persist a key you control.

## 2. Install the OpenDeck plugin

```bash
make opendeck-plugin-install
```

Restart OpenDeck fully (quit + reopen). A **Deckhand** category should appear.

The plugin reads connection settings in this order:

1. `DECKHAND_URL` / `DECKHAND_API_KEY` env vars
2. `~/.config/deckhand/runtime.toml` (written by Core on startup — preferred while Core is running)
3. `[client]` section in `config.toml`
4. Legacy `deckhand.env` next to the plugin (deprecated)

For OpenDeck-only installs (no service checkout), put config at `~/.config/deckhand/config.toml`:

```toml
[client]
url = "http://127.0.0.1:18765"
api_key = "your-write-key"             # same as one of [auth].api_keys
```

## 3. First usage button

1. Drag **Data Widget** onto a button.
2. In the Property Inspector, pick a state key (sorted by `dropdown_label`).
3. Set display format to `percentage` for usage bars.
4. Stay signed in to the provider (e.g. `claude auth login` for Claude Code).

Within ~60 seconds the button should show live plan usage. Press the button to briefly flash time-until-reset (`Xd Yh` or `Xh Ym`); duration is `[client].usage_reset_flash_seconds` (default 5).

If the dropdown is empty: copy `[catalog.state_keys]` from `config.example.toml`, or run `uv run deckhand catalog sync`, then click **Refresh**.

See [USAGE.md](USAGE.md) for all provider keys and formats.

## 4. Optional: live sessions

Usage widgets do **not** need session hooks. For Agent Status / Slot / Dashboard:

```bash
uv run deckhand hooks install
uv run deckhand hooks status
```

Start a Claude Code or Cursor session, then bind **Agent Status**. Full guide: [SESSION_HOOKS.md](SESSION_HOOKS.md).

Try without IDE hooks: `uv run deckhand agents demo`

## Configuration reference

`config.example.toml` is the annotated reference for every section. Common overrides:

| Setting | Env var | Default |
|---------|---------|---------|
| Listen host | `DECKHAND_HOST` | `127.0.0.1` |
| Listen port | `DECKHAND_PORT` | `18765` |
| Runtime URL file | `DECKHAND_RUNTIME_FILE` | `~/.config/deckhand/runtime.toml` |
| API key | `DECKHAND_API_KEY` | auto-generated at startup |
| Config file | `DECKHAND_CONFIG_FILE` | `./config.toml`, then `~/.config/deckhand/config.toml` |

## CLI smoke test

```bash
uv run deckhand state list
uv run deckhand state watch usage.claude_code.session
uv run deckhand agents list
uv run deckhand hooks status
```

## Next steps

- [Usage widgets](USAGE.md) — all plan-bar keys and peek behavior
- [Session hooks](SESSION_HOOKS.md) — Claude Code and Cursor lifecycle
- [Stream Deck profile ideas](CURSOR_STREAM_DECK_PROFILES.md) — example button layouts
- [OpenDeck plugin](../opendeck-plugin/README.md) — action settings and development
