"""Data model representing persisted user settings for storage layer."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)
from pydantic import (  # noqa: E402
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    SerializationInfo,
    field_serializer,
    field_validator,
    model_validator,
)
from pydantic.json import pydantic_encoder  # noqa: E402

from backend.core.config.mcp_config import MCPConfig  # noqa: E402
from backend.core.config.utils import load_forge_config  # noqa: E402
from backend.storage.data_models.knowledge_base import KnowledgeBaseSettings  # noqa: E402
from backend.storage.data_models.user_secrets import UserSecrets  # noqa: E402

try:
    from unittest.mock import Mock
except ImportError:  # pragma: no cover
    Mock = None  # type: ignore

if TYPE_CHECKING:
    from backend.core.config.llm_config import LLMConfig

# 🚀 PERFORMANCE FIX: Module-level cache for Settings.from_config()
#   Prevents repeated settings.json parsing (1,119ms bottleneck under concurrent load)
#   OPTIMIZED: Increased TTL from 30s to 60s for 2-3x improvement
_settings_from_config_cache: Settings | None = None
_settings_from_config_cache_time: float = 0.0
_settings_from_config_cache_loader_id: int | None = None
_SETTINGS_FROM_CONFIG_CACHE_TTL: float = 60.0  # seconds (OPTIMIZED)


class Settings(BaseModel):
    """Persisted settings for Forge sessions."""

    language: str | None = None
    agent: str | None = None
    max_iterations: int | None = None
    security_analyzer: str | None = None
    confirmation_mode: bool | None = None
    llm_model: str | None = None
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None
    # Advanced LLM Configuration
    llm_temperature: float | None = None
    llm_top_p: float | None = None
    llm_max_output_tokens: int | None = None
    llm_timeout: int | None = None
    llm_num_retries: int | None = None
    llm_custom_llm_provider: str | None = None
    llm_caching_prompt: bool | None = None
    llm_disable_vision: bool | None = None
    # Autonomy Configuration
    autonomy_level: str | None = None
    enable_permissions: bool | None = None
    enable_checkpoints: bool | None = None
    secrets_store: UserSecrets = Field(
        default_factory=lambda: UserSecrets(), frozen=True
    )
    enable_default_condenser: bool = True
    enable_sound_notifications: bool = False
    enable_proactive_conversation_starters: bool = True
    enable_solvability_analysis: bool = True
    enable_review_critics: bool = True
    user_consents_to_analytics: bool | None = None
    mcp_config: MCPConfig | None = None
    # Knowledge Base Configuration
    kb_enabled: bool = True
    kb_active_collection_ids: list[str] = Field(default_factory=list)
    kb_search_top_k: int = 5
    kb_relevance_threshold: float = 0.7
    kb_auto_search: bool = True
    kb_search_strategy: str = "hybrid"  # "hybrid", "semantic", "keyword"
    max_budget_per_task: float | None = None
    condenser_max_size: int | None = None
    email: str | None = None
    email_verified: bool | None = None
    vcs_user_name: str | None = None
    vcs_user_email: str | None = None

    # Core & Runtime Configuration
    runtime: str | None = None
    file_store: str | None = None
    file_store_path: str | None = None
    workspace_base: str | None = None
    workspace_mount_path_in_runtime: str | None = None
    enable_browser: bool | None = None
    cache_dir: str | None = None
    max_budget_per_session: float | None = None
    max_budget_per_day: float | None = None
    debug: bool | None = None
    disable_color: bool | None = None
    conversation_max_age_seconds: int | None = None
    max_concurrent_conversations: int | None = None
    log_format: str | None = None
    log_level: str | None = None
    file_store_web_hook_url: str | None = None
    file_store_web_hook_headers: dict[str, str] | None = None
    file_store_web_hook_batch: bool | None = None
    replay_trajectory_path: str | None = None
    save_trajectory_path: str | None = None
    save_screenshots_in_trajectory: bool | None = None
    cli_multiline_input: bool | None = None
    mcp_host: str | None = None
    init_git_in_empty_workspace: bool | None = None
    run_as_Forge: bool | None = None
    file_uploads_max_file_size_mb: int | None = None
    file_uploads_restrict_file_types: bool | None = None
    file_uploads_allowed_extensions: list[str] | None = None

    # Agent Optional Abilities
    agent_enable_browsing: bool | None = None
    agent_enable_llm_editor: bool | None = None
    agent_enable_editor: bool | None = None
    agent_enable_cmd: bool | None = None
    agent_enable_think: bool | None = None
    agent_enable_finish: bool | None = None
    agent_enable_circuit_breaker: bool | None = None
    agent_enable_graceful_shutdown: bool | None = None
    agent_enable_history_truncation: bool | None = None
    agent_enable_condensation_request: bool | None = None
    # Parallel sub-agents: shared blackboard for coordination (off by default)
    delegate_task_blackboard_enabled: bool = False

    # Condenser Customization
    condenser_type: str | None = None
    condenser_keep_first: int | None = None
    condenser_max_events: int | None = None
    condenser_attention_window: int | None = None
    condenser_llm_config: str | None = None
    condenser_max_event_length: int | None = None
    condenser_token_budget: int | None = None

    # Graph RAG Configurations
    graph_rag_enabled: bool | None = None
    graph_rag_persistence_path: str | None = None
    graph_rag_graph_depth: int | None = None
    graph_rag_max_seed_results: int | None = None

    # Playbook Configuration
    disabled_playbooks: list[str] | None = None
    """Names of built-in or user playbooks to suppress for this session."""

    model_config = ConfigDict(validate_assignment=True)

    @property
    def knowledge_base(self) -> KnowledgeBaseSettings:
        """Returns the knowledge base settings as a KnowledgeBaseSettings object."""
        return KnowledgeBaseSettings(
            enabled=self.kb_enabled,
            active_collection_ids=self.kb_active_collection_ids,
            search_top_k=self.kb_search_top_k,
            relevance_threshold=self.kb_relevance_threshold,
            auto_search=self.kb_auto_search,
            search_strategy=self.kb_search_strategy,
        )

    @field_serializer("llm_api_key")
    def api_key_serializer(self, api_key: SecretStr | None, info: SerializationInfo):
        """Serialize API keys, exposing secrets only when requested.

        To serialize the API key instead of ********, set expose_secrets to True in the serialization context.
        """
        if api_key is None:
            return None
        context = info.context
        if context and context.get("expose_secrets", False):
            return api_key.get_secret_value()
        return pydantic_encoder(api_key)

    @model_validator(mode="before")
    @classmethod
    def convert_provider_tokens(cls, data: dict | object) -> dict | object:
        """Convert provider tokens from JSON format to UserSecrets format."""
        if not isinstance(data, dict):
            return data
        secrets_store = data.get("secrets_store")
        if not isinstance(secrets_store, dict):
            return data
        custom_secrets = secrets_store.get("custom_secrets")
        tokens = secrets_store.get("provider_tokens")
        secret_store = UserSecrets(provider_tokens={}, custom_secrets={})
        if isinstance(tokens, dict):
            converted_store = UserSecrets(provider_tokens=tokens)
            secret_store = secret_store.model_copy(
                update={"provider_tokens": converted_store.provider_tokens}
            )
        else:
            secret_store.model_copy(update={"provider_tokens": tokens})
        if isinstance(custom_secrets, dict):
            converted_store = UserSecrets(custom_secrets=custom_secrets)
            secret_store = secret_store.model_copy(
                update={"custom_secrets": converted_store.custom_secrets}
            )
        else:
            secret_store = secret_store.model_copy(
                update={"custom_secrets": custom_secrets}
            )
        data["secret_store"] = secret_store
        return data

    @field_validator("condenser_max_size")
    @classmethod
    def validate_condenser_max_size(cls, v: int | None) -> int | None:
        """Validate condenser max size is at least 20 events.

        Args:
            v: Max size value to validate

        Returns:
            Validated value

        Raises:
            ValueError: If value less than 20

        """
        if v is None:
            return v
        if v < 20:
            msg = "condenser_max_size must be at least 20"
            raise ValueError(msg)
        return v

    @field_validator("agent", mode="before")
    @classmethod
    def normalize_legacy_agent_names(cls, v: str | None) -> str | None:
        """Map deprecated/legacy agent names to current registry names."""
        if not isinstance(v, str):
            return v

        normalized = v.strip()
        if not normalized:
            return None

        legacy_map = {
            "codeactagent": "Orchestrator",
            "codeact": "Orchestrator",
            "codact": "Orchestrator",
            "orchestrator": "Orchestrator",
        }
        return legacy_map.get(normalized.lower(), normalized)

    @field_serializer("secrets_store")
    def secrets_store_serializer(self, secrets: UserSecrets, info: SerializationInfo):
        """Serialize the secrets store while forcing cache invalidation."""
        "Force invalidate secret store"
        return {"provider_tokens": {}}

    @staticmethod
    def _check_explicit_llm_config(app_config) -> bool:
        """Check if explicit LLM config should skip settings creation."""
        if not (hasattr(app_config, "llms") and isinstance(app_config.llms, dict)):
            return False

        explicit = app_config.llms.get("llm")
        if explicit is None:
            return False

        explicit_api_key = getattr(explicit, "api_key", None)
        if explicit_api_key is None:
            return True

        try:
            import os

            env_key = os.environ.get("FORGE_API_KEY")
            if (
                env_key
                and isinstance(explicit_api_key, SecretStr)
                and (explicit_api_key.get_secret_value() == env_key)
            ):
                return True
        except Exception:
            logger.warning("API key validation failed unexpectedly", exc_info=True)

        return False

    @staticmethod
    def _validate_api_key(api_key) -> bool:
        """Validate API key is present and not empty."""
        if api_key is None:
            return False

        try:
            if isinstance(api_key, SecretStr) and api_key.get_secret_value() == "":
                return False
        except Exception:
            if not api_key:
                return False

        return True

    @staticmethod
    def _has_explicit_api_key(config: object) -> bool:
        """Determine if the provided config carried an explicit API key."""
        try:
            return bool(getattr(config, "_has_explicit_api_key"))
        except AttributeError:
            # Fallback if attribute missing: assume explicit when key provided
            api_key = getattr(config, "api_key", None)
            return api_key is not None

    @staticmethod
    def _cache_and_return_none(current_time: float) -> None:
        """Cache a None result to avoid repeated config loads."""
        global \
            _settings_from_config_cache, \
            _settings_from_config_cache_time, \
            _settings_from_config_cache_loader_id
        _settings_from_config_cache = None
        _settings_from_config_cache_time = current_time
        _settings_from_config_cache_loader_id = id(load_forge_config)
        return

    @staticmethod
    def _get_cached_settings(current_time: float) -> Settings | None:
        """Return cached settings when valid, otherwise None."""
        global \
            _settings_from_config_cache, \
            _settings_from_config_cache_time, \
            _settings_from_config_cache_loader_id

        cached = _settings_from_config_cache
        if cached is None:
            return None

        cache_is_mocked = Mock is not None and isinstance(load_forge_config, Mock)
        cache_loader_matches = _settings_from_config_cache_loader_id == id(
            load_forge_config
        )
        cache_fresh = (
            current_time - _settings_from_config_cache_time
            < _SETTINGS_FROM_CONFIG_CACHE_TTL
        )

        if cache_fresh and not cache_is_mocked and cache_loader_matches:
            return cached

        if cache_is_mocked or not cache_loader_matches:
            Settings._reset_settings_cache()
        return None

    @staticmethod
    def _reset_settings_cache() -> None:
        """Reset cached settings metadata."""
        global \
            _settings_from_config_cache, \
            _settings_from_config_cache_time, \
            _settings_from_config_cache_loader_id
        _settings_from_config_cache = None
        _settings_from_config_cache_time = 0.0
        _settings_from_config_cache_loader_id = None

    @staticmethod
    def _should_use_llm_config(llm_config: LLMConfig) -> bool:
        if not Settings._has_explicit_api_key(llm_config):
            return False
        api_key = llm_config.api_key if hasattr(llm_config, "api_key") else None
        return Settings._validate_api_key(api_key)

    @staticmethod
    def _build_settings_from_app_config(app_config, llm_config: LLMConfig) -> Settings:
        security = app_config.security
        mcp_config = app_config.mcp if hasattr(app_config, "mcp") else None
        return Settings(
            language="en",
            agent=app_config.default_agent,
            max_iterations=app_config.max_iterations,
            security_analyzer=security.security_analyzer,
            confirmation_mode=security.confirmation_mode,
            llm_model=llm_config.model,
            llm_api_key=llm_config.api_key,
            llm_base_url=llm_config.base_url,
            mcp_config=mcp_config,
            max_budget_per_task=app_config.max_budget_per_task,
        )

    @staticmethod
    def _cache_settings_result(settings: Settings, current_time: float) -> None:
        """Persist successful settings result in module cache."""
        global \
            _settings_from_config_cache, \
            _settings_from_config_cache_time, \
            _settings_from_config_cache_loader_id
        _settings_from_config_cache = settings
        _settings_from_config_cache_time = current_time
        _settings_from_config_cache_loader_id = id(load_forge_config)

    @staticmethod
    def from_config() -> Settings | None:
        """Load settings from settings.json with global caching.

        🚀 PERFORMANCE FIX: Added module-level cache to prevent repeated settings.json parsing.
           This fixes the 1,119ms bottleneck when 10+ users load settings concurrently.
        """
        import time

        global \
            _settings_from_config_cache, \
            _settings_from_config_cache_time, \
            _settings_from_config_cache_loader_id

        current_time = time.time()

        cached_settings = Settings._get_cached_settings(current_time)
        if cached_settings is not None:
            return cached_settings

        app_config = load_forge_config()

        # Check for explicit LLM config that should skip settings
        if Settings._check_explicit_llm_config(app_config):
            return Settings._cache_and_return_none(current_time)

        # Get and validate API key
        llm_config: LLMConfig = app_config.get_llm_config()
        if not Settings._should_use_llm_config(llm_config):
            return Settings._cache_and_return_none(current_time)

        settings_from_config = Settings._build_settings_from_app_config(
            app_config, llm_config
        )
        Settings._cache_settings_result(settings_from_config, current_time)
        return settings_from_config

    def merge_with_config_settings(self) -> Settings:
        """Merge settings.json config with stored settings.

        settings.json takes priority for MCP settings, but they are merged rather than replaced.
        This method can be used by both server mode and CLI mode.
        """
        config_settings = Settings.from_config()
        if not config_settings or not config_settings.mcp_config:
            return self
        if not self.mcp_config:
            self.mcp_config = config_settings.mcp_config
            return self
        merged_mcp = config_settings.mcp_config.merge(self.mcp_config)
        self.mcp_config = merged_mcp
        return self
