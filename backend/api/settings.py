"""Pydantic models for server settings and provider configuration APIs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from backend.storage.data_models.settings import Settings

try:
    from backend.core.config.mcp_config import MCPConfig
except Exception as e:
    # Log import failure for debugging, but allow fallback
    import logging

    logging.getLogger(__name__).warning("Failed to import MCPConfig: %s", e)
    MCPConfig = Any  # type: ignore

from backend.core.provider_types import CustomSecret, ProviderToken, ProviderType


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
