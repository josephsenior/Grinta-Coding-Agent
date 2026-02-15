"""Server configuration defaults and helpers for loading overrides."""

import os
import secrets
from pathlib import Path

from backend.core.logger import FORGE_logger as logger
from backend.server.types import AppMode, ServerConfigInterface
from backend.utils.import_utils import get_impl

_DEFAULT_INSECURE_KEY = "forge_dev_key"


def _resolve_session_api_key() -> str:
    """Return the session API key, auto-generating one if not configured.

    Priority:
      1. SESSION_API_KEY environment variable (explicit override)
      2. Existing key persisted in .env.local
      3. Auto-generate a new random key, persist to .env.local, and return it

    The static default "forge_dev_key" is never used in production.
    """
    env_key = os.environ.get("SESSION_API_KEY", "").strip()
    if env_key and env_key != _DEFAULT_INSECURE_KEY:
        return env_key

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

    config_cls = os.environ.get("FORGE_CONFIG_CLS", None)
    app_mode = AppMode.OSS
    session_api_key = _resolve_session_api_key()
    posthog_client_key = "phc_3ESMmY9SgqEAGBB6sMGK5ayYHkeUuknH2vP6FmWH9RA"
    github_client_id = os.environ.get("GITHUB_APP_CLIENT_ID", "")
    enable_billing = os.environ.get("ENABLE_BILLING", "false") == "true"
    hide_llm_settings = os.environ.get("HIDE_LLM_SETTINGS", "false") == "true"
    # Project management integrations
    enable_jira = os.environ.get("ENABLE_JIRA", "true") == "true"
    enable_jira_dc = os.environ.get("ENABLE_JIRA_DC", "true") == "true"
    enable_linear = os.environ.get("ENABLE_LINEAR", "true") == "true"
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
        "backend.server.conversation_manager.local_conversation_manager.LocalConversationManager",
    )
    monitoring_listener_class: str = "backend.server.monitoring.MonitoringListener"

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
