"""Pure MCP event helpers (no orchestrator dependency)."""

from __future__ import annotations

import json


def mcp_content_is_error(content: str) -> bool:
    s = (content or '').strip()
    if not s:
        return False
    if s.startswith('Error'):
        return True
    if s.startswith('{'):
        try:
            data = json.loads(s)
        except json.JSONDecodeError:
            return False
        if isinstance(data, dict) and (
            data.get('isError') or data.get('ok') is False
        ):
            return True
    return False
