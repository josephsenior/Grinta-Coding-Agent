"""Tests for persistent LSP sessions and timeout profiles."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.utils.http.stdio_json_rpc import (
    encode_json_rpc_message,
    feed_content_length_buffer,
)
from backend.utils.lsp.lsp_project_routing import LspFileContext
from backend.utils.lsp.lsp_session import LspSession, LspSessionPool, reset_lsp_session_pool
from backend.utils.lsp.lsp_timeouts import (
    effective_query_timeout,
    init_timeout_for_server,
    query_timeout_for_server,
)


def test_encode_and_feed_content_length_buffer_roundtrip() -> None:
    message = {'jsonrpc': '2.0', 'id': 7, 'result': {'ok': True}}
    framed = encode_json_rpc_message(message)
    parsed, leftover = feed_content_length_buffer(framed)
    assert leftover == b''
    assert len(parsed) == 1
    assert parsed[0]['id'] == 7


def test_feed_content_length_buffer_handles_partial_frame() -> None:
    message = {'jsonrpc': '2.0', 'id': 1, 'result': 1}
    framed = encode_json_rpc_message(message)
    half = len(framed) // 2
    parsed, leftover = feed_content_length_buffer(framed[:half])
    assert parsed == []
    assert leftover == framed[:half]
    parsed2, leftover2 = feed_content_length_buffer(leftover + framed[half:])
    assert [m['id'] for m in parsed2] == [1]
    assert leftover2 == b''


def test_slow_server_timeouts() -> None:
    assert query_timeout_for_server('jdtls') == 45.0
    assert init_timeout_for_server('metals') == 60.0
    assert query_timeout_for_server('rust-analyzer') == 15.0


def test_effective_query_timeout_post_edit_floor() -> None:
    assert effective_query_timeout('jdtls', 3.0, post_edit=True) == 12.0
    assert effective_query_timeout('rust-analyzer', 3.0, post_edit=True) == 3.0
    assert effective_query_timeout('jdtls', None) == 45.0


def test_lsp_session_pool_reuses_alive_session(tmp_path: Path) -> None:
    reset_lsp_session_pool()
    ctx = LspFileContext(
        server_name='rust-analyzer',
        command=('rust-analyzer',),
        language_id='rust',
        workspace_root=tmp_path,
    )
    pool = LspSessionPool()
    mock_session = MagicMock()
    mock_session.is_alive.return_value = True

    with patch('backend.utils.lsp.lsp_session.LspSession', return_value=mock_session):
        first = pool.get(ctx)
        second = pool.get(ctx)

    assert first is mock_session
    assert second is mock_session
    assert mock_session.start.call_count == 1


def test_lsp_session_wait_publish_diagnostics() -> None:
    ctx = LspFileContext(
        server_name='rust-analyzer',
        command=('rust-analyzer',),
        language_id='rust',
        workspace_root=Path('.'),
    )
    session = LspSession(ctx)
    uri = 'file:///tmp/a.rs'
    payload = {
        'jsonrpc': '2.0',
        'method': 'textDocument/publishDiagnostics',
        'params': {
            'uri': uri,
            'diagnostics': [
                {
                    'range': {
                        'start': {'line': 0, 'character': 0},
                        'end': {'line': 0, 'character': 1},
                    },
                    'message': 'unused',
                    'severity': 2,
                }
            ],
        },
    }
    session._inbox.put(payload)  # noqa: SLF001
    diags = session.wait_publish_diagnostics(uri, timeout=0.5)
    assert len(diags) == 1
    assert diags[0]['message'] == 'unused'
