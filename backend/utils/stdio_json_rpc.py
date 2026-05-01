"""Parse JSON-RPC / DAP / LSP messages using ``Content-Length`` header framing.

Both LSP batch subprocess output and related tooling share the same header/body
layout; keep one parser so behavior stays consistent.
"""

from __future__ import annotations

import json
from typing import Any


def parse_content_length_json_messages(raw: str) -> list[dict[str, Any]]:
    """Extract JSON objects from a complete stdout/stderr buffer.

    Scans for ``Content-Length: N`` headers followed by ``\\r\\n\\r\\n`` and a
    body of *N* bytes, then ``json.loads`` each body. Malformed chunks are
    skipped without raising.
    """
    responses: list[dict[str, Any]] = []
    buf = raw
    i = 0
    n = len(buf)
    while i < n:
        cl_pos = buf.find('Content-Length:', i)
        if cl_pos == -1:
            break
        line_end = buf.find('\r\n', cl_pos)
        if line_end == -1:
            break
        header_line = buf[cl_pos:line_end]
        lower = header_line.strip().lower()
        if not lower.startswith('content-length:'):
            i = cl_pos + 1
            continue
        try:
            length = int(header_line.split(':', 1)[1].strip())
        except ValueError:
            i = line_end + 2
            continue
        sep = buf.find('\r\n\r\n', line_end)
        if sep == -1:
            break
        body_start = sep + 4
        body_end = body_start + length
        if body_end > n:
            break
        chunk = buf[body_start:body_end]
        try:
            responses.append(json.loads(chunk))
        except Exception:
            pass
        i = body_end
    return responses


__all__ = ['parse_content_length_json_messages']
