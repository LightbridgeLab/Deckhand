#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"

# Connection settings (URL + API key) are resolved inside plugin.py — see
# client_config.py. Order of precedence: DECKHAND_URL / DECKHAND_API_KEY env
# vars → [client] section of the shared config.toml (./config.toml or
# ~/.config/deckhand/config.toml) → legacy deckhand.env (deprecated).

VENV="$DIR/.venv"
if [ ! -x "$VENV/bin/python3" ]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet aiohttp websockets
fi

exec "$VENV/bin/python3" "$DIR/plugin.py" "$@"
