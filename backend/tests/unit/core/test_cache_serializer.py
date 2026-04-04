"""Tests for backend.core.cache._serializer — JSON-based cache serialization."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest
from pydantic import BaseModel, SecretStr

from backend.core.cache._serializer import (
    _json_fallback,
    deserialize_model,
    serialize_model,
)

# ── helpers ──────────────────────────────────────────────────────────


class Color(Enum):
    RED = 'red'
    BLUE = 'blue'


class SampleModel(BaseModel):
    name: str = 'test'
    value: int = 42


class SecretModel(BaseModel):
    api_key: SecretStr = SecretStr('default-key')
    label: str = 'x'


# ── _json_fallback ───────────────────────────────────────────────────


class TestJsonFallback:
    def test_secret_str(self):
        s = SecretStr('my-secret')
        assert _json_fallback(s) == 'my-secret'

    def test_enum(self):
        assert _json_fallback(Color.RED) == 'red'

    def test_path(self):
        result = _json_fallback(Path('/tmp/foo'))
        # On Windows, Path normalizes to backslashes
        assert result.replace('\\', '/') == '/tmp/foo'

    def test_pure_posix_path(self):
        result = _json_fallback(PurePosixPath('/usr/bin'))
        assert result == '/usr/bin'

    def test_pure_windows_path(self):
        result = _json_fallback(PureWindowsPath('C:\\Users\\test'))
        assert 'Users' in result

    def test_bytes(self):
        assert _json_fallback(b'hello') == 'hello'

    def test_bytes_replacement(self):
        # Invalid UTF-8 bytes should use replace error handler
        result = _json_fallback(b'\xff\xfe')
        assert isinstance(result, str)

    def test_set(self):
        result = _json_fallback({3, 1, 2})
        assert result == [1, 2, 3]

    def test_fallback_str(self):
        """Unrecognized types get str() conversion."""

        class Custom:
            def __str__(self):
                return 'custom-repr'

        assert _json_fallback(Custom()) == 'custom-repr'


# ── serialize_model ──────────────────────────────────────────────────


class TestSerializeModel:
    def test_returns_bytes(self):
        m = SampleModel()
        result = serialize_model(m)
        assert isinstance(result, bytes)

    def test_is_valid_json(self):
        m = SampleModel(name='hello', value=99)
        data = json.loads(serialize_model(m))
        assert data['name'] == 'hello'
        assert data['value'] == 99

    def test_compact_separators(self):
        raw = serialize_model(SampleModel())
        text = raw.decode('utf-8')
        # Compact JSON has no spaces after : or ,
        assert ': ' not in text
        assert ', ' not in text

    def test_secret_str_preserved(self):
        m = SecretModel(api_key=SecretStr('top-secret'), label='lab')
        data = json.loads(serialize_model(m))
        assert data['api_key'] == 'top-secret'
        assert data['label'] == 'lab'


# ── deserialize_model ────────────────────────────────────────────────


class TestDeserializeModel:
    def test_round_trip(self):
        original = SampleModel(name='foo', value=7)
        raw = serialize_model(original)
        restored = deserialize_model(raw, SampleModel)
        assert restored.name == 'foo'
        assert restored.value == 7

    def test_round_trip_secret(self):
        original = SecretModel(api_key=SecretStr('abc'), label='lbl')
        raw = serialize_model(original)
        restored = deserialize_model(raw, SecretModel)
        assert restored.api_key.get_secret_value() == 'abc'
        assert restored.label == 'lbl'

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match='not valid JSON'):
            deserialize_model(b'not-json!!!', SampleModel)

    def test_invalid_utf8_raises(self):
        with pytest.raises(ValueError, match='not valid JSON'):
            deserialize_model(b'\xff\xfe\xfd', SampleModel)

    def test_wrong_schema_raises(self):
        # Missing required fields or wrong types
        raw = json.dumps({'name': 123, 'value': 'not-int'}).encode()
        with pytest.raises(Exception):
            deserialize_model(raw, SampleModel)
