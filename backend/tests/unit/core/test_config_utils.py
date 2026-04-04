"""Unit tests for backend.core.config.config_utils — Pydantic introspection helpers."""

from __future__ import annotations

from pydantic import BaseModel

from backend.core.config.config_utils import get_field_info, model_defaults_to_dict

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class Inner(BaseModel):
    timeout: int = 30
    verbose: bool = False


class Outer(BaseModel):
    name: str = 'default'
    count: int | None = None
    inner: Inner = Inner()


# ---------------------------------------------------------------------------
# get_field_info
# ---------------------------------------------------------------------------


class TestGetFieldInfo:
    def test_simple_type(self):
        info = get_field_info(Outer.model_fields['name'])
        assert info['type'] == 'str'
        assert info['optional'] is False
        assert info['default'] == 'default'

    def test_optional_type(self):
        info = get_field_info(Outer.model_fields['count'])
        assert info['optional'] is True
        assert info['type'] == 'int'
        assert info['default'] is None

    def test_bool_field(self):
        info = get_field_info(Inner.model_fields['verbose'])
        assert info['type'] == 'bool'
        assert info['default'] is False

    def test_int_field(self):
        info = get_field_info(Inner.model_fields['timeout'])
        assert info['type'] == 'int'
        assert info['default'] == 30


# ---------------------------------------------------------------------------
# model_defaults_to_dict
# ---------------------------------------------------------------------------


class TestModelDefaultsToDict:
    def test_flat_model(self):
        result = model_defaults_to_dict(Inner())
        assert 'timeout' in result
        assert result['timeout']['type'] == 'int'
        assert result['timeout']['default'] == 30
        assert 'verbose' in result

    def test_nested_model(self):
        result = model_defaults_to_dict(Outer())
        assert 'name' in result
        assert 'inner' in result
        # inner should be recursive
        assert isinstance(result['inner'], dict)
        assert 'timeout' in result['inner']

    def test_optional_in_result(self):
        result = model_defaults_to_dict(Outer())
        assert result['count']['optional'] is True
