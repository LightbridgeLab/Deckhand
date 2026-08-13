#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"

# Connection settings (URL + API key) are resolved inside plugin.py — see
# client_config.py. Order of precedence: DECKHAND_URL / DECKHAND_API_KEY env
# vars → live ~/.config/deckhand/runtime.toml → [client] in config.toml →
# legacy deckhand.env (deprecated).

VENV="$DIR/.venv"
if [ ! -x "$VENV/bin/python3" ]; then
  python3 -m venv "$VENV"
fi

# Ensure deps exist even when a stale/empty venv is already present.
if ! "$VENV/bin/python3" -c "import aiohttp, websockets" 2>/dev/null; then
  "$VENV/bin/pip" install --quiet aiohttp websockets
fi

exec "$VENV/bin/python3" "$DIR/plugin.py" "$@"
