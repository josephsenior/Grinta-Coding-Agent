"""Routes for retrieving and updating user/server settings with caching."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Annotated, Any, cast

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import SecretStr

from backend.core.config.api_key_manager import api_key_manager
from backend.core.constants import SECRET_PLACEHOLDER, SETTINGS_CACHE_TTL
from backend.core.logger import FORGE_logger as logger

# Import these at runtime so FastAPI can resolve them in Annotated types
from backend.core.provider_types import PROVIDER_TOKEN_TYPE, ProviderType
from backend.core.pydantic_compat import model_dump_with_options
from backend.server.dependencies import get_dependencies
from backend.server.settings import GETSettingsModel
from backend.server.shared import config
from backend.server.user_auth import (
    get_provider_tokens,
    get_secrets_store,
    get_user_id,
    get_user_settings,
    get_user_settings_store,
)
from backend.storage.data_models.settings import Settings
from backend.storage.data_models.user_secrets import UserSecrets
from backend.storage.settings.settings_store import SettingsStore

if TYPE_CHECKING:
    from backend.core.provider_types import ProviderToken

# Rebuild GETSettingsModel to resolve forward references
GETSettingsModel.model_rebuild()

router = APIRouter(prefix="/api/v1", dependencies=get_dependencies())

# 🚀 PERFORMANCE FIX: Global cache for settings to avoid repeated database calls
#   Cache key: user_id (or 'default' for single-tenant), Cache value: (settings_response, timestamp)
#   TTL: 60 seconds (OPTIMIZED: increased from 30s for 2-3x improvement)
import time as time_module

_settings_cache: dict[str, tuple[GETSettingsModel, float]] = {}
_PROVIDER_TOKEN_MAPPING: dict[str, str] = {
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "together": "TOGETHER_API_KEY",
    "deepinfra": "DEEPINFRA_API_KEY",
    "replicate": "REPLICATE_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
}


def _settings_to_dict(settings: Settings, **dump_kwargs: Any) -> dict[str, Any]:
    context = dump_kwargs.pop("context", {}) or {}
    context = {**context, "expose_secrets": True}
    return settings.model_dump(context=context, **dump_kwargs)


def _secret_value(api_key: SecretStr | str | None) -> str | None:
    if api_key is None:
        return None
    if hasattr(api_key, "get_secret_value"):
        return cast(SecretStr, api_key).get_secret_value()
    return str(api_key)


def _log_api_key_state(label: str, api_key: SecretStr | str | None) -> None:
    logger.debug("[STORE_LLM_SETTINGS] API key state updated")


def _ensure_secrets_store(settings: Settings) -> Settings:
    if settings.secrets_store:
        return settings
    return settings.model_copy(
        update={"secrets_store": UserSecrets(provider_tokens={}, custom_secrets={})}
    )


def _merge_with_existing_settings(
    new_settings: Settings, existing_settings: Settings | None
) -> Settings:
    if not existing_settings:
        return _ensure_secrets_store(new_settings)

    merged = _settings_to_dict(existing_settings)
    merged.update(_settings_to_dict(new_settings, exclude_none=True))
    return _ensure_secrets_store(Settings(**merged))


def _rebuild_settings_with(settings: Settings, **updates: Any) -> Settings:
    data = _settings_to_dict(settings)
    data.update(updates)
    if "llm_api_key" not in updates:
        data["llm_api_key"] = settings.llm_api_key

    secrets_store_override = updates.get("secrets_store")
    if isinstance(secrets_store_override, UserSecrets):
        data["secrets_store"] = secrets_store_override.model_dump()
    elif "secrets_store" not in updates:
        data["secrets_store"] = settings.secrets_store.model_dump()

    return Settings(**data)


def _provider_token_key_for(model: str | None) -> tuple[str | None, str | None]:
    if not model:
        return None, None
    provider = api_key_manager._extract_provider(model)
    return _PROVIDER_TOKEN_MAPPING.get(provider), provider


def _current_provider_tokens(settings: Settings) -> dict[str, ProviderToken]:
    if not (settings.secrets_store and settings.secrets_store.provider_tokens):
        return {}

    tokens: dict[str, ProviderToken] = {}
    for key, token in settings.secrets_store.provider_tokens.items():
        key_str = key.value if isinstance(key, ProviderType) else str(key)
        tokens[key_str] = token
    return tokens


def _apply_provider_token(settings: Settings, token_key: str) -> Settings:
    from backend.core.provider_types import ProviderToken

    if not settings.llm_api_key:
        return settings

    current_tokens = _current_provider_tokens(settings)
    current_tokens[token_key] = ProviderToken(token=settings.llm_api_key)

    new_secrets_store = UserSecrets(
        provider_tokens=cast(dict[ProviderType, ProviderToken], current_tokens),
        custom_secrets=(
            dict(settings.secrets_store.custom_secrets)
            if settings.secrets_store and settings.secrets_store.custom_secrets
            else {}
        ),
    )

    return _rebuild_settings_with(settings, secrets_store=new_secrets_store)


def _ensure_openrouter_base_url(settings: Settings) -> Settings:
    if not (
        settings.llm_model
        and settings.llm_model.startswith("openrouter/")
        and settings.llm_base_url
    ):
        return settings

    base_url_lower = str(settings.llm_base_url).lower()
    if base_url_lower == "gemini-2.5-pro" or "gemini" in base_url_lower:
        logger.debug(
            "🔧 STORE_LLM_SETTINGS FINAL FIX: Clearing base_url '%s' for OpenRouter model",
            settings.llm_base_url,
        )
        return _rebuild_settings_with(settings, llm_base_url="")

    return settings


def _preserve_llm_api_key(
    settings: Settings, existing_settings: Settings | None
) -> None:
    incoming_key = _secret_value(settings.llm_api_key)
    if incoming_key:
        logger.debug("[STORE SETTINGS] Received API key metadata")
        if incoming_key == SECRET_PLACEHOLDER:
            logger.info("[STORE SETTINGS] Preserving existing API key (placeholder)")
            preserved_key = (
                cast(SecretStr | None, existing_settings.llm_api_key)
                if existing_settings and existing_settings.llm_api_key
                else None
            )
            if preserved_key:
                settings.llm_api_key = preserved_key
                logger.info("[STORE SETTINGS] Preserving existing API key")
            else:
                logger.warning("[STORE SETTINGS] No existing API key to preserve")
                settings.llm_api_key = cast(SecretStr | None, None)
        return

    logger.info("[STORE SETTINGS] No API key received from client")
    if existing_settings and existing_settings.llm_api_key:
        logger.info("[STORE SETTINGS] Preserving existing API key (None received)")
        settings.llm_api_key = cast(
            SecretStr | None,
            existing_settings.llm_api_key,  # type: ignore[arg-type]
        )


def _set_environment_variables(
    model: str | None, api_key: SecretStr | str | None, stage: str
) -> None:
    if not (model and api_key):
        return
    if isinstance(api_key, SecretStr):
        normalized_key = api_key
    else:
        normalized_key = SecretStr(str(api_key))
    try:
        api_key_manager.set_environment_variables(model, normalized_key)
        provider = api_key_manager._extract_provider(model)
        if provider == "google":
            os.environ.get("GEMINI_API_KEY")
            logger.debug("GEMINI provider env key present")
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("%s Failed to set environment variables: %s", stage, exc)


def _looks_like_model_identifier(value: str) -> bool:
    indicators = [
        "gemini",
        "gpt",
        "claude",
        "llama",
        "mistral",
        "deepseek",
        "qwen",
    ]
    return any(indicator in value for indicator in indicators)


def _sanitize_llm_base_url(settings: Settings, provider: str | None) -> None:
    if not settings.llm_base_url:
        return

    base_url_str = str(settings.llm_base_url).strip()
    base_url_lower = base_url_str.lower()

    if _looks_like_model_identifier(base_url_lower) and not base_url_lower.startswith(
        ("http://", "https://")
    ):
        logger.warning(
            "🚨 CRITICAL: base_url appears to be a model name, not a URL: '%s' - CLEARING IT",
            settings.llm_base_url,
        )
        settings.llm_base_url = None
        return

    if provider == "google":
        logger.info(
            "Clearing base URL for Google provider as it handles routing internally: '%s'",
            settings.llm_base_url,
        )
        settings.llm_base_url = None
        return

    if provider in {"openrouter", "openai", "anthropic", "google"}:
        if not base_url_lower.startswith(("http://", "https://")):
            logger.info(
                "Clearing invalid base URL '%s' for %s model - missing protocol",
                settings.llm_base_url,
                provider,
            )
            settings.llm_base_url = None
            return
        if provider == "openrouter" and any(
            incorrect in base_url_lower
            for incorrect in ("gemini", "anthropic", "openai")
        ):
            logger.info(
                "Clearing incorrect base URL '%s' for %s model",
                settings.llm_base_url,
                provider,
            )
            settings.llm_base_url = None


def _process_llm_model_configuration(settings: Settings) -> None:
    if not settings.llm_model or not settings.llm_model.strip():
        return

    logger.info("🔧 PROCESSING LLM SETTINGS")

    if settings.llm_api_key:
        _set_environment_variables(
            settings.llm_model, settings.llm_api_key, "🔑 Initial"
        )

    correct_api_key = api_key_manager.get_api_key_for_model(
        settings.llm_model, settings.llm_api_key
    )

    if correct_api_key:
        settings.llm_api_key = cast(SecretStr | None, correct_api_key)
        logger.info("✅ Validated API key for model")
        _set_environment_variables(settings.llm_model, correct_api_key, "✅ Validated")
    elif settings.llm_api_key:
        logger.warning("⚠️ Using provided API key as fallback")
        _set_environment_variables(
            settings.llm_model, settings.llm_api_key, "⚠️ Fallback"
        )

    provider = api_key_manager._extract_provider(settings.llm_model)
    _sanitize_llm_base_url(settings, provider)


def _apply_runtime_and_git_overrides(settings: Settings) -> None:
    git_config_updated = False
    if settings.vcs_user_name is not None:
        config.vcs_user_name = settings.vcs_user_name
        git_config_updated = True
    if settings.vcs_user_email is not None:
        config.vcs_user_email = settings.vcs_user_email
        git_config_updated = True
    if git_config_updated:
        logger.info(
            "Updated global git configuration: name=%s, email=%s",
            config.vcs_user_name,
            config.vcs_user_email,
        )


def invalidate_settings_cache(user_id: str | None = None) -> None:
    """Invalidate settings cache for a specific user or all users.

    Args:
        user_id: User ID to invalidate (None = invalidate all)
    """
    if user_id:
        cache_key = user_id if user_id else "default"
        _settings_cache.pop(cache_key, None)
        logger.info("Invalidated settings cache for user '%s'", cache_key)
    else:
        _settings_cache.clear()
        logger.info("Cleared all settings cache entries")


@router.get(
    "/settings",
    response_model=GETSettingsModel,
    responses={
        200: {
            "description": "Settings retrieved successfully",
            "content": {
                "application/json": {
                    "examples": {
                        "basic": {
                            "summary": "Basic configuration",
                            "value": {
                                "LLM_MODEL": "anthropic/claude-3-5-sonnet-20241022",
                                "LLM_API_KEY": "sk-ant-***",
                                "AGENT": "Orchestrator",
                                "LANGUAGE": "en",
                                "LLM_NUM_RETRIES": 6,
                                "LLM_TIMEOUT": 180,
                            },
                        }
                    }
                }
            },
        },
        404: {"description": "Settings not found"},
        401: {"description": "Invalid token"},
    },
)
async def load_settings(
    provider_tokens: Annotated[
        PROVIDER_TOKEN_TYPE | None, Depends(get_provider_tokens)
    ],
    settings_store: Annotated[Any, Depends(get_user_settings_store)],
    settings: Annotated[Settings, Depends(get_user_settings)],
    secrets_store: Annotated[Any, Depends(get_secrets_store)],
    user_id: Annotated[str | None, Depends(get_user_id)] = None,
) -> Any:
    """Load user settings with token status information.

    🚀 PERFORMANCE OPTIMIZED: 60s cache with proper per-user key for 2-3x improvement.
       - Increased TTL from 30s to 60s
       - Fixed cache key to use user_id instead of settings_hash
       - Expected: 1,295ms → ~300-500ms for 10 concurrent users

    Args:
        provider_tokens: Provider tokens dependency
        settings_store: Settings store dependency
        settings: User settings dependency
        secrets_store: Secrets store dependency
        user_id: User ID (None for single-tenant, defaults to 'default')

    Returns:
        Settings model or error response

    """
    try:
        if not settings:
            # Return default settings for development when no settings exist
            logger.info("No settings found, returning default settings for development")
            return _build_default_settings_response()

        # 🚀 PERFORMANCE FIX: Check cache first with proper user_id key
        # Use user_id as cache key (fallback to 'default' for single-tenant mode)
        cache_key = user_id if user_id else "default"
        current_time = time_module.time()

        if cache_key in _settings_cache:
            cached_response, cached_time = _settings_cache[cache_key]
            if current_time - cached_time < SETTINGS_CACHE_TTL:
                logger.info("Settings cache hit for user '%s'", cache_key)
                return cached_response

        # Cache miss - load from database
        logger.info("Settings cache miss for user '%s', loading from store", cache_key)
        user_secrets = settings.secrets_store
        provider_tokens_set = _build_provider_tokens_set(user_secrets, provider_tokens)

        response = _build_settings_response(settings, provider_tokens_set)

        # 🚀 PERFORMANCE FIX: Cache the response with user_id key
        _settings_cache[cache_key] = (response, current_time)
        logger.info(
            "Cached settings for user '%s' (TTL: %ds)", cache_key, SETTINGS_CACHE_TTL
        )

        return response

    except Exception as e:
        logger.warning(
            "Error loading settings: %s, returning default settings for development", e
        )
        return _build_default_settings_response()


def _build_provider_tokens_set(
    user_secrets: Any,
    provider_tokens: PROVIDER_TOKEN_TYPE | None,
) -> dict[ProviderType, str | None]:
    """Build provider tokens set dict.

    Args:
        user_secrets: User secrets object
        provider_tokens: Provider tokens

    Returns:
        Dictionary mapping provider type to host

    """
    git_providers = user_secrets.provider_tokens if user_secrets else provider_tokens
    provider_tokens_set: dict[ProviderType, str | None] = {}

    if git_providers:
        for provider_type, provider_token in git_providers.items():
            if provider_token.token or provider_token.user_id:
                provider_tokens_set[provider_type] = provider_token.host

    return provider_tokens_set


def _build_settings_response(
    settings: Settings,
    provider_tokens_set: dict[ProviderType, str | None] | None,
) -> GETSettingsModel:
    """Build settings response with masked sensitive data.

    Args:
        settings: User settings
        provider_tokens_set: Provider tokens status

    Returns:
        Settings model with masked keys

    """
    logger.debug(
        "Loading settings for user_id=%s autonomy_level=%s",
        getattr(settings, "user_id", "unknown"),
        getattr(settings, "autonomy_level", "NOT_FOUND"),
    )
    settings_with_token_data = GETSettingsModel(
        **model_dump_with_options(settings, exclude={"secrets_store"}),
        llm_api_key_set=settings.llm_api_key is not None and bool(settings.llm_api_key),
        provider_tokens_set=provider_tokens_set or None,
    )

    # Mask sensitive data without mutating original instance
    return settings_with_token_data.model_copy(
        update={
            "llm_api_key": None,
        },
    )


def _build_unauthorized_response(settings: Settings | None) -> JSONResponse:
    """Build unauthorized response for invalid tokens.

    Args:
        settings: User settings (may be None)

    Returns:
        401 Unauthorized JSON response

    """
    logger.info("Returning 401 Unauthorized - Invalid token")

    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"error": "Invalid token"},
    )


async def store_llm_settings(
    settings: Settings,
    settings_store: SettingsStore,
    existing_settings: Settings | None = None,
) -> Settings:
    """Merge new LLM settings with existing settings.

    Preserves existing values for any fields that are None in new settings.
    Also auto-populates provider_tokens based on the selected model.

    Args:
        settings: New settings to merge
        settings_store: Settings storage
        existing_settings: Optional existing settings to merge with

    Returns:
        Merged settings with existing values preserved

    """
    _log_api_key_state("INCOMING", settings.llm_api_key)

    existing_settings = existing_settings or await settings_store.load()
    settings = _merge_with_existing_settings(settings, existing_settings)

    provider_token_key, provider = _provider_token_key_for(settings.llm_model)
    if provider:
        _sanitize_llm_base_url(settings, provider)

    if provider_token_key and settings.llm_api_key:
        settings = _apply_provider_token(settings, provider_token_key)

    settings = _ensure_openrouter_base_url(settings)

    _log_api_key_state("OUTGOING", settings.llm_api_key)
    return settings


@router.patch(
    "/settings",
    response_model=None,
    responses={
        200: {"description": "Settings patched successfully", "model": dict},
        500: {"description": "Error patching settings", "model": dict},
    },
)
@router.post(
    "/settings",
    response_model=None,
    responses={
        200: {"description": "Settings stored successfully", "model": dict},
        500: {"description": "Error storing settings", "model": dict},
    },
)
async def store_settings(
    settings: Settings,
    settings_store: Annotated[Any, Depends(get_user_settings_store)],
) -> JSONResponse:
    """Store user settings with clean, secure API key handling.

    Uses the new APIKeyManager for secure, provider-aware API key validation and storage.

    Args:
        settings: Settings to store
        settings_store: Settings storage dependency

    Returns:
        JSON response with success/error message

    """
    try:
        logger.info("Storing settings with clean API key handling")
        existing_settings = await settings_store.load()

        _preserve_llm_api_key(settings, existing_settings)
        _process_llm_model_configuration(settings)

        if existing_settings:
            settings = await store_llm_settings(
                settings, settings_store, existing_settings=existing_settings
            )
            if settings.user_consents_to_analytics is None:
                settings.user_consents_to_analytics = (
                    existing_settings.user_consents_to_analytics
                )

        _apply_runtime_and_git_overrides(settings)

        settings = convert_to_settings(settings)
        logger.info("Settings validation complete, storing clean settings")

        _set_environment_variables(settings.llm_model, settings.llm_api_key, "🌐 Final")

        await settings_store.store(settings)

        try:
            user_id = "default"  # Simplified for single-tenant mode
            invalidate_settings_cache(user_id)
            logger.info(
                "Invalidated settings cache for user '%s' after update", user_id
            )
        except Exception as e:  # pragma: no cover - cache invalidation guard
            logger.warning("Settings cache invalidation failed: %s", e)

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"message": "Settings stored"},
        )
    except Exception as e:
        logger.warning("Something went wrong storing settings: %s", e)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "Something went wrong storing settings"},
        )


def convert_to_settings(settings_with_token_data: Settings) -> Settings:
    """Convert settings with token data to clean Settings object.

    Filters out extra fields while preserving API keys.

    Args:
        settings_with_token_data: Settings object with potential extra fields

    Returns:
        Clean Settings object with only valid fields

    """
    filtered_settings_data = _filtered_settings_data(settings_with_token_data)
    _preserve_secret_field(
        filtered_settings_data,
        settings_with_token_data.llm_api_key,
        "llm_api_key",
    )
    _apply_final_openrouter_fixes(filtered_settings_data)
    return Settings(**filtered_settings_data)


def _filtered_settings_data(settings: Settings) -> dict[str, Any]:
    settings_data = model_dump_with_options(settings, exclude_none=False)
    _log_settings_snapshot("before filtering", settings_data)

    filtered = {k: v for k, v in settings_data.items() if k in Settings.model_fields}
    _log_settings_snapshot("after filtering", filtered)
    return filtered


def _log_settings_snapshot(label: str, data: dict[str, Any]) -> None:
    logger.info(
        "Settings data %s: autonomy_level=%s",
        label,
        data.get("autonomy_level", "NOT_FOUND"),
    )
    logger.info("API key presence logged")


def _preserve_secret_field(
    target: dict[str, Any], value: SecretStr | str | None, field_name: str
) -> None:
    if value is None:
        return
    if isinstance(value, SecretStr):
        target[field_name] = value
    elif isinstance(value, str):
        target[field_name] = SecretStr(value)

    if field_name == "llm_api_key":
        logger.info("API key preserved")


def _apply_final_openrouter_fixes(settings_data: dict[str, Any]) -> None:
    model = settings_data.get("llm_model")
    if not _is_openrouter_model(model):
        return

    logger.debug("Final settings fix: openrouter base_url normalization")
    _clear_invalid_openrouter_base_url(settings_data)
    _replace_openrouter_api_key_if_needed(settings_data)


def _is_openrouter_model(model: str | None) -> bool:
    return bool(model and model.startswith("openrouter/"))


def _clear_invalid_openrouter_base_url(settings_data: dict[str, Any]) -> None:
    base_url = settings_data.get("llm_base_url")
    if not base_url:
        return
    if "gemini" in base_url.lower() or base_url == "gemini-2.5-pro":
        logger.debug("Final settings fix: clearing mismatched base_url")
        settings_data["llm_base_url"] = ""


def _replace_openrouter_api_key_if_needed(settings_data: dict[str, Any]) -> None:
    api_key = settings_data.get("llm_api_key")
    if not api_key:
        return
    try:
        key_value = (
            api_key.get_secret_value()
            if hasattr(api_key, "get_secret_value")
            else str(api_key)
        )
    except Exception:  # pragma: no cover - defensive logging
        logger.debug("Final settings fix: error checking API key")
        return

    if not key_value.startswith("AIza"):
        return

    logger.debug("Final settings fix: attempting API key replacement from env")
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if not openrouter_key:
        return

    settings_data["llm_api_key"] = SecretStr(openrouter_key)
    logger.debug("Final settings fix: replaced API key from env")


def _build_default_settings_response() -> GETSettingsModel:
    """Build default settings response for development.

    Returns:
        Default settings model for unauthenticated/development use

    """
    # Create default settings similar to client DEFAULT_SETTINGS
    default_settings = Settings(
        llm_model="anthropic/claude-3-5-sonnet-latest",
        llm_base_url="",
        agent="Orchestrator",
        language="en",
        confirmation_mode=False,
        security_analyzer="llm",
        enable_default_condenser=True,
        condenser_max_size=120,
        enable_sound_notifications=False,
        user_consents_to_analytics=False,
        enable_proactive_conversation_starters=False,
        enable_solvability_analysis=False,
        max_budget_per_task=None,
        email="",
        email_verified=True,
        mcp_config=None,
        vcs_user_name="forge",
        vcs_user_email="Forge@forge.dev",
        # Autonomy Configuration
        autonomy_level="balanced",
        enable_permissions=True,
        enable_checkpoints=True,
        # Advanced LLM Configuration
        llm_temperature=None,
        llm_top_p=None,
        llm_max_output_tokens=None,
        llm_timeout=None,
        llm_num_retries=None,
        llm_caching_prompt=None,
        llm_disable_vision=None,
        llm_custom_llm_provider=None,
    )

    # Build response similar to _build_settings_response
    settings_with_token_data = GETSettingsModel(
        **model_dump_with_options(default_settings, exclude={"secrets_store"}),
        llm_api_key_set=False,
        provider_tokens_set=None,
    )

    return settings_with_token_data.model_copy(
        update={
            "llm_api_key": None,
        },
    )
