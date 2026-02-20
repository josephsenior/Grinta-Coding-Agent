"""Server configuration defaults and helpers for loading overrides."""

import os
import secrets
from pathlib import Path

from backend.core.logger import forge_logger as logger
from backend.api.types import AppMode, ServerConfigInterface
from backend.utils.import_utils import get_impl

_DEFAULT_INSECURE_KEY = "forge_dev_key"


def _resolve_session_api_key() -> str:
    """Return the session API key, auto-generating one if not configured.

    Priority:
      1. FORGE_RUNTIME="local" → Explicitly return "" for zero-config.
      2. SESSION_API_KEY environment variable (explicit override)
      3. Existing key persisted in .env.local
      4. Auto-generate a new random key (unless in local dev mode)
    """
    # For local/OSS mode, if no key is set, we default to disabled (empty string)
    # to ensure a "One-Click" zero-config experience.
    if os.environ.get("FORGE_RUNTIME") == "local":
        logger.info(
            "FORGE_RUNTIME=local detected: disabling session API key for zero-config."
        )
        return ""

    env_key = os.environ.get("SESSION_API_KEY")
    if env_key is not None:
        # If explicitly set (even to empty string), respect it
        val = env_key.strip()
        if val != _DEFAULT_INSECURE_KEY:
            return val

    # Try to read from .env.local (persisted from a previous run)
    env_local = Path(".env.local")
    if env_local.exists():
        for line in env_local.read_text().splitlines():
            line = line.strip()
            if line.startswith("SESSION_API_KEY="):
                persisted = line.split("=", 1)[1].strip().strip("\"'")
                if persisted and persisted != _DEFAULT_INSECURE_KEY:
                    return persisted

    # Auto-generate a cryptographically secure key
    new_key = f"forge_{secrets.token_urlsafe(32)}"
    try:
        # Append to .env.local so it persists across restarts
        with open(env_local, "a", encoding="utf-8") as f:
            f.write(f"\nSESSION_API_KEY={new_key}\n")
        logger.info(
            "Auto-generated SESSION_API_KEY and saved to .env.local. Set SESSION_API_KEY env var to override."
        )
    except OSError:
        logger.warning(
            "Could not write .env.local — auto-generated key will not persist. Set SESSION_API_KEY env var explicitly."
        )

    return new_key


class ServerConfig(ServerConfigInterface):
    """Default OSS server configuration with environment-driven overrides."""

    config_cls: str | None = os.environ.get("FORGE_CONFIG_CLS", None)
    app_mode: AppMode = AppMode.OSS
    posthog_client_key: str = "phc_3ESMmY9SgqEAGBB6sMGK5ayYHkeUuknH2vP6FmWH9RA"
    github_client_id: str = os.environ.get("GITHUB_APP_CLIENT_ID", "")
    enable_billing: bool = os.environ.get("ENABLE_BILLING", "false") == "true"
    hide_llm_settings: bool = os.environ.get("HIDE_LLM_SETTINGS", "false") == "true"
    # Project management integrations
    enable_jira: bool = os.environ.get("ENABLE_JIRA", "true") == "true"
    enable_jira_dc: bool = os.environ.get("ENABLE_JIRA_DC", "true") == "true"
    enable_linear: bool = os.environ.get("ENABLE_LINEAR", "true") == "true"
    settings_store_class: str = (
        "backend.storage.settings.file_settings_store.FileSettingsStore"
    )
    secret_store_class: str = (
        "backend.storage.secrets.file_secrets_store.FileSecretsStore"
    )
    conversation_store_class: str = os.environ.get(
        "CONVERSATION_STORE_CLASS",
        "backend.storage.conversation.file_conversation_store.FileConversationStore",
    )
    conversation_manager_class: str = os.environ.get(
        "CONVERSATION_MANAGER_CLASS",
        "backend.api.conversation_manager.local_conversation_manager.LocalConversationManager",
    )
    monitoring_listener_class: str = "backend.api.monitoring.MonitoringListener"

    def __init__(self) -> None:
        """Initialize server configuration and resolve session API key."""
        self.session_api_key = _resolve_session_api_key()

    def verify_config(self) -> None:
        """Validate that no unsupported config class overrides are provided."""
        if self.config_cls:
            msg = "Unexpected config path provided"
            raise ValueError(msg)

    def get_config(self):
        """Return JSON-serializable snapshot consumed by client/admin APIs."""
        return {
            "APP_MODE": self.app_mode,
            "GITHUB_CLIENT_ID": self.github_client_id,
            "POSTHOG_CLIENT_KEY": self.posthog_client_key,
            "FEATURE_FLAGS": {
                "ENABLE_BILLING": self.enable_billing,
                "HIDE_LLM_SETTINGS": self.hide_llm_settings,
                "ENABLE_JIRA": self.enable_jira,
                "ENABLE_JIRA_DC": self.enable_jira_dc,
                "ENABLE_LINEAR": self.enable_linear,
            },
        }


def load_server_config() -> ServerConfig:
    """Load server configuration from environment.

    Reads FORGE_CONFIG_CLS environment variable to determine config class,
    instantiates it, and verifies the configuration.

    Returns:
        Loaded and verified ServerConfig instance

    """
    config_cls = os.environ.get("FORGE_CONFIG_CLS", None)
    logger.info("Using config class %s", config_cls)
    server_config_cls = get_impl(ServerConfig, config_cls)
    server_config: ServerConfig = server_config_cls()
    server_config.verify_config()
    return server_config
