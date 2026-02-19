"""LLM configuration schemas and helpers for Forge agents."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

from backend._canonical import CanonicalModelMetaclass
from backend.core.config.api_key_manager import api_key_manager
from backend.core.config.provider_config import provider_config_manager
from backend.core.constants import (
    DEFAULT_LLM_CORRECT_NUM,
    DEFAULT_LLM_MAX_MESSAGE_CHARS,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_NUM_RETRIES,
    DEFAULT_LLM_RETRY_MAX_WAIT,
    DEFAULT_LLM_RETRY_MIN_WAIT,
    DEFAULT_LLM_RETRY_MULTIPLIER,
    DEFAULT_LLM_TEMPERATURE,
    DEFAULT_LLM_TOP_P,
)
from backend.core.logger import LOG_DIR
from backend.core.logger import forge_logger as logger


@contextmanager
def suppress_llm_env_export() -> Iterator[None]:
    """Context manager to temporarily disable environment export during config loading."""
    previous = api_key_manager.suppress_env_export
    api_key_manager.suppress_env_export = True
    try:
        yield
    finally:
        api_key_manager.suppress_env_export = previous


class LLMConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for the LLM model.

    Attributes:
        model: The model to use (e.g., openai/gpt-4o, anthropic/claude-3-5-sonnet).
        api_key: The API key to use.
        base_url: The base URL for the API.
        api_version: The version of the API.
        num_retries: The number of retries to attempt.
        retry_multiplier: The multiplier for the exponential backoff.
        retry_min_wait: The minimum time to wait between retries, in seconds.
        retry_max_wait: The maximum time to wait between retries, in seconds.
        timeout: The timeout for the API.
        max_message_chars: The approximate max number of characters in the content of an event included in the prompt.
        temperature: The temperature for the API.
        top_p: The top p for the API.
        top_k: The top k for the API.
        custom_llm_provider: The custom LLM provider to use (openai, anthropic, gemini, xai).
        max_input_tokens: The maximum number of input tokens.
        max_output_tokens: The maximum number of output tokens.
        input_cost_per_token: The cost per input token.
        output_cost_per_token: The cost per output token.
        drop_params: Drop any unmapped (unsupported) params without causing an exception.
        modify_params: Modify params allows the SDK to do transformations like adding a default message.
        disable_vision: If model is vision capable, this option allows to disable image processing.
        caching_prompt: Use the prompt caching feature if provided by the LLM and supported by the provider.
        log_completions: Whether to log LLM completions to the state.
        log_completions_folder: The folder to log LLM completions to.
        custom_tokenizer: A custom tokenizer to use for token counting.
        native_tool_calling: Whether to use native tool calling if supported by the model.
        reasoning_effort: The effort to put into reasoning ('low', 'medium', 'high', 'none').
        seed: The seed to use for the LLM.
        safety_settings: Safety settings for models that support them (like Gemini).
        correct_num: The number of times the draft editor LLM tries to fix an error when editing.

    """

    model: str = Field(
        default=DEFAULT_LLM_MODEL,
        min_length=1,
        description="The LLM model identifier to use",
    )
    api_key: SecretStr | None = Field(
        default=None, description="The API key to use for authentication"
    )
    base_url: str | None = Field(default=None, description="The base URL for the API")
    api_version: str | None = Field(default=None, description="The version of the API")
    num_retries: int = Field(
        default=DEFAULT_LLM_NUM_RETRIES,
        ge=0,
        description="The number of retries to attempt on API failures",
    )
    retry_multiplier: float = Field(
        default=DEFAULT_LLM_RETRY_MULTIPLIER,
        ge=1.0,
        description="The multiplier for exponential backoff retry delays",
    )
    retry_min_wait: int = Field(
        default=DEFAULT_LLM_RETRY_MIN_WAIT,
        ge=0,
        description="The minimum time to wait between retries, in seconds",
    )
    retry_max_wait: int = Field(
        default=DEFAULT_LLM_RETRY_MAX_WAIT,
        ge=0,
        description="The maximum time to wait between retries, in seconds",
    )
    timeout: int | None = Field(
        default=None, ge=1, description="The timeout in seconds for the API requests"
    )
    max_message_chars: int = Field(
        default=DEFAULT_LLM_MAX_MESSAGE_CHARS,
        ge=1,
        description="The approximate max number of characters in the content of an event included in the prompt",
    )
    temperature: float = Field(
        default=DEFAULT_LLM_TEMPERATURE,
        ge=0.0,
        le=2.0,
        description="The temperature for the API (0.0 to 2.0)",
    )
    top_p: float = Field(
        default=DEFAULT_LLM_TOP_P,
        ge=0.0,
        le=1.0,
        description="The top_p (nucleus sampling) parameter for the API (0.0 to 1.0)",
    )
    top_k: float | None = Field(
        default=None, ge=1.0, description="The top_k parameter for the API"
    )
    custom_llm_provider: str | None = Field(
        default=None,
        description="The custom LLM provider to use (openai, anthropic, gemini, xai)",
    )
    max_input_tokens: int | None = Field(
        default=None, ge=1, description="The maximum number of input tokens"
    )
    max_output_tokens: int | None = Field(
        default=None, ge=1, description="The maximum number of output tokens"
    )
    input_cost_per_token: float | None = Field(
        default=None, ge=0.0, description="The cost per input token"
    )
    output_cost_per_token: float | None = Field(
        default=None, ge=0.0, description="The cost per output token"
    )
    drop_params: bool = Field(
        default=True,
        description="Drop any unmapped (unsupported) params without causing an exception",
    )
    modify_params: bool = Field(
        default=True, description="Modify params allows the SDK to do transformations"
    )
    disable_vision: bool | None = Field(
        default=None,
        description="If model is vision capable, this option allows to disable image processing",
    )
    disable_stop_word: bool | None = Field(
        default=False, description="Whether to disable stop word handling"
    )
    caching_prompt: bool = Field(
        default=True,
        description="Use the prompt caching feature if provided by the LLM",
    )
    log_completions: bool = Field(
        default=False, description="Whether to log LLM completions to the state"
    )
    log_completions_folder: str = Field(
        default=os.path.join(LOG_DIR, "completions"),
        min_length=1,
        description="The folder to log LLM completions to",
    )
    custom_tokenizer: str | None = Field(
        default=None, description="A custom tokenizer to use for token counting"
    )
    native_tool_calling: bool | None = Field(
        default=None,
        description="Whether to use native tool calling if supported by the model",
    )
    reasoning_effort: str | None = Field(
        default=None,
        description="The effort to put into reasoning ('low', 'medium', 'high', 'none')",
    )
    seed: int | None = Field(default=None, description="The seed to use for the LLM")

    @model_validator(mode="after")
    def set_defaults(self) -> LLMConfig:
        """Set default values for reasoning_effort and base_url."""
        # Set reasoning_effort default if not provided
        if self.reasoning_effort is None:
            # Gemini models keep None for optimization
            if not (
                "gemini" in self.model.lower()
                or (
                    self.custom_llm_provider
                    and "gemini" in self.custom_llm_provider.lower()
                )
            ):
                self.reasoning_effort = "high"

        return self

    safety_settings: list[dict[str, str]] | None = Field(
        default=None,
        description="Safety settings for models that support them (like Gemini)",
    )
    correct_num: int = Field(
        default=DEFAULT_LLM_CORRECT_NUM,
        description="The number of times the draft editor LLM tries to fix an error",
    )
    for_routing: bool = Field(
        default=False,
        description="Whether this LLM config is used for routing decisions",
    )
    model_config = ConfigDict(extra="forbid")

    @field_validator("model", "log_completions_folder")
    @classmethod
    def validate_required_strings(cls, v: str) -> str:
        """Validate required string fields are non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name="field")

    @field_validator("base_url")
    @classmethod
    def validate_urls(cls, v: str | None) -> str | None:
        """Validate URL fields if provided."""
        if v is not None:
            v = v.strip()
            from backend.core.type_safety.type_safety import validate_non_empty_string

            validate_non_empty_string(v, name="url")
            # Basic URL format check - auto-patch if protocol is missing
            if v and "://" not in v:
                v = f"http://{v}"
            if not v.startswith(("http://", "https://")):
                raise ValueError("URL must start with http:// or https://")
        return v

    @classmethod
    def from_toml_section(cls, data: dict) -> dict[str, LLMConfig]:
        """Create a mapping of LLMConfig instances from a toml dictionary representing the [llm] section.

        The default configuration is built from all non-dict keys in data.
        Then, each key with a dict value (e.g. [llm.random_name]) is treated as a custom LLM configuration,
        and its values override the default configuration.

        Example:
        Apply generic LLM config with custom LLM overrides, e.g.
            [llm]
            model=...
            num_retries = 5
            [llm.claude]
            model="claude-3-5-sonnet"
        results in num_retries APPLIED to claude-3-5-sonnet.

        Returns:
            dict[str, LLMConfig]: A mapping where the key "llm" corresponds to the default configuration
            and additional keys represent custom configurations.

        """
        # Initialize the result mapping
        llm_mapping: dict[str, LLMConfig] = {}

        # Extract base config data (non-dict values)
        base_data = {}
        custom_sections: dict[str, dict] = {}
        for key, value in data.items():
            if isinstance(value, dict):
                custom_sections[key] = value
            else:
                base_data[key] = value

        # Try to create the base config
        try:
            base_config = cls.model_validate(base_data)
            llm_mapping["llm"] = base_config
        except ValidationError as e:
            logger.warning(
                "Cannot parse [llm] config from toml. Continuing with defaults.\nError: %s",
                e,
            )
            # If base config fails, create a default one
            base_config = cls()
            # Still add it to the mapping
            llm_mapping["llm"] = base_config

        # Process each custom section independently
        for name, overrides in custom_sections.items():
            try:
                # Merge base config with overrides
                merged = {**base_config.model_dump(), **overrides}
                custom_config = cls.model_validate(merged)
                llm_mapping[name] = custom_config
            except ValidationError:
                logger.debug(
                    "Cannot parse [%s] config from toml. This section will be skipped.",
                    name,
                )
                # Skip this custom section but continue with others
                continue

        return llm_mapping

    def model_post_init(self, __context: Any) -> None:
        """Post-initialization hook for clean API key handling and environment setup.

        Uses the new APIKeyManager for secure, provider-aware API key handling.
        """
        super().model_post_init(__context)

        if not api_key_manager.suppress_env_export:
            # SECURE API KEY HANDLING - Use the new API key manager
            key_val = ""
            if self.api_key is not None:
                # Pydantic ensures api_key is always SecretStr | None, so get_secret_value always exists
                key_val = self.api_key.get_secret_value()

            has_explicit_key = bool(key_val and key_val.strip())
            object.__setattr__(self, "_has_explicit_api_key", has_explicit_key)

            if not has_explicit_key:
                # Get the correct API key for this model/provider
                correct_api_key = api_key_manager.get_api_key_for_model(
                    self.model, self.api_key
                )

                if correct_api_key:
                    self.api_key = correct_api_key
                    logger.debug("Set correct API key for model: %s", self.model)
                else:
                    # Try to set from environment as fallback
                    provider = api_key_manager._extract_provider(self.model)
                    env_key = api_key_manager._get_provider_key_from_env(provider)
                    if env_key:
                        self.api_key = SecretStr(env_key)
                        logger.debug("Loaded API key from environment for %s", provider)
                    else:
                        logger.warning("No API key available for model: %s", self.model)

            # ALWAYS sync with api_key_manager if we have a key (explicit or loaded)
            if self.api_key:
                api_key_manager.set_api_key(self.model, self.api_key)
                api_key_manager.set_environment_variables(self.model, self.api_key)

        # CRITICAL: Clean base_url to prevent protocol errors
        self._clean_base_url()

        # Configure model-specific settings
        self._configure_model_defaults()

    def _clean_base_url(self) -> None:
        """Clean base_url and other parameters using provider-aware validation."""
        provider = api_key_manager._extract_provider(self.model)
        provider_config = provider_config_manager.get_provider_config(provider)

        # Use provider configuration to validate and clean base_url
        cleaned_url = provider_config.validate_base_url(self.base_url)
        if cleaned_url != self.base_url:
            logger.info(
                "Cleaned base_url for %s: '%s' -> %s",
                provider,
                self.base_url,
                cleaned_url,
            )
            self.base_url = cleaned_url

        # Additional validation for custom_llm_provider based on provider configuration
        if hasattr(self, "custom_llm_provider") and self.custom_llm_provider:
            # Check if custom_llm_provider is forbidden for this provider
            if not provider_config.is_param_allowed("custom_llm_provider"):
                logger.info(
                    "Clearing custom_llm_provider '%s' for %s - not allowed for this provider",
                    self.custom_llm_provider,
                    provider,
                )
                # Note: Can't directly modify Pydantic field, but this will help with logging

    def _configure_model_defaults(self) -> None:
        """Configure model-specific default settings."""
        # Set reasoning_effort to 'high' by default for non-Gemini models
        if self.reasoning_effort is None and "gemini-2.5-pro" not in self.model:
            self.reasoning_effort = "high"
