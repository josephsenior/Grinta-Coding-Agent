from typing import Any

from backend.storage import get_file_store
from backend.storage.secrets.file_secrets_store import FileSecretsStore
from backend.storage.settings.file_settings_store import FileSettingsStore


def get_user_id(*args, **kwargs) -> str:
    """Return the constant OSS user ID."""
    return "oss_user"


def get_user_settings_store(*args, **kwargs) -> FileSettingsStore:
    """Return a default file-based settings store."""
    return FileSettingsStore(file_store=get_file_store("memory"))


def get_user_secret_store(*args, **kwargs) -> FileSecretsStore:
    """Return a default file-based secret store."""
    return FileSecretsStore(file_store=get_file_store("memory"))


def get_secrets_store(*args, **kwargs) -> FileSecretsStore:
    return get_user_secret_store()


def get_access_token(*args, **kwargs) -> str | None:
    return None


def get_provider_tokens(*args, **kwargs) -> dict:
    return {}


def get_user_settings(*args, **kwargs) -> Any:
    return None


def get_user_secrets(*args, **kwargs) -> Any:
    return None


class AuthType:
    NONE = "none"
    TOKEN = "token"
    BEARER = "bearer"
    OAUTH = "oauth"  # Keep for compatibility


def get_auth_type() -> str:
    return AuthType.TOKEN


def get_current_user_id() -> str:
    return "oss_user"
