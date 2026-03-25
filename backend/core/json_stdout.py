"""Small IO helpers for consistent stdout JSON printing across CLI utilities.

Use `print_json_stdout()` for machine-readable JSON output so it can be
centralized (pretty-printing, encoding, future JSONL adaptation) while
still writing to stdout for pipelines. This module keeps minimal imports so
it remains safe to import from CLI scripts.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)


def print_json_stdout(
    obj: Any, *, pretty: bool = False, ensure_ascii: bool = False
) -> None:
    """Serialize `obj` to JSON and write to stdout.

    This helper centralizes JSON formatting and flushing behavior. It logs a
    debug entry and writes the JSON to stdout (so downstream pipes remain
    compatible). Use `pretty=True` for human-readable CLI output.
    """
    txt = format_json(obj, pretty=pretty, ensure_ascii=ensure_ascii)
    try:
        sys.stdout.write(txt + "\n")
        sys.stdout.flush()
    except Exception:
        logger.exception("Failed to write JSON to stdout")


def format_json(obj: Any, *, pretty: bool = False, ensure_ascii: bool = False) -> str:
    """Return a JSON-formatted string for `obj`.

    This is the pure formatting counterpart to `print_json_stdout` and is
    useful for unit testing and code that prefers to receive the formatted
    value instead of writing to stdout directly.
    """
    try:
        if pretty:
            return json.dumps(obj, indent=2, ensure_ascii=ensure_ascii, default=str)
        return json.dumps(
            obj, separators=(",", ":"), ensure_ascii=ensure_ascii, default=str
        )
    except Exception:
        logger.exception("Failed to serialize object to JSON")
        return repr(obj)
