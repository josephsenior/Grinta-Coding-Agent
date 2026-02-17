"""Tests for backend.server.services.conversation_service helper functions.

Targets the 19.4% coverage gap by testing pure helper functions
that don't require async infrastructure.
"""

from __future__ import annotations

from types import MappingProxyType
from unittest.mock import MagicMock

import pytest

from backend.core.provider_types import ProviderToken, ProviderType
from backend.events.action.message import MessageAction

# Only member: ProviderType.ENTERPRISE_SSO
_SSO = ProviderType.ENTERPRISE_SSO

from backend.server.services.conversation_service import (
    _create_initial_message_action,
    _ensure_provider_tokens_for_providers,
    _get_normalized_provider_tokens,
    _normalize_provider_list,
    _process_custom_secrets,
    _process_git_provider_tokens,
    create_provider_tokens_object,
)


# -----------------------------------------------------------
# _process_git_provider_tokens
# -----------------------------------------------------------

class TestProcessGitProviderTokens:
    def test_none_returns_empty(self):
        result = _process_git_provider_tokens(None)
        assert isinstance(result, MappingProxyType)
        assert len(result) == 0

    def test_empty_dict_returns_empty(self):
        result = _process_git_provider_tokens({})
        assert isinstance(result, MappingProxyType)
        assert len(result) == 0

    def test_dict_wrapped_in_mapping_proxy(self):
        tokens = {_SSO: ProviderToken(token="abc", user_id="u")}
        result = _process_git_provider_tokens(tokens)
        assert isinstance(result, MappingProxyType)
        assert _SSO in result

    def test_mapping_proxy_returned_as_is(self):
        tokens = MappingProxyType(
            {_SSO: ProviderToken(token="x", user_id="u")}
        )
        result = _process_git_provider_tokens(tokens)
        assert result is tokens


# -----------------------------------------------------------
# _process_custom_secrets
# -----------------------------------------------------------

class TestProcessCustomSecrets:
    def test_none_returns_empty(self):
        result = _process_custom_secrets(None)
        assert isinstance(result, MappingProxyType)
        assert len(result) == 0

    def test_empty_dict_returns_empty(self):
        result = _process_custom_secrets({})
        assert isinstance(result, MappingProxyType)

    def test_dict_wrapped(self):
        result = _process_custom_secrets({"API_KEY": "secret"})
        assert isinstance(result, MappingProxyType)
        assert result["API_KEY"] == "secret"

    def test_mapping_proxy_returned_directly(self):
        mp = MappingProxyType({"KEY": "VAL"})
        result = _process_custom_secrets(mp)
        assert result is mp

    def test_user_secrets_object(self):
        from backend.storage.data_models.user_secrets import CustomSecret, UserSecrets

        us = UserSecrets(custom_secrets={"K": CustomSecret(secret="V")})
        result = _process_custom_secrets(us)
        assert isinstance(result, MappingProxyType)
        assert "K" in result

    def test_unknown_type_returns_empty(self):
        result = _process_custom_secrets(42)
        assert isinstance(result, MappingProxyType)
        assert len(result) == 0


# -----------------------------------------------------------
# _normalize_provider_list
# -----------------------------------------------------------

class TestNormalizeProviderList:
    def test_none_returns_empty(self):
        assert _normalize_provider_list(None) == []

    def test_empty_list(self):
        assert _normalize_provider_list([]) == []

    def test_enum_values_pass_through(self):
        result = _normalize_provider_list([_SSO])
        assert result == [_SSO]

    def test_string_values_converted(self):
        result = _normalize_provider_list(["enterprise_sso"])
        assert result == [_SSO]

    def test_invalid_string_skipped(self):
        result = _normalize_provider_list(["nonexistent_provider_xyz"])
        assert result == []


# -----------------------------------------------------------
# _get_normalized_provider_tokens
# -----------------------------------------------------------

class TestGetNormalizedProviderTokens:
    def test_with_valid_tokens(self):
        tokens = {_SSO: ProviderToken(token="t", user_id="u")}
        result = _get_normalized_provider_tokens(tokens, None)
        assert _SSO in result

    def test_none_tokens_falls_back_to_defaults(self):
        defaults = MappingProxyType(
            {_SSO: ProviderToken(token="d", user_id="u")}
        )
        result = _get_normalized_provider_tokens(None, defaults)
        assert result is defaults

    def test_empty_tokens_falls_back_to_defaults(self):
        defaults = MappingProxyType(
            {_SSO: ProviderToken(token="d", user_id="u")}
        )
        result = _get_normalized_provider_tokens({}, defaults)
        assert result is defaults


# -----------------------------------------------------------
# _ensure_provider_tokens_for_providers
# -----------------------------------------------------------

class TestEnsureProviderTokensForProviders:
    def test_no_providers_returns_existing(self):
        tokens = MappingProxyType(
            {_SSO: ProviderToken(token="t", user_id="u")}
        )
        result = _ensure_provider_tokens_for_providers(tokens, None, "u")
        assert result is tokens

    def test_adds_missing_provider(self):
        result = _ensure_provider_tokens_for_providers(
            MappingProxyType({}), [_SSO], "u1"
        )
        assert _SSO in result
        assert result[_SSO].user_id == "u1"

    def test_existing_provider_not_overwritten(self):
        existing = MappingProxyType(
            {_SSO: ProviderToken(token="existing", user_id="u")}
        )
        result = _ensure_provider_tokens_for_providers(
            existing, [_SSO], "u2"
        )
        # token is SecretStr, compare via get_secret_value
        assert result[_SSO].token.get_secret_value() == "existing"

    def test_none_tokens_creates_new(self):
        result = _ensure_provider_tokens_for_providers(
            None, [_SSO], "u1"
        )
        assert _SSO in result


# -----------------------------------------------------------
# _create_initial_message_action
# -----------------------------------------------------------

class TestCreateInitialMessageAction:
    def test_no_msg_no_images_returns_none(self):
        assert _create_initial_message_action(None, None) is None

    def test_empty_msg_no_images_returns_none(self):
        assert _create_initial_message_action("", None) is None

    def test_with_message(self):
        action = _create_initial_message_action("Hello", None)
        assert isinstance(action, MessageAction)
        assert action.content == "Hello"

    def test_with_images_only(self):
        action = _create_initial_message_action(None, ["http://img.png"])
        assert isinstance(action, MessageAction)
        assert action.image_urls == ["http://img.png"]

    def test_with_msg_and_images(self):
        action = _create_initial_message_action("Hi", ["http://a.png"])
        assert action.content == "Hi"
        assert action.image_urls == ["http://a.png"]


# -----------------------------------------------------------
# create_provider_tokens_object
# -----------------------------------------------------------

class TestCreateProviderTokensObject:
    def test_empty_providers(self):
        result = create_provider_tokens_object([])
        assert isinstance(result, MappingProxyType)
        assert len(result) == 0

    def test_single_provider(self):
        result = create_provider_tokens_object([_SSO])
        assert _SSO in result
        assert result[_SSO].token is None

    def test_same_provider_twice(self):
        result = create_provider_tokens_object([_SSO, _SSO])
        assert _SSO in result
