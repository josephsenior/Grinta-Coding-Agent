"""SecretsStore implementation backed by the configured FileStore backend."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from backend.core.constants import DEFAULT_SECRETS_FILENAME
from backend.core.pydantic_compat import model_dump_json
from backend.persistence import get_file_store
from backend.persistence.data_models.user_secrets import UserSecrets
from backend.persistence.secrets.secrets_store import SecretsStore
from backend.utils.async_utils import call_sync_from_async

if TYPE_CHECKING:
    from backend.core.config.app_config import AppConfig
    from backend.persistence.files import FileStore


class FileSecretsStore(SecretsStore):
    """SecretsStore implementation persisting secrets to JSON file on disk."""

    DEFAULT_FILENAME = DEFAULT_SECRETS_FILENAME

    def __init__(
        self,
        file_store: FileStore,
        path: str | None = None,
        *,
        user_id: str | None = None,
        config: AppConfig | None = None,
    ) -> None:
        """Store dependencies and resolve the target secrets file path."""
        self.file_store = file_store
        self.user_id = user_id
        self.config = config
        self.path = path or self._build_default_path()

    def _build_default_path(self) -> str:
        if self.user_id:
            return f'users/{self.user_id}/{self.DEFAULT_FILENAME}'
        return self.DEFAULT_FILENAME

    async def load(self) -> UserSecrets | None:
        """Load user secrets from storage.

        Returns:
            UserSecrets object or None if not found

        """
        try:
            json_str = await call_sync_from_async(self.file_store.read, self.path)
            kwargs = json.loads(json_str)
            if not isinstance(kwargs, dict):
                kwargs = {}
            raw_provider_tokens = kwargs.get('provider_tokens') or {}
            normalized_tokens: dict[str, dict[str, str | Any]] = {}
            for key, value in raw_provider_tokens.items():
                if isinstance(value, dict):
                    token_value = value.get('token')
                    if token_value:
                        normalized_tokens[key] = value
                elif value:
                    normalized_tokens[key] = {'token': value}
            kwargs['provider_tokens'] = normalized_tokens if normalized_tokens else None
            return UserSecrets(**kwargs)
        except FileNotFoundError:
            return None

    async def store(self, secrets: UserSecrets) -> None:
        """Save user secrets to storage.

        Args:
            secrets: UserSecrets to persist

        """
        json_str = model_dump_json(secrets, context={'expose_secrets': True})
        await call_sync_from_async(self.file_store.write, self.path, json_str)

    @classmethod
    async def get_instance(
        cls, config: AppConfig, user_id: str | None
    ) -> FileSecretsStore:
        """Get FileSecretsStore singleton instance.

        Same root as ``settings.json`` — see :func:`backend.core.app_paths.get_app_settings_root`.

        Args:
            config: App configuration
            user_id: Optional user ID

        Returns:
            FileSecretsStore instance

        """
        from backend.core.app_paths import get_app_settings_root

        file_store = get_file_store(
            file_store_type=config.file_store,
            local_data_root=get_app_settings_root(),
        )
        return cls(file_store, user_id=user_id, config=config)
