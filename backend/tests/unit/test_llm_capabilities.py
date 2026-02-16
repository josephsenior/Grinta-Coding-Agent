"""Tests for backend.llm.capabilities — ModelCapabilities frozen dataclass."""

from __future__ import annotations

import pytest

from backend.llm.capabilities import ModelCapabilities


class TestModelCapabilities:
    def test_defaults(self):
        mc = ModelCapabilities()
        assert mc.supports_function_calling is False
        assert mc.supports_reasoning_effort is False
        assert mc.supports_prompt_cache is False
        assert mc.supports_stop_words is True
        assert mc.supports_response_schema is False

    def test_custom_values(self):
        mc = ModelCapabilities(
            supports_function_calling=True,
            supports_reasoning_effort=True,
            supports_prompt_cache=True,
            supports_stop_words=False,
            supports_response_schema=True,
        )
        assert mc.supports_function_calling is True
        assert mc.supports_reasoning_effort is True
        assert mc.supports_prompt_cache is True
        assert mc.supports_stop_words is False
        assert mc.supports_response_schema is True

    def test_frozen_immutable(self):
        mc = ModelCapabilities()
        with pytest.raises(AttributeError):
            mc.supports_function_calling = True  # type: ignore[misc]

    def test_kw_only(self):
        # positional args should not work
        with pytest.raises(TypeError):
            ModelCapabilities(True, False)  # pylint: disable=too-many-function-args

    def test_equality(self):
        a = ModelCapabilities(supports_function_calling=True)
        b = ModelCapabilities(supports_function_calling=True)
        assert a == b

    def test_inequality(self):
        a = ModelCapabilities(supports_function_calling=True)
        b = ModelCapabilities(supports_function_calling=False)
        assert a != b
