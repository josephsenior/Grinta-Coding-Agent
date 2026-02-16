"""Tests for backend.storage.data_models.user_secrets — UserSecrets model."""

from __future__ import annotations

from types import MappingProxyType

import pytest
from pydantic import SecretStr

from backend.core.pydantic_compat import model_dump_with_options
from backend.core.provider_types import CustomSecret, ProviderToken, ProviderType
from backend.storage.data_models.user_secrets import UserSecrets


class TestUserSecretsDefaults:
    def test_empty_dict(self):
        s = UserSecrets()
        assert isinstance(s.provider_tokens, MappingProxyType)
        assert len(s.provider_tokens) == 0
        assert isinstance(s.custom_secrets, MappingProxyType)
        assert len(s.custom_secrets) == 0

    def test_none_input(self):
        s = UserSecrets.model_validate(None)
        assert len(s.provider_tokens) == 0

    def test_not_a_dict_rejected(self):
        with pytest.raises(ValueError, match="dictionary"):
            UserSecrets.model_validate("bad")


class TestConvertProviderTokens:
    def test_empty(self):
        result = UserSecrets._convert_provider_tokens({})
        assert isinstance(result, MappingProxyType)
        assert len(result) == 0

    def test_already_mappingproxy(self):
        token = ProviderToken(token=SecretStr("tok"), host="h")
        mp = MappingProxyType({ProviderType.ENTERPRISE_SSO: token})
        result = UserSecrets._convert_provider_tokens(mp)
        assert result is mp

    def test_string_keys_converted(self):
        token = ProviderToken(token=SecretStr("tok123"), host="gh.com")
        result = UserSecrets._convert_provider_tokens(
            {"enterprise_sso": token}
        )
        assert ProviderType.ENTERPRISE_SSO in result

    def test_invalid_provider_skipped(self):
        token = ProviderToken(token=SecretStr("tok"), host="h")
        result = UserSecrets._convert_provider_tokens({"invalid_provider": token})
        assert len(result) == 0


class TestConvertCustomSecrets:
    def test_empty(self):
        result = UserSecrets._convert_custom_secrets({})
        assert len(result) == 0

    def test_already_mappingproxy(self):
        sec = CustomSecret(secret=SecretStr("v"), description="d")
        mp = MappingProxyType({"K": sec})
        result = UserSecrets._convert_custom_secrets(mp)
        assert result is mp

    def test_custom_secret_values(self):
        sec = CustomSecret(secret=SecretStr("val"), description="test")
        result = UserSecrets._convert_custom_secrets({"MY_KEY": sec})
        assert "MY_KEY" in result


class TestUserSecretsSerialization:
    def test_provider_tokens_hidden_by_default(self):
        token = ProviderToken(token=SecretStr("secret123"), host="gh.com")
        s = UserSecrets(
            provider_tokens={ProviderType.ENTERPRISE_SSO: token}
        )
        data = model_dump_with_options(s)
        # Token should NOT be exposed
        for _, v in data.get("provider_tokens", {}).items():
            assert "secret123" not in str(v.get("token", ""))

    def test_provider_tokens_exposed_with_context(self):
        token = ProviderToken(token=SecretStr("secret123"), host="gh.com")
        s = UserSecrets(
            provider_tokens={ProviderType.ENTERPRISE_SSO: token}
        )
        data = model_dump_with_options(s, context={"expose_secrets": True})
        found = False
        for _, v in data.get("provider_tokens", {}).items():
            if v.get("token") == "secret123":
                found = True
        assert found

    def test_custom_secrets_hidden_by_default(self):
        sec = CustomSecret(secret=SecretStr("mysecret"), description="d")
        s = UserSecrets(custom_secrets={"KEY": sec})
        data = model_dump_with_options(s)
        for _, v in data.get("custom_secrets", {}).items():
            assert "mysecret" not in str(v.get("secret", ""))

    def test_custom_secrets_exposed(self):
        sec = CustomSecret(secret=SecretStr("mysecret"), description="d")
        s = UserSecrets(custom_secrets={"KEY": sec})
        data = model_dump_with_options(s, context={"expose_secrets": True})
        assert data["custom_secrets"]["KEY"]["secret"] == "mysecret"


class TestGetEnvVars:
    def test_empty(self):
        s = UserSecrets()
        assert s.get_env_vars() == {}

    def test_returns_secret_values(self):
        sec = CustomSecret(secret=SecretStr("val123"), description="d")
        s = UserSecrets(custom_secrets={"MY_VAR": sec})
        env = s.get_env_vars()
        assert env["MY_VAR"] == "val123"


class TestGetCustomSecretsDescriptions:
    def test_empty(self):
        s = UserSecrets()
        assert s.get_custom_secrets_descriptions() == {}

    def test_returns_descriptions(self):
        sec = CustomSecret(secret=SecretStr("v"), description="My desc")
        s = UserSecrets(custom_secrets={"KEY": sec})
        descs = s.get_custom_secrets_descriptions()
        assert descs["KEY"] == "My desc"


class TestUserSecretsFrozen:
    def test_cannot_reassign(self):
        s = UserSecrets()
        with pytest.raises(Exception):
            s.provider_tokens = {}  # type: ignore
