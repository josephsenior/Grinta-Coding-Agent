from __future__ import annotations

import json

import pytest

from backend.core.tool_arguments_json import parse_tool_arguments_object


def test_valid_object_round_trips() -> None:
    raw = '{"command": "create_file", "path": "x.txt", "file_text": "hello"}'
    assert parse_tool_arguments_object(raw) == {
        'command': 'create_file',
        'path': 'x.txt',
        'file_text': 'hello',
    }


def test_invalid_json_escape_repaired() -> None:
    """Stdlib JSON rejects some escapes that models emit inside embedded code strings."""
    bad = r'{"file_text": "rgba(0,0,0,0.5) \("}'
    with pytest.raises(json.JSONDecodeError):
        json.loads(bad)
    out = parse_tool_arguments_object(bad)
    assert isinstance(out, dict)
    assert 'file_text' in out


def test_non_object_rejected() -> None:
    with pytest.raises(TypeError, match='JSON object'):
        parse_tool_arguments_object('[1, 2]')
