"""Unit tests for the JSON compatibility wrapper (stdlib vs orjson)."""

from __future__ import annotations

import io
import json as stdlib_json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import backend.core.json_compat as json_compat


# A helper to run test cases under both orjson available and unavailable states
@pytest.fixture(params=[True, False])
def mock_orjson_state(request: pytest.FixtureRequest) -> Any:
    state = request.param
    mock_orjson = MagicMock()
    # Mock behavior of orjson.dumps / orjson.loads
    mock_orjson.OPT_NON_STR_KEYS = 1
    mock_orjson.OPT_SORT_KEYS = 2
    mock_orjson.OPT_INDENT_2 = 4

    def dummy_dumps(obj: Any, default: Any = None, option: int = 0) -> bytes:
        # Dummy serialized bytes for check
        return stdlib_json.dumps(obj, sort_keys=bool(option & 2), indent=2 if (option & 4) else None).encode('utf-8')

    mock_orjson.dumps.side_effect = dummy_dumps
    mock_orjson.loads.side_effect = stdlib_json.loads

    with patch.object(json_compat, '_ORJSON_AVAILABLE', state), \
         patch.object(json_compat, '_orjson', mock_orjson):
        yield state, mock_orjson


def test_can_use_orjson_states(mock_orjson_state: tuple[bool, MagicMock]) -> None:
    orjson_available, _ = mock_orjson_state

    # Helper function to call _can_use_orjson with default options
    def check(
        ensure_ascii: bool = False,
        indent: int | None = None,
        separators: tuple[str, str] | None = None,
        cls: type[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> bool:
        return json_compat._can_use_orjson(
            ensure_ascii=ensure_ascii,
            indent=indent,
            separators=separators,
            cls=cls,
            kwargs=kwargs or {},
        )

    if not orjson_available:
        # Should always be False if orjson is not available
        assert check() is False
        return

    # If available, standard options should match
    assert check() is True

    # Bad options should cause fallback
    assert check(ensure_ascii=True) is False
    assert check(indent=4) is False
    assert check(separators=(', ', ' : ')) is False
    assert check(cls=stdlib_json.JSONEncoder) is False
    assert check(kwargs={'extra': 'arg'}) is False

    # Acceptable indent values (None, 2)
    assert check(indent=2) is True
    assert check(indent=None) is True

    # Acceptable separators (compact separators)
    assert check(separators=(',', ':')) is True


def test_dumps_fallback_parameters(mock_orjson_state: tuple[bool, MagicMock]) -> None:
    _, mock_orjson = mock_orjson_state
    data = {'a': 1, 'b': 2}

    # skipkeys=True should fall back to stdlib
    res = json_compat.dumps(data, skipkeys=True)
    assert 'a' in res
    assert not mock_orjson.dumps.called

    # check_circular=False should fall back to stdlib
    res = json_compat.dumps(data, check_circular=False)
    assert 'a' in res
    assert not mock_orjson.dumps.called

    # allow_nan=False should fall back to stdlib
    res = json_compat.dumps(data, allow_nan=False)
    assert 'a' in res
    assert not mock_orjson.dumps.called


def test_dumps_behavior(mock_orjson_state: tuple[bool, MagicMock]) -> None:
    orjson_available, mock_orjson = mock_orjson_state
    data = {'z': 26, 'a': 1}

    # Standard serialization
    # Standard json.dumps defaults to ensure_ascii=True, which falls back to stdlib
    res = json_compat.dumps(data)
    assert 'a' in res
    assert not mock_orjson.dumps.called

    # To potentially trigger orjson, we must pass ensure_ascii=False
    res_no_ascii = json_compat.dumps(data, ensure_ascii=False)
    if orjson_available:
        assert mock_orjson.dumps.called
        # Check option passes OPT_NON_STR_KEYS by default
        mock_orjson.dumps.assert_called_with(data, default=None, option=mock_orjson.OPT_NON_STR_KEYS)
    else:
        assert not mock_orjson.dumps.called
        assert 'z' in res_no_ascii


def test_dumps_with_sort_keys_and_indent(mock_orjson_state: tuple[bool, MagicMock]) -> None:
    orjson_available, mock_orjson = mock_orjson_state
    data = {'z': 26, 'a': 1}

    # Pass ensure_ascii=False to allow orjson
    json_compat.dumps(data, ensure_ascii=False, sort_keys=True, indent=2)
    if orjson_available:
        expected_option = mock_orjson.OPT_NON_STR_KEYS | mock_orjson.OPT_SORT_KEYS | mock_orjson.OPT_INDENT_2
        mock_orjson.dumps.assert_called_with(data, default=None, option=expected_option)
    else:
        assert not mock_orjson.dumps.called


def test_dump_writes_to_file(mock_orjson_state: tuple[bool, MagicMock]) -> None:
    data = {'hello': 'world'}
    fp = io.StringIO()
    json_compat.dump(data, fp)
    fp.seek(0)
    content = fp.read()
    assert 'hello' in content
    assert 'world' in content


def test_loads_behavior(mock_orjson_state: tuple[bool, MagicMock]) -> None:
    orjson_available, mock_orjson = mock_orjson_state
    json_str = '{"x": 100}'

    # Test loading string
    res = json_compat.loads(json_str)
    assert res == {'x': 100}
    if orjson_available:
        mock_orjson.loads.assert_called_with(json_str)
    else:
        assert not mock_orjson.loads.called

    # Reset mock call history
    mock_orjson.reset_mock()

    # Test loads with kwargs (should fall back to stdlib)
    res = json_compat.loads(json_str, parse_float=float)
    assert res == {'x': 100}
    assert not mock_orjson.loads.called


def test_loads_memoryview(mock_orjson_state: tuple[bool, MagicMock]) -> None:
    orjson_available, mock_orjson = mock_orjson_state
    data_bytes = b'{"y": 200}'
    mview = memoryview(data_bytes)

    res = json_compat.loads(mview)
    assert res == {'y': 200}
    if orjson_available:
        mock_orjson.loads.assert_called_with(data_bytes)
    else:
        assert not mock_orjson.loads.called


def test_load_reads_from_file(mock_orjson_state: tuple[bool, MagicMock]) -> None:
    json_str = '{"foo": "bar"}'
    fp = io.StringIO(json_str)
    res = json_compat.load(fp)
    assert res == {'foo': 'bar'}
