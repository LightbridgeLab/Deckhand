#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"

# Load DECKHAND_URL and DECKHAND_API_KEY from deckhand.env (copy from deckhand.env.example).
if [ -f "$DIR/deckhand.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$DIR/deckhand.env"
  set +a
fi

VENV="$DIR/.venv"
if [ ! -x "$VENV/bin/python3" ]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet aiohttp websockets
fi

exec "$VENV/bin/python3" "$DIR/plugin.py" "$@"
