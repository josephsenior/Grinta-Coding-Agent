"""Configuration schemas describing external provider integrations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from backend.core.providers import (
    DEFAULT_API_KEY_MIN_LENGTH,
    PROVIDER_CONFIGURATIONS,
    UNKNOWN_PROVIDER_CONFIG,
)
from backend.core.logger import app_logger as logger


class ParameterType(Enum):
    """Types of parameters for provider validation."""

    REQUIRED = "required"
    OPTIONAL = "optional"
    FORBIDDEN = "forbidden"


@dataclass
class ProviderConfig:
    """Configuration schema for an LLM provider."""

    # Core provider identification
    name: str
    env_var: str | None = None
    requires_protocol: bool = True  # Whether base_url needs http(s)://
    supports_streaming: bool = True

    # Parameter definitions
    required_params: set[str] = field(default_factory=set)
    optional_params: set[str] = field(default_factory=set)
    forbidden_params: set[str] = field(default_factory=set)

    # API key format validation
    api_key_prefixes: list[str] = field(default_factory=list)
    api_key_min_length: int = DEFAULT_API_KEY_MIN_LENGTH

    # Special handling flags
    handles_own_routing: bool = False  # Provider handles routing internally
    requires_custom_llm_provider: bool = False

    def is_param_allowed(self, param_name: str) -> bool:
        """Check if a parameter is allowed for this provider."""
        return param_name not in self.forbidden_params and (
            param_name in self.required_params or param_name in self.optional_params
        )

    def is_param_required(self, param_name: str) -> bool:
        """Check if a parameter is required for this provider."""
        return param_name in self.required_params

    def validate_base_url(self, base_url: str | None) -> str | None:
        """Validate and normalize base_url for this provider."""
        if not base_url:
            return None

        base_url = str(base_url).strip()
        if not base_url:
            return None

        # If provider handles its own routing, don't use custom base_url
        if self.handles_own_routing:
            logger.debug(
                "Provider %s handles own routing - clearing base_url", self.name
            )
            return None

        # Check protocol requirement
        if self.requires_protocol and not any(
            base_url.startswith(proto) for proto in ["http://", "https://"]
        ):
            logger.warning(
                "Provider %s requires base_url with protocol - clearing invalid URL: %s",
                self.name,
                base_url,
            )
            return None

        return base_url


class ProviderConfigurationManager:
    """Manages provider configurations and provides validation logic."""

    def __init__(self) -> None:
        """Initialize with comprehensive provider configurations."""
        self._provider_configs = self._load_provider_configurations()
        self._unknown_provider_config = self._create_unknown_provider_config()

    def _load_provider_configurations(self) -> dict[str, ProviderConfig]:
        """Load provider-specific configurations for App agents."""
        configs: dict[str, ProviderConfig] = {}

        for provider_name, config_data in PROVIDER_CONFIGURATIONS.items():
            configs[provider_name] = ProviderConfig(**config_data)

        # Alias for gemini
        if "google" in configs:
            configs["gemini"] = configs["google"]

        return configs

    def _create_unknown_provider_config(self) -> ProviderConfig:
        """Create a safe default configuration for unknown providers."""
        return ProviderConfig(**UNKNOWN_PROVIDER_CONFIG)

    def get_provider_config(self, provider: str) -> ProviderConfig:
        """Get configuration for a provider, falling back to unknown provider config."""
        return self._provider_configs.get(
            provider.lower(), self._unknown_provider_config
        )

    def _process_forbidden_param(
        self, param_name: str, provider: str, warnings: list[str]
    ) -> bool:
        """Process forbidden parameter.

        Args:
            param_name: Parameter name
            provider: Provider name
            warnings: Warnings list to append to

        Returns:
            True if parameter should be skipped

        """
        logger.debug(
            "Removing forbidden parameter '%s' for provider %s", param_name, provider
        )
        warnings.append(
            f"Parameter '{param_name}' is not allowed for {provider} provider"
        )
        return True

    def _process_base_url_param(
        self,
        param_value: Any,
        provider: str,
        cleaned_params: dict[str, Any],
        config: ProviderConfig,
    ) -> None:
        """Process base_url parameter.

        Args:
            param_value: Parameter value
            provider: Provider name
            cleaned_params: Cleaned parameters dict
            config: Provider config

        """
        cleaned_value = config.validate_base_url(param_value)
        if cleaned_value is not None:
            cleaned_params["base_url"] = cleaned_value
        elif param_value is not None:
            logger.debug("Cleaned base_url for %s: %s -> None", provider, param_value)

    def _process_known_param(
        self,
        param_name: str,
        param_value: Any,
        config: ProviderConfig,
        cleaned_params: dict[str, Any],
    ) -> None:
        """Process known parameter (required or optional).

        Args:
            param_name: Parameter name
            param_value: Parameter value
            config: Provider config
            cleaned_params: Cleaned parameters dict

        """
        if param_name == "base_url":
            self._process_base_url_param(param_value, "", cleaned_params, config)
        else:
            cleaned_params[param_name] = param_value

    def _process_unknown_param(
        self,
        param_name: str,
        param_value: Any,
        provider: str,
        cleaned_params: dict[str, Any],
    ) -> None:
        """Process unknown parameter.

        Args:
            param_name: Parameter name
            param_value: Parameter value
            provider: Provider name
            cleaned_params: Cleaned parameters dict

        """
        cleaned_params[param_name] = param_value
        if provider == "unknown":
            logger.debug(
                "Allowing unknown parameter '%s' for unknown provider", param_name
            )
        else:
            logger.debug(
                "Parameter '%s' not specified for %s provider - allowing for flexibility",
                param_name,
                provider,
            )

    def validate_and_clean_params(
        self, provider: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Validate and clean parameters for a specific provider.

        Args:
            provider: The LLM provider name
            params: Dictionary of parameters to validate and clean

        Returns:
            Cleaned dictionary with only valid parameters for the provider

        """
        config = self.get_provider_config(provider)
        cleaned_params: dict[str, Any] = {}
        warnings: list[str] = []

        logger.debug("Validating parameters for provider: %s", provider)

        required = config.required_params
        optional = config.optional_params
        forbidden = config.forbidden_params

        for param_name, param_value in params.items():
            if param_name in forbidden:
                if self._process_forbidden_param(param_name, provider, warnings):
                    continue

            if (param_name in required) or (param_name in optional):
                self._process_known_param(
                    param_name, param_value, config, cleaned_params
                )
            else:
                self._process_unknown_param(
                    param_name, param_value, provider, cleaned_params
                )

        missing_required = config.required_params - set(cleaned_params.keys())
        if missing_required:
            warnings.append(
                f"Missing required parameters for {provider}: {', '.join(missing_required)}"
            )

        if warnings:
            logger.warning(
                "Parameter validation warnings for %s: %s",
                provider,
                "; ".join(warnings),
            )

        logger.debug(
            "Parameter validation complete for %s: %s params kept",
            provider,
            len(cleaned_params),
        )
        return cleaned_params

    def validate_api_key_format(self, provider: str, api_key: str | None) -> bool:
        """Validate API key format for a provider.

        Args:
            provider: The LLM provider name
            api_key: The API key to validate

        Returns:
            True if the API key format is valid or acceptable

        """
        if not api_key:
            config = self.get_provider_config(provider)
            return "api_key" not in config.required_params

        config = self.get_provider_config(provider)

        # Check minimum length
        if len(api_key) < config.api_key_min_length:
            logger.warning(
                "API key for %s is shorter than expected minimum (%s)",
                provider,
                config.api_key_min_length,
            )
            return False

        # Check prefixes if specified - warn but don't fail validation
        prefixes = config.api_key_prefixes
        if prefixes:
            if not any(api_key.startswith(prefix) for prefix in prefixes):
                logger.warning(
                    "API key for %s doesn't match expected prefixes: %s",
                    provider,
                    config.api_key_prefixes,
                )
                # Don't return False here - just warn and continue
                # This allows for API key variations and updates from providers

        return True

    def get_environment_variable(self, provider: str) -> str | None:
        """Get the environment variable name for a provider."""
        config = self.get_provider_config(provider)
        return config.env_var


# Global instance for use throughout the application
provider_config_manager = ProviderConfigurationManager()
