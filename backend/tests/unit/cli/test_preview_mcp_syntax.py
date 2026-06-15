"""MCP JSON syntax extras for activity cards."""

from __future__ import annotations

import json

import pytest
from rich.syntax import Syntax

from backend.cli.tool_display import preview as mcp_preview
from backend.cli.tool_display.preview import mcp_result_syntax_extras


def test_mcp_result_syntax_extras_returns_none_when_not_verbose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_preview, '_VERBOSE_MCP_JSON', False)
    large = json.dumps({'items': [{'id': i, 'name': f'x{i}'} for i in range(40)]})
    assert mcp_result_syntax_extras(large) is None


def test_mcp_result_syntax_extras_returns_none_for_small_when_verbose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_preview, '_VERBOSE_MCP_JSON', True)
    small = json.dumps({'a': 1})
    assert mcp_result_syntax_extras(small) is None


def test_mcp_result_syntax_extras_for_large_json_when_verbose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_preview, '_VERBOSE_MCP_JSON', True)
    payload = json.dumps({'items': [{'id': i, 'name': f'x{i}'} for i in range(40)]})
    extras = mcp_result_syntax_extras(payload)
    assert extras is not None
    assert len(extras) == 1
    assert isinstance(extras[0], Syntax)


def test_mcp_result_user_preview_summarizes_github_envelope_json() -> None:
    inner = json.dumps(
        {'total_count': 55, 'items': [{'full_name': 'a/b'}, {'full_name': 'c/d'}]}
    )
    envelope = json.dumps({'meta': None, 'content': [{'type': 'text', 'text': inner}]})
    preview = mcp_preview.mcp_result_user_preview(envelope, max_len=500)
    assert '55 repos' in preview
    assert 'a/b' in preview
