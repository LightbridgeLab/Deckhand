"""Pretty-printers for CLI output."""

from __future__ import annotations

import json
import sys
from typing import Any


def emit_json(data: Any) -> None:
    json.dump(data, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


def emit_error(message: str, *, exit_code: int = 1) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(exit_code)


def parse_payload(raw: str | None) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        emit_error(f"invalid JSON payload: {exc}")
    if not isinstance(parsed, dict):
        emit_error("payload must be a JSON object")
    return parsed
