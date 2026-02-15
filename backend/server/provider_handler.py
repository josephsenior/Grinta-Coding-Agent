"""Lightweight provider token handler for secret masking and env-var propagation.

This is the slimmed-down successor of the old ``backend.integrations.provider.ProviderHandler``.
All git-service methods (repo listing, branch search, PR checks, playbook
fetching, etc.) have been removed.  For git operations, use an MCP server
instead.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from pydantic import SecretStr

from backend.core.provider_types import (
    PROVIDER_TOKEN_TYPE,
    ProviderToken,
    ProviderType,
)

if TYPE_CHECKING:
    from backend.events.action.action import Action
    from backend.events.stream import EventStream


class ProviderHandler:
    """Facade for propagating provider tokens as environment variables.

    Responsibilities:
    - Expose tokens as ``{provider}_token`` environment variables for runtimes.
    - Mask secret values in the ``EventStream`` so they never leak to logs or
      the client.
    - Detect when an agent ``CmdRunAction`` references a token env var.
    """

    def __init__(
        self,
        provider_tokens: MappingProxyType[ProviderType, ProviderToken],
    ) -> None:
        self._provider_tokens = provider_tokens

    # -- read-only access ---------------------------------------------------

    @property
    def provider_tokens(self) -> PROVIDER_TOKEN_TYPE:
        """Read-only access to provider tokens."""
        return self._provider_tokens

    # -- env-var helpers ----------------------------------------------------

    @classmethod
    def get_provider_env_key(cls, provider: ProviderType) -> str:
        """Map ProviderType value to the environment variable name in the runtime."""
        return f"{provider.value}_token".lower()

    def expose_env_vars(
        self, env_secrets: dict[ProviderType, SecretStr]
    ) -> dict[str, str]:
        """Return string values instead of typed values for environment secrets."""
        exposed_envs: dict[str, str] = {}
        for provider, token in env_secrets.items():
            env_key = self.get_provider_env_key(provider)
            exposed_envs[env_key] = token.get_secret_value()
        return exposed_envs

    async def get_env_vars(
        self,
        expose_secrets: bool = False,
    ) -> dict[ProviderType, SecretStr] | dict[str, str]:
        """Retrieve provider tokens, optionally exposing raw string values.

        Args:
            expose_secrets: If ``True``, return ``{env_key: str}`` pairs instead
                of ``{ProviderType: SecretStr}``.
        """
        if not self._provider_tokens:
            return {}

        env_vars: dict[ProviderType, SecretStr] = {}
        for provider in self._provider_tokens:
            token_obj = self._provider_tokens[provider]
            if token_obj and token_obj.token:
                env_vars[provider] = token_obj.token

        if expose_secrets:
            return self.expose_env_vars(env_vars)
        return env_vars

    # -- event-stream secret masking ----------------------------------------

    async def set_event_stream_secrets(
        self,
        event_stream: EventStream,
        env_vars: dict[ProviderType, SecretStr] | None = None,
    ) -> None:
        """Ensure the latest provider tokens are masked in the event stream.

        Args:
            event_stream: Agent session's event stream.
            env_vars: Optional pre-collected tokens.  When ``None`` the handler
                fetches them from its own token store.
        """
        if env_vars:
            exposed = self.expose_env_vars(env_vars)
        else:
            raw = await self.get_env_vars(expose_secrets=True)
            exposed = {str(k): str(v) for k, v in raw.items()} if raw else {}
        event_stream.set_secrets(exposed)

    # -- action introspection -----------------------------------------------

    @classmethod
    def check_cmd_action_for_provider_token_ref(
        cls, event: Action
    ) -> list[ProviderType]:
        """Detect if an agent run action references a provider token env var.

        Returns a list of providers whose env vars appear in the command.
        """
        from backend.events.action.commands import CmdRunAction

        if not isinstance(event, CmdRunAction):
            return []
        return [
            provider
            for provider in ProviderType
            if cls.get_provider_env_key(provider) in event.command.lower()
        ]
