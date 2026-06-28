"""Parse JSON-RPC / DAP / LSP messages using ``Content-Length`` header framing.

Both LSP batch subprocess output and related tooling share the same header/body
layout; keep one parser so behavior stays consistent.
"""

from __future__ import annotations

import json
from typing import Any


def parse_content_length_json_messages(raw: str) -> list[dict[str, Any]]:
    r"""Extract JSON objects from a complete stdout/stderr buffer.

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


def encode_json_rpc_message(message: dict[str, Any]) -> bytes:
    """Encode one JSON-RPC message with LSP Content-Length framing."""
    body = json.dumps(message, ensure_ascii=False).encode('utf-8')
    header = f'Content-Length: {len(body)}\r\n\r\n'.encode('ascii')
    return header + body


def feed_content_length_buffer(buf: bytes) -> tuple[list[dict[str, Any]], bytes]:
    """Parse complete framed messages from *buf* and return the leftover bytes."""
    responses: list[dict[str, Any]] = []
    i = 0
    n = len(buf)
    while i < n:
        cl_pos = buf.find(b'Content-Length:', i)
        if cl_pos == -1:
            break
        line_end = buf.find(b'\r\n', cl_pos)
        if line_end == -1:
            break
        header_line = buf[cl_pos:line_end].decode('ascii', errors='ignore')
        lower = header_line.strip().lower()
        if not lower.startswith('content-length:'):
            i = cl_pos + 1
            continue
        try:
            length = int(header_line.split(':', 1)[1].strip())
        except ValueError:
            i = line_end + 2
            continue
        sep = buf.find(b'\r\n\r\n', line_end)
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
    return responses, buf[i:]


__all__ = [
    'encode_json_rpc_message',
    'feed_content_length_buffer',
    'parse_content_length_json_messages',
]
