"""Tests for backend.core.io_adapters.json."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from backend.core.errors import LLMResponseError
from backend.core.io_adapters.json import (
    AppJSONEncoder,
    _extract_first_json_object,
    _try_serialize_app_object,
    dumps,
    loads,
)


def test_dumps_uses_app_encoder_by_default() -> None:
    s = dumps({'a': 1})
    assert json.loads(s) == {'a': 1}


def test_dumps_with_kwargs_includes_custom_encoder() -> None:
    s = dumps({'x': None}, indent=2)
    assert 'null' in s


def test_dumps_encodes_datetime() -> None:
    dt = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    out = dumps({'t': dt})
    assert '2024-01-02' in out


def test_app_json_encoder_default_datetime() -> None:
    enc = AppJSONEncoder()
    dt = datetime(2020, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert enc.default(dt) == dt.isoformat()


def test_try_serialize_app_object_pydantic_like() -> None:
    m = MagicMock()
    m.model_dump.return_value = {'k': 1}
    out = _try_serialize_app_object(m)
    assert out == {'k': 1}


def test_loads_parses_clean_json() -> None:
    assert loads('{"z": 2}') == {'z': 2}


def test_loads_extracts_embedded_object() -> None:
    blob = 'Reasoning: {"a": true} trailing'
    assert loads(blob) == {'a': True}


def test_loads_repair_malformed_inner_object() -> None:
    # Trailing comma often repaired by json_repair
    text = 'x {"a": 1,}'
    result = loads(text)
    assert result == {'a': 1}


def test_loads_raises_when_no_json() -> None:
    with pytest.raises(LLMResponseError, match='No valid JSON'):
        loads('no braces here')


def test_extract_first_json_object_nested() -> None:
    s = 'pre {"outer": {"inner": 1}} post'
    extracted = _extract_first_json_object(s)
    assert extracted is not None
    assert json.loads(extracted) == {'outer': {'inner': 1}}
