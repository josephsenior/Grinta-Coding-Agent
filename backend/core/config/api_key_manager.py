"""API key management utilities for app configuration workflows."""

from __future__ import annotations

import builtins
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from pydantic import BaseModel, Field, SecretStr

from backend._canonical import CanonicalModelMetaclass
from backend.core.logger import app_logger as logger

from .provider_config import provider_config_manager

_INSTANCE_NAME = 'app_api_key_manager_instance'


class APIKeyManager(BaseModel, metaclass=CanonicalModelMetaclass):
    """Secure API key manager for multi-provider LLM support.

    Handles API keys for 30+ LLM providers with explicit or catalog-backed provider detection,
    format validation, and secure storage using Pydantic SecretStr.

    Features:
        - Provider extraction from explicit prefixes or exact catalog entries
        - API key format validation (prefix matching, length checks)
        - Environment variable fallbacks (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.)
        - Secure storage (never logs full keys, uses SecretStr)
        - Provider-specific validation rules

    Example:
        >>> manager = api_key_manager
        >>> key = manager.get_api_key_for_model('openrouter/gpt-4o')
        >>> # Returns: SecretStr(OPENROUTER_API_KEY from environment)

        >>> manager.set_environment_variables('claude-4', key)
        >>> # Sets: ANTHROPIC_API_KEY in environment

    Attributes:
        provider_api_keys: Mapping of provider names to their API keys

    """

    # Provider-specific API key mappings
    provider_api_keys: dict[str, SecretStr] = Field(default_factory=dict)

    # Flag to temporarily suppress environment variable export (useful during config loading)
    suppress_env_export: bool = Field(default=False)

    def model_post_init(self, __context: Any) -> None:
        """Post-initialization hook."""
        super().model_post_init(__context)
        # Ensure we don't accidentally suppress if we're not in a context
        if not hasattr(self, 'suppress_env_export'):
            object.__setattr__(self, 'suppress_env_export', False)

    @contextmanager
    def suppress_env_export_context(self) -> Iterator[None]:
        """Context manager to temporarily disable environment export."""
        previous = self.suppress_env_export
        object.__setattr__(self, 'suppress_env_export', True)
        try:
            yield
        finally:
            object.__setattr__(self, 'suppress_env_export', previous)

    def get_api_key_for_model(
        self, model: str | None, provided_key: SecretStr | None = None
    ) -> SecretStr | None:
        """Get the correct API key for a given model, following provider conventions.

        Determines the provider from the model string, validates the API key format,
        and returns the appropriate key from provided key, environment variables,
        or stored keys.

        Args:
            model: The LLM model identifier. Format varies by provider:
                - OpenAI: 'gpt-4o', 'gpt-5-2025-08-07'
                - Anthropic: 'claude-sonnet-4-20250514'
                - OpenRouter: 'openrouter/anthropic/claude-3.5-sonnet'
                - xAI: 'openrouter/x-ai/grok-4-fast'
                - Ollama: 'ollama/llama3.3:70b'
            provided_key: API key provided by user. May be incorrect for the provider
                (e.g., user provides OpenAI key but model requires Anthropic key).
                Will be validated and corrected if needed.

        Returns:
            SecretStr containing the correct API key for the model's provider,
            or None if no key found. Keys are never logged in plaintext.

        Note:
            If *model* is unset, returns None (no provider to resolve).

        Example:
            >>> # Get key for OpenRouter model
            >>> key = manager.get_api_key_for_model('openrouter/gpt-4o')
            >>> # Returns: OPENROUTER_API_KEY from environment

            >>> # Wrong key provided, will be corrected
            >>> wrong_key = SecretStr('sk-...')  # OpenAI key
            >>> correct_key = manager.get_api_key_for_model(
            ...     'claude-4',  # Anthropic model
            ...     provided_key=wrong_key
            ... )
            >>> # Returns: ANTHROPIC_API_KEY from environment (corrected)

        """
        if not model or not str(model).strip():
            return None

        # If a key is provided and it matches the provider, trust it.
        # If it does NOT match, prefer environment/stored provider keys first.
        # This avoids misrouting when a user switches models/providers but their
        # settings still contain an old provider key (e.g., OpenRouter -> Gemini).
        fallback_key: SecretStr | None = None

        provider = self._extract_provider(model)
        if provider == 'unknown':
            logger.error(
                'Cannot determine API-key provider for model %s. Use an explicit provider prefix.',
                model,
            )
            return None

        if provided_key:
            key_value = provided_key.get_secret_value()
            if self._is_correct_provider_key(provided_key, provider):
                logger.debug('Using provided API key for %s', provider)
                return provided_key
            if key_value and len(key_value) > 10:
                fallback_key = provided_key
                logger.warning(
                    'Provided API key does not match provider %s; will try env/stored keys first',
                    provider,
                )
            else:
                logger.warning(
                    'Provided API key appears to be for wrong provider. Expected %s',
                    provider,
                )

        # Try to get key from environment variables
        env_key = self._get_provider_key_from_env(provider)
        if env_key:
            logger.debug('Loaded %s API key from environment', provider)
            return SecretStr(env_key)

        # Try provider-specific mappings
        if provider in self.provider_api_keys:
            logger.debug('Using stored %s API key', provider)
            return self.provider_api_keys[provider]

        # If we still haven't found a provider-specific key, fall back to any
        # substantial key that was provided, even if it didn't match expected
        # format. This is a last resort and may still fail at the provider.
        if fallback_key:
            key_value = fallback_key.get_secret_value()
            logger.info(
                'Using provided API key as last-resort fallback for %s (key length: %s)',
                provider,
                len(key_value) if key_value else 0,
            )
            return fallback_key

        # Last-resort before startup config load: unified LLM key from the environment
        # only (secrets belong in .env as LLM_API_KEY, not in settings.json).
        env_llm = (os.environ.get('LLM_API_KEY') or '').strip()
        if env_llm:
            return SecretStr(env_llm)

        # Provide helpful guidance for missing API keys
        provider_config = provider_config_manager.get_provider_config(provider)
        env_var = (
            provider_config.env_var
            if provider_config
            else f'{provider.upper()}_API_KEY'
        )

        logger.error('No API key found for provider: %s', provider)
        logger.info(
            'To fix this, set the %s environment variable with your %s API key',
            env_var,
            provider,
        )
        return None

    def set_api_key(self, model: str | None, api_key: SecretStr) -> None:
        """Set API key for a model's provider."""
        if not model or not str(model).strip():
            return
        provider = self._extract_provider(model)
        if provider == 'unknown':
            logger.warning(
                'Skipping API key storage for ambiguous model %s; provider must be explicit',
                model,
            )
            return
        self.provider_api_keys[provider] = api_key
        logger.debug('Set API key for %s', provider)

    def set_environment_variables(
        self, model: str, api_key: SecretStr | None = None
    ) -> None:
        """Set provider-specific environment variables for the given model.

        Args:
            model: The LLM model identifier.
            api_key: The API key to set. If None, retrieves from manager.

        """
        if self.suppress_env_export:
            logger.debug(
                'Skipping environment variable export for %s (suppressed)', model
            )
            return

        if not model or not str(model).strip():
            logger.debug('Skipping environment variable export (no model set)')
            return

        provider = self._extract_provider(model)
        if provider == 'unknown':
            logger.warning(
                'Skipping environment export for ambiguous model %s; provider must be explicit',
                model,
            )
            return
        logger.debug(
            'Setting environment variables for model: %s, provider: %s', model, provider
        )

        # Get provider configuration
        provider_config = provider_config_manager.get_provider_config(provider)

        # Get the correct API key to use - prioritize the provided key
        key_to_use: SecretStr | None = None
        if api_key:
            key_to_use = api_key
            logger.debug('Using provided API key for %s', provider)

            # Validate API key format using provider configuration (warn only, don't fail)
            if api_key_value := api_key.get_secret_value():
                provider_config_manager.validate_api_key_format(provider, api_key_value)
                logger.debug('API key format validation completed for %s', provider)
        else:
            key_to_use = self.get_api_key_for_model(model)
            if key_to_use:
                logger.debug('Retrieved API key from manager for %s', provider)

        if not key_to_use:
            # Check if API key is actually required for this provider
            if 'api_key' in provider_config.required_params:
                env_var = provider_config.env_var
                logger.error(
                    'CRITICAL: No API key available for %s model %s', provider, model
                )
                logger.info(
                    'Please set the %s environment variable with your %s API key',
                    env_var,
                    provider,
                )
                # Try to get from environment as last resort
                env_key = self._get_provider_key_from_env(provider)
                if env_key:
                    logger.info('Found API key in environment for %s', provider)
                    key_to_use = SecretStr(env_key)
                else:
                    logger.error('FAILED: No API key found anywhere for %s', provider)
                    logger.info(
                        'Set %s environment variable to use %s models',
                        env_var,
                        provider,
                    )
                    return
            else:
                logger.debug('API key not required for provider %s', provider)
                return

        api_key_value = key_to_use.get_secret_value()
        logger.debug('Using API key for %s (length: %d)', provider, len(api_key_value))

        # Use provider configuration for environment variable mapping
        env_var = provider_config_manager.get_environment_variable(provider)
        if env_var:
            os.environ[env_var] = api_key_value
            logger.debug('Set %s environment variable for %s', env_var, provider)

            # CRITICAL: For Google/Gemini, also set GOOGLE_API_KEY as some SDKs expect this too
            if provider == 'google':
                os.environ['GOOGLE_API_KEY'] = api_key_value
                logger.debug(
                    'Set GOOGLE_API_KEY environment variable for Google provider'
                )
        else:
            logger.debug('No environment variable specified for provider: %s', provider)

        # ALSO set generic fallback ONLY if not already set
        if 'LLM_API_KEY' not in os.environ:
            os.environ['LLM_API_KEY'] = api_key_value
            logger.debug('Set LLM_API_KEY fallback environment variable')

    def _check_prefix_match(self, model: str, model_lower: str) -> str | None:
        """Check for provider prefix matches.

        Args:
            model: Original model string
            model_lower: Lowercase model string

        Returns:
            Provider name if matched, None otherwise

        """
        # Explicit provider prefixes only.
        prefix_patterns = {
            'openai': ['openai/'],
            'anthropic': ['anthropic/'],
            'google': ['google/'],
            'xai': ['xai/'],
            'groq': ['groq/'],
            'mistral': ['mistral/'],
            'openrouter': ['openrouter/'],
            'nvidia': ['nvidia/'],
            'ollama': ['ollama/'],
            'deepseek': ['deepseek/'],
        }

        for provider, prefixes in prefix_patterns.items():
            if any(model.startswith(prefix) for prefix in prefixes):
                return provider

        return None

    def _check_keyword_match(self, model_lower: str) -> str | None:
        """Legacy no-op retained for compatibility with older tests/helpers."""
        return None

    def _check_fallback_patterns(self, model_lower: str) -> str:
        """Legacy no-op retained for compatibility with older tests/helpers."""
        return 'unknown'

    def extract_provider(self, model: str) -> str:
        """Return the provider identifier for a model string."""
        return self._extract_provider(model)

    def _extract_provider(self, model: str) -> str:
        """Extract provider from model identifier using resolver.

        Uses explicit provider prefixes or exact catalog entries.

        Args:
            model: Model identifier string

        Returns:
            Provider name (e.g., 'openai', 'anthropic', etc.)

        """
        if not model:
            return 'unknown'

        try:
            from backend.inference.provider_resolver import get_resolver

            resolver = get_resolver()
            provider = resolver.resolve_provider(model)
            logger.debug('Resolved model=%s to provider=%s', model, provider)
            return provider
        except Exception as e:
            logger.warning(
                'Failed to determine provider for model %s without heuristics: %s',
                model,
                e,
            )
            return 'unknown'

    def _is_correct_provider_key(
        self, api_key: SecretStr, expected_provider: str
    ) -> bool:
        """Validate if an API key appears to be for the correct provider.

        This is a basic format check - different providers have different key formats.
        """
        try:
            key_value = api_key.get_secret_value()

            # Basic format validation based on provider conventions
            provider_patterns = {
                'openai': lambda k: k.startswith('sk-'),
                'anthropic': lambda k: k.startswith('sk-ant-'),
                'google': lambda k: k.startswith('AIza'),
                'xai': lambda k: k.startswith('xai-'),
            }

            pattern_check = provider_patterns.get(expected_provider)
            if pattern_check:
                return pattern_check(key_value)

            # If no pattern is known, assume it's correct
            return True

        except Exception:
            return False

    def _get_provider_key_from_env(self, provider: str) -> str | None:
        """Get API key for provider from environment variables using provider configuration."""
        if not provider or provider == 'unknown':
            return None
        # Use provider configuration to get the correct environment variable
        env_var = provider_config_manager.get_environment_variable(provider)
        if env_var:
            return os.environ.get(env_var)

        # Fallback to generic
        return os.environ.get('LLM_API_KEY')

    def get_provider_key_from_env(self, provider: str) -> str | None:
        """Return the configured environment API key for a provider, if present."""
        return self._get_provider_key_from_env(provider)

    def validate_and_clean_completion_params(
        self, model: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Validate and clean parameters for completion calls.

        Args:
            model: The LLM model identifier
            params: Dictionary of parameters to validate and clean

        Returns:
            Cleaned dictionary with only valid parameters for the provider

        """
        provider = self._extract_provider(model)
        logger.debug('Validating completion parameters for provider: %s', provider)

        # Use the provider configuration manager to validate and clean parameters
        cleaned_params = provider_config_manager.validate_and_clean_params(
            provider, params
        )

        logger.debug(
            'Parameter validation completed: %d -> %d parameters',
            len(params),
            len(cleaned_params),
        )
        return cleaned_params


# Global instance - persistent across reloads
if not hasattr(builtins, _INSTANCE_NAME):
    setattr(builtins, _INSTANCE_NAME, APIKeyManager())
api_key_manager: APIKeyManager = getattr(builtins, _INSTANCE_NAME)
