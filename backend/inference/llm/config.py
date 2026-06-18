"""Split from ``llm.py`` — see ``backend.inference.llm`` facade."""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
)

from backend.core.logger import app_logger as logger
from backend.inference.capabilities.model_features import ModelFeatures
from backend.inference.exceptions import (
    AuthenticationError,
)
from backend.inference.llm.utils import create_pretrained_tokenizer

if TYPE_CHECKING:
    pass


def _get_provider_resolver() -> Any:
    """Return the provider resolver instance."""
    from backend.inference.provider_resolver import get_resolver

    return get_resolver()


def _apply_base_url_discovery(config: Any, resolver: Any) -> None:
    """Discover and set base_url if not configured."""
    if not config.base_url:
        discovered = resolver.resolve_base_url(
            config.model,
            config_provider=getattr(config, 'custom_llm_provider', None),
        )
        if discovered:
            logger.info('Auto-discovered base_url for %s: %s', config.model, discovered)
            config.base_url = discovered


def _is_local_model(config: Any, resolver: Any) -> bool:
    """Check if model is local (no API key required)."""
    if resolver.is_local_model(config.model):
        return True
    base = config.base_url or ''
    return any(h in base for h in ('localhost', '127.0.0.1', '0.0.0.0'))


def _validate_api_key_or_local(
    api_key_value: str | None, config: Any, resolver: Any
) -> None:
    """Raise AuthenticationError if API key missing and model is not local."""
    if api_key_value or _is_local_model(config, resolver):
        return
    logger.error('No API key available for model: %s', config.model)
    raise AuthenticationError(
        f"No API key provided for model '{config.model}'. "
        'Please set it in Settings -> Models -> API Keys.',
        model=config.model,
    )


def _resolve_function_calling_config(
    native_tool_calling: bool | None, model: str
) -> bool:
    """Determine whether function calling is active."""
    try:
        from backend.inference import llm as llm_module

        features = llm_module.get_features(model)
        return (
            native_tool_calling
            if native_tool_calling is not None
            else features.supports_function_calling
        )
    except (KeyError, ValueError) as exc:
        logger.warning(
            'Could not detect function-calling support for model %s: %s  '
            '— defaulting to disabled. If this model supports tools, '
            'set native_tool_calling=true in the LLM config.',
            model,
            exc,
        )
        return native_tool_calling or False


def _load_cached_features(model: str) -> ModelFeatures:
    """Load model features for caching. Fall back to empty defaults on error."""
    try:
        from backend.inference import llm as llm_module

        return llm_module.get_features(model)
    except (KeyError, ValueError) as exc:
        logger.warning(
            'Model feature lookup failed for %s: %s  '
            '— using empty defaults. Token limits, vision, and '
            'other capabilities may be inaccurate.',
            model,
            exc,
        )
        return ModelFeatures()


def _apply_custom_tokenizer(config: Any) -> None:
    """Replace config.custom_tokenizer with created tokenizer if configured."""
    if not config.custom_tokenizer:
        return
    tokenizer = create_pretrained_tokenizer(config.custom_tokenizer)
    if tokenizer is not None:
        config.custom_tokenizer = tokenizer


def _safe_call_kwargs_for_log(call_kwargs: dict[str, Any]) -> dict[str, Any]:
    """Return compact, non-secret kwargs actually sent to the LLM client."""
    logged: dict[str, Any] = {}
    scalar_keys = (
        'model',
        'temperature',
        'top_p',
        'top_k',
        'max_tokens',
        'max_completion_tokens',
        'timeout',
        'seed',
        'reasoning_effort',
        'parallel_tool_calls',
        'tool_choice',
    )
    for key in scalar_keys:
        if key in call_kwargs:
            logged[key] = call_kwargs[key]
    if 'thinking' in call_kwargs:
        logged['thinking'] = call_kwargs['thinking']
    if 'response_format' in call_kwargs:
        response_format = call_kwargs['response_format']
        if isinstance(response_format, dict):
            logged['response_format'] = {
                key: response_format.get(key)
                for key in ('type', 'name')
                if key in response_format
            } or sorted(response_format)
        else:
            logged['response_format'] = type(response_format).__name__
    tools = call_kwargs.get('tools')
    if isinstance(tools, list):
        logged['tool_count'] = len(tools)
        names: list[str] = []
        for tool in tools[:25]:
            if not isinstance(tool, dict):
                continue
            function = tool.get('function')
            if isinstance(function, dict) and function.get('name'):
                names.append(str(function['name']))
            elif tool.get('name'):
                names.append(str(tool['name']))
        if names:
            logged['tool_names_preview'] = names
            logged['tool_names_truncated'] = len(tools) > len(names)
    return logged


