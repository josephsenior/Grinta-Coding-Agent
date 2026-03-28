"""Tests for backend.gateway.types — server type abstractions."""

from __future__ import annotations

import pytest

from backend.gateway.types import (
    LLMAuthenticationError,
    MissingSettingsError,
)
from backend.core.errors import UserActionRequiredError


class TestMissingSettingsError:
    def test_is_value_error(self):
        err = MissingSettingsError("no settings")
        assert isinstance(err, ValueError)

    def test_is_user_action_required(self):
        err = MissingSettingsError("no settings")
        assert isinstance(err, UserActionRequiredError)

    def test_message(self):
        err = MissingSettingsError("API key missing")
        assert "API key missing" in str(err)


class TestLLMAuthenticationError:
    def test_is_value_error(self):
        err = LLMAuthenticationError("bad key")
        assert isinstance(err, ValueError)

    def test_is_user_action_required(self):
        err = LLMAuthenticationError("bad key")
        assert isinstance(err, UserActionRequiredError)

    def test_message(self):
        err = LLMAuthenticationError("invalid API key")
        assert "invalid API key" in str(err)

    def test_catchable_as_value_error(self):
        with pytest.raises(ValueError):
            raise LLMAuthenticationError("test")
