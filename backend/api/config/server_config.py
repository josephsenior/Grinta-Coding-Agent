"""Server configuration defaults and helpers for loading overrides."""

import os

from backend.core.logger import forge_logger as logger
from backend.api.types import AppMode, ServerConfigInterface
from backend.utils.import_utils import get_impl




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
        """Initialize server configuration."""

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