def _llm_model_metadata_for_log(config: Any, resolver: Any) -> dict[str, Any]:
    """Return visible active model metadata for run logs."""
    from backend.inference.capabilities.context_limits import limits_from_config
    from backend.inference.catalog_loader import (
        compact_metadata_for_log,
        lookup,
        runtime_model_id,
        runtime_parameter_mode,
    )
    from backend.inference.reasoning import reasoning_effort_options

    model = str(getattr(config, 'model', '') or '').strip()
    config_provider = getattr(config, 'custom_llm_provider', None)
    try:
        resolved_provider = resolver.resolve_provider(
            model, config_provider=config_provider
        )
    except Exception:
        resolved_provider = config_provider or 'unknown'
    limits = limits_from_config(config, unknown_default=False)
    fallback_limits = limits_from_config(config, unknown_default=True)
    metadata: dict[str, Any] = {
        'model': model,
        'custom_llm_provider': config_provider,
        'resolved_provider': resolved_provider,
        'base_url': getattr(config, 'base_url', None) or 'default',
        'context_window_tokens': getattr(config, 'context_window_tokens', None),
        'max_input_tokens': getattr(config, 'max_input_tokens', None),
        'max_output_tokens': getattr(config, 'max_output_tokens', None),
        'resolved_limits': {
            'context_window_tokens': limits.context_window_tokens,
            'usable_input_tokens': limits.usable_input_tokens,
            'max_output_tokens': limits.max_output_tokens,
            'source': limits.source,
        },
        'context_budget_limits': {
            'context_window_tokens': fallback_limits.context_window_tokens,
            'usable_input_tokens': fallback_limits.usable_input_tokens,
            'max_output_tokens': fallback_limits.max_output_tokens,
            'source': fallback_limits.source,
        },
        'config_params': {
            'temperature': getattr(config, 'temperature', None),
            'top_p': getattr(config, 'top_p', None),
            'top_k': getattr(config, 'top_k', None),
            'reasoning_effort': getattr(config, 'reasoning_effort', None),
            'native_tool_calling': getattr(config, 'native_tool_calling', None),
            'prompt_history_token_budget': getattr(
                config, 'prompt_history_token_budget', None
            ),
            'prompt_history_budget_ratio': getattr(
                config, 'prompt_history_budget_ratio', None
            ),
            'prompt_history_max_events': getattr(
                config, 'prompt_history_max_events', None
            ),
        },
    }
    entry = lookup(model)
    metadata['catalog_match'] = entry is not None
    if entry is not None:
        metadata['catalog'] = {
            'provider': entry.provider,
            'client': entry.client,
            'catalog_file': entry.catalog_file,
            'metadata': compact_metadata_for_log(entry.metadata),
            'name': entry.name,
            'runtime_model_id': runtime_model_id(entry),
            'verified': entry.verified,
            'featured': entry.featured,
            'supports_function_calling': entry.supports_function_calling,
            'supports_parallel_tool_calls': entry.supports_parallel_tool_calls,
            'supports_reasoning_effort': entry.supports_reasoning_effort,
            'resolved_reasoning_effort_options': list(
                reasoning_effort_options(entry, include_disabled=True)
            ),
            'supports_prompt_cache': entry.supports_prompt_cache,
            'supports_response_schema': entry.supports_response_schema,
            'supports_vision': entry.supports_vision,
            'strip_reasoning_effort': entry.strip_reasoning_effort,
            'thinking_mode': entry.thinking_mode,
            'strip_temperature': entry.strip_temperature,
            'strip_top_p': entry.strip_top_p,
            'strip_penalties': entry.strip_penalties,
            'use_max_completion_tokens': entry.use_max_completion_tokens,
            'default_temperature': entry.default_temperature,
            'runtime_parameter_mode': runtime_parameter_mode(entry),
            'pricing_per_million': {
                'input': entry.input_price_per_m,
                'cached_input': entry.cached_input_price_per_m,
                'cached_write': entry.cached_write_price_per_m,
                'output': entry.output_price_per_m,
                'long_context_threshold_tokens': entry.long_context_threshold_tokens,
                'long_input': entry.long_input_price_per_m,
                'long_cached_input': entry.long_cached_input_price_per_m,
                'long_cached_write': entry.long_cached_write_price_per_m,
                'long_output': entry.long_output_price_per_m,
            },
        }
    return metadata
