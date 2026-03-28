from typing import Any

from backend.core.app_paths import get_app_settings_root
from backend.persistence import get_file_store
from backend.persistence.secrets.file_secrets_store import FileSecretsStore
from backend.persistence.settings.file_settings_store import FileSettingsStore
from backend.persistence.data_models.settings import Settings
from backend.persistence.data_models.user_secrets import UserSecrets


def get_user_id(request: Any | None = None) -> str:
    """Return the constant OSS user ID.

    Accepts an optional request object for compatibility with FastAPI dependency
    injection and explicit calls.
    """
    return "oss_user"


def get_user_settings_store(request: Any | None = None) -> FileSettingsStore:
    """Return a settings store backed by settings.json in the project root.

    This makes the project-root settings.json the single source of truth
    for all settings (startup config + runtime API).
    """
    return FileSettingsStore(
        file_store=get_file_store("local", local_data_root=get_app_settings_root())
    )


def get_user_secret_store(request: Any | None = None) -> FileSecretsStore:
    """Return a local-disk-backed secret store next to the canonical ``settings.json``."""
    return FileSecretsStore(
        file_store=get_file_store("local", local_data_root=get_app_settings_root())
    )


def get_secrets_store() -> FileSecretsStore:
    return get_user_secret_store()


def get_access_token(request: Any | None = None) -> str | None:
    return None


def get_provider_tokens() -> dict:
    return {}


async def get_user_settings() -> Settings | None:
    """Load settings from the local file store."""
    store = get_user_settings_store()
    return await store.load()


async def get_user_secrets() -> UserSecrets | None:
    """Load secrets from the local file store."""
    store = get_user_secret_store()
    return await store.load()


def get_current_user_id() -> str:
    return "oss_user"
