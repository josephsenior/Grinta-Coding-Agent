"""Tests for backend.gateway.settings Pydantic models (GET/POST helpers)."""

from __future__ import annotations

import json

from pydantic import SecretStr

from backend.gateway.settings import (
    CustomSecretModel,
    CustomSecretWithoutValueModel,
    GETCustomSecrets,
    GETSettingsModel,
    POSTCustomSecrets,
    POSTProviderModel,
)
from backend.core.provider_types import CustomSecret


def test_post_provider_model_defaults() -> None:
    m = POSTProviderModel()
    assert m.mcp_config is None
    assert m.provider_tokens == {}


def test_post_custom_secrets_round_trip() -> None:
    cs = CustomSecret(secret=SecretStr("v"), description="d")
    m = POSTCustomSecrets(custom_secrets={"x": cs})
    dumped = m.model_dump()
    assert "custom_secrets" in dumped


def test_get_settings_model_minimal() -> None:
    m = GETSettingsModel(
        llm_api_key_set=False,
        llm_model_supports_vision=True,
        startup_snapshot={"resolved_port": 3000},
        recovery_snapshot={"status": "ok"},
    )
    assert m.llm_api_key_set is False
    assert m.llm_model_supports_vision is True
    assert m.startup_snapshot["resolved_port"] == 3000


def test_custom_secret_without_value_serialization() -> None:
    m = CustomSecretWithoutValueModel(name="api", description="desc")
    data = json.loads(m.model_dump_json())
    assert data == {"name": "api", "description": "desc"}


def test_custom_secret_model_has_value() -> None:
    m = CustomSecretModel(name="k", description=None, value=SecretStr("secret"))
    assert m.name == "k"
    assert m.value.get_secret_value() == "secret"


def test_get_custom_secrets_empty() -> None:
    m = GETCustomSecrets()
    assert m.custom_secrets is None
