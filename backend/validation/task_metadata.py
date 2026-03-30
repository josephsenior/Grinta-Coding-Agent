"""Optional structured fields embedded in the first user message.

Clients may prefix the task with a single-line JSON object so validators can
avoid guessing from prose.

Format (first line only)::

    APP_TASK_JSON:{"expected_output_files":["out.txt","report.md"]}

Everything after the first newline is the human-readable ``Task.description``.
If the prefix is missing or JSON is invalid, the full string is treated as
description and no structured fields apply.
"""

from __future__ import annotations

import json
from typing import Any

APP_TASK_JSON_PREFIX = "APP_TASK_JSON:"


def parse_task_from_user_message(content: str) -> tuple[str, dict[str, Any]]:
    """Split user message into description and optional structured metadata.

    Returns:
        ``(description, meta_dict)``. ``meta_dict`` is empty when unset.
    """
    if not content:
        return "", {}

    stripped = content.lstrip("\ufeff")
    if not stripped.startswith(APP_TASK_JSON_PREFIX):
        return content, {}

    rest = stripped[len(APP_TASK_JSON_PREFIX) :]
    newline = rest.find("\n")
    if newline == -1:
        json_line, body = rest, ""
    else:
        json_line, body = rest[:newline], rest[newline + 1 :]

    json_line = json_line.strip()
    if not json_line:
        return body if body else content, {}

    try:
        meta = json.loads(json_line)
    except json.JSONDecodeError:
        return content, {}

    if not isinstance(meta, dict):
        return content, {}

    return (body if body else "").strip() or content, meta
