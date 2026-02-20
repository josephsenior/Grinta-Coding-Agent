from typing import Any

from backend.storage import get_file_store
from backend.storage.locations import get_file_store_path
from backend.storage.secrets.file_secrets_store import FileSecretsStore
from backend.storage.settings.file_settings_store import FileSettingsStore
from backend.storage.data_models.settings import Settings
from backend.storage.data_models.user_secrets import UserSecrets


def get_user_id(request: Any | None = None) -> str:
    """Return the constant OSS user ID.

    Accepts an optional request object for compatibility with FastAPI dependency
    injection and explicit calls.
    """
    return "oss_user"


def get_user_settings_store(request: Any | None = None) -> FileSettingsStore:
    """Return a local-disk-backed settings store persisted under ~/.Forge."""
    return FileSettingsStore(
        file_store=get_file_store("local", file_store_path=get_file_store_path())
    )


def get_user_secret_store(request: Any | None = None) -> FileSecretsStore:
    """Return a local-disk-backed secret store persisted under ~/.Forge."""
    return FileSecretsStore(
        file_store=get_file_store("local", file_store_path=get_file_store_path())
    )


def get_secrets_store() -> FileSecretsStore:
    return get_user_secret_store()


def get_access_token() -> str | None:
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


class AuthType:
    NONE = "none"
    TOKEN = "token"
    BEARER = "bearer"
    OAUTH = "oauth"  # Keep for compatibility


def get_auth_type() -> str:
    return AuthType.TOKEN


def get_current_user_id() -> str:
    return "oss_user"
