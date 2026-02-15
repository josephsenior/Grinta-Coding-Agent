"""Pydantic model capturing per-session overrides for conversation startup."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ConfigDict, Field

from backend.core.provider_types import CUSTOM_SECRETS_TYPE, PROVIDER_TOKEN_TYPE, ProviderType
from backend.storage.data_models.settings import Settings

if TYPE_CHECKING:
    pass


class ConversationInitData(Settings):
    """Session initialization data for the web environment - a deep copy of the global config is made and then overridden with this data."""

    vcs_provider_tokens: PROVIDER_TOKEN_TYPE | None = Field(default=None, frozen=True)
    custom_secrets: CUSTOM_SECRETS_TYPE | None = Field(default=None, frozen=True)
    selected_repository: str | None = Field(default=None)
    replay_json: str | None = Field(default=None)
    selected_branch: str | None = Field(default=None)
    conversation_instructions: str | None = Field(default=None)
    vcs_provider: ProviderType | None = Field(default=None)
    model_config = ConfigDict(arbitrary_types_allowed=True)
