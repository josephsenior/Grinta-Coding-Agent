from __future__ import annotations

import json

import pytest

import backend.core.tool_arguments_json as tool_arguments_json
from backend.core.tool_arguments_json import (
    TruncatedToolArgumentsError,
    parse_tool_arguments_object,
)


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


def test_non_string_input_rejected() -> None:
    with pytest.raises(TypeError, match='must be a string'):
        parse_tool_arguments_object({'command': 'create_file'})


def test_empty_string_rejected_after_strip() -> None:
    with pytest.raises(ValueError, match='empty'):
        parse_tool_arguments_object('   \n\t  ')


def test_truncated_object_raises_dedicated_error() -> None:
    raw = '{"command": "create_file", "file_text": "hello"'

    with pytest.raises(TruncatedToolArgumentsError, match='appear truncated'):
        parse_tool_arguments_object(raw)


def test_repaired_non_object_is_rejected() -> None:
    raw = '[1, 2,]'

    with pytest.raises(TypeError, match='JSON object'):
        parse_tool_arguments_object(raw)


def test_tuple_repair_result_is_unwrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tool_arguments_json,
        'repair_json',
        lambda _text: ('{"command": "create_file", "path": "x.txt"}', None),
    )

    parsed = parse_tool_arguments_object('{"command": create_file}')

    assert parsed == {'command': 'create_file', 'path': 'x.txt'}
