"""Pydantic models for server settings and provider configuration APIs."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from backend.core.provider_types import CustomSecret, ProviderToken, ProviderType
from backend.persistence.data_models.settings import Settings


def _import_mcp_config_class():
    from backend.core.config.mcp_config import MCPConfig as _MCPConfig

    return _MCPConfig


def _mcp_config_type_with_fallback():
    try:
        return _import_mcp_config_class()
    except Exception as e:
        logging.getLogger(__name__).warning("Failed to import MCPConfig: %s", e)
        return Any  # type: ignore[return-value]


MCPConfig = _mcp_config_type_with_fallback()


class POSTProviderModel(BaseModel):
    """Settings for POST requests."""

    mcp_config: MCPConfig | None = None
    provider_tokens: dict[str, ProviderToken] = Field(default_factory=dict)
    model_config = ConfigDict(arbitrary_types_allowed=True)


class POSTCustomSecrets(BaseModel):
    """Adding new custom secret."""

    custom_secrets: dict[str, CustomSecret] = {}


class GETSettingsModel(Settings):
    """Settings with additional token data for the client."""

    provider_tokens_set: dict[ProviderType, str | None] | None = None
    llm_api_key_set: bool
    #: From ``catalog.json`` for the configured ``llm_model`` (for chat image attachments).
    llm_model_supports_vision: bool = False
    startup_snapshot: dict[str, Any] | None = None
    recovery_snapshot: dict[str, Any] | None = None
    model_config = ConfigDict(use_enum_values=True, arbitrary_types_allowed=True)


class CustomSecretWithoutValueModel(BaseModel):
    """Custom secret model without value."""

    name: str
    description: str | None = None


class CustomSecretModel(CustomSecretWithoutValueModel):
    """Custom secret model with value."""

    value: SecretStr


class GETCustomSecrets(BaseModel):
    """Custom secrets names."""

    custom_secrets: list[CustomSecretWithoutValueModel] | None = None
