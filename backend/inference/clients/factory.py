"""Factory function for creating direct LLM clients."""

from __future__ import annotations

from typing import Any

from backend.core import json_compat as json
from backend.core.logging.logger import app_logger as logger
from backend.inference.clients.anthropic_client import AnthropicClient
from backend.inference.clients.base import (
    DirectLLMClient,
    TransportProfile,
    _resolve_transport_profile,
    _with_default_timeout,
)
from backend.inference.clients.openai_client import (
    OpenAIClient,
    OpenCodeResponsesClient,
)


def get_direct_client(
    model: str,
    api_key: str,
    base_url: str | None = None,
    timeout: float | int | None = None,
    provider: str | None = None,
) -> DirectLLMClient:
    """Factory function to get the correct direct client using explicit routing."""
    from backend.inference.provider_resolver import get_resolver

    resolver = get_resolver()
    provider = resolver.resolve_provider(model, config_provider=provider)
    stripped_model = _strip_transport_provider_prefix(model, provider)
    resolved_base_url = resolver.resolve_base_url(
        model, base_url, config_provider=provider
    )
    metadata = _model_metadata_for_log(
        requested_model=model,
        transport_provider=provider,
        runtime_model=stripped_model,
        resolved_base_url=resolved_base_url,
    )

    logger.info(
        'Resolved model=%s -> provider=%s, base_url=%s, stripped=%s, metadata=%s',
        model,
        provider,
        resolved_base_url or 'default',
        stripped_model,
        json.dumps(metadata, sort_keys=True),
    )

    client = _try_opencode_messages_client(
        provider, stripped_model, api_key, timeout, resolved_base_url
    )
    if client is not None:
        return client

    client = _try_opencode_responses_client(
        provider, stripped_model, api_key, timeout, resolved_base_url
    )
    if client is not None:
        return client

    client = _try_opencode_gemini_client(
        provider, stripped_model, api_key, timeout, resolved_base_url
    )
    if client is not None:
        return client

    client = _try_proxy_client(provider, resolved_base_url, model, api_key, timeout)
    if client is not None:
        return client

    return _route_by_provider(
        provider,
        stripped_model,
        api_key,
        base_url,
        resolved_base_url,
        timeout,
        model,
        resolver,
    )


def _strip_transport_provider_prefix(model: str, provider: str | None) -> str:
    """Strip ``provider/`` only when it names the transport provider."""
    if not provider or '/' not in model:
        return model
    prefix, stripped = model.split('/', 1)
    if prefix.strip().lower() == provider.strip().lower():
        return stripped
    return model


def _model_metadata_for_log(
    *,
    requested_model: str,
    transport_provider: str,
    runtime_model: str,
    resolved_base_url: str | None,
) -> dict[str, Any]:
    """Return deterministic, non-secret model metadata for run logs."""
    from backend.inference.capabilities.context_limits import derive_usable_input_tokens
    from backend.inference.catalog.catalog_loader import (
        compact_metadata_for_log,
        lookup_provider_model,
        runtime_model_id,
        runtime_parameter_mode,
    )
    from backend.inference.reasoning import reasoning_effort_options

    entry = lookup_provider_model(
        transport_provider,
        runtime_model,
        allow_aliases=True,
    )
    metadata: dict[str, Any] = {
        'requested_model': requested_model,
        'transport_provider': transport_provider,
        'runtime_model': runtime_model,
        'base_url': resolved_base_url or 'default',
        'catalog_match': entry is not None,
    }
    if entry is None:
        metadata['catalog_miss_reason'] = 'no exact provider catalog entry'
        return metadata

    usable_input = derive_usable_input_tokens(
        context_window_tokens=entry.context_window_tokens,
        max_output_tokens=entry.max_output_tokens,
        fallback_input_tokens=entry.max_input_tokens,
    )
    metadata['catalog'] = {
        'provider': entry.provider,
        'client': entry.client,
        'catalog_file': entry.catalog_file,
        'metadata': compact_metadata_for_log(entry.metadata),
        'name': entry.name,
        'runtime_model_id': runtime_model_id(entry),
        'verified': entry.verified,
        'featured': entry.featured,
        'context_window_tokens': entry.context_window_tokens,
        'configured_max_input_tokens': entry.max_input_tokens,
        'usable_input_tokens': usable_input,
        'max_output_tokens': entry.max_output_tokens,
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
        'capabilities': {
            'function_calling': entry.supports_function_calling,
            'parallel_tool_calls': entry.supports_parallel_tool_calls,
            'reasoning_effort': entry.supports_reasoning_effort,
            'resolved_reasoning_effort_options': list(
                reasoning_effort_options(entry, include_disabled=True)
            ),
            'prompt_cache': entry.supports_prompt_cache,
            'response_schema': entry.supports_response_schema,
            'stop_words': entry.supports_stop_words,
            'vision': entry.supports_vision,
        },
        'param_overrides': {
            'strip_reasoning_effort': entry.strip_reasoning_effort,
            'thinking_mode': entry.thinking_mode,
            'strip_temperature': entry.strip_temperature,
            'strip_top_p': entry.strip_top_p,
            'strip_penalties': entry.strip_penalties,
            'use_max_completion_tokens': entry.use_max_completion_tokens,
            'default_temperature': entry.default_temperature,
        },
        'runtime_parameter_mode': runtime_parameter_mode(entry),
    }
    return metadata


def _try_opencode_responses_client(
    provider: str,
    stripped_model: str,
    api_key: str,
    timeout: float | int | None,
    resolved_base_url: str | None,
) -> OpenCodeResponsesClient | None:
    if provider != 'opencode':
        return None
    from backend.inference.provider_resolver import opencode_required_endpoint

    if opencode_required_endpoint(stripped_model) != '/responses':
        return None
    profile = _resolve_transport_profile('opencode', resolved_base_url)
    return OpenCodeResponsesClient(
        model_name=stripped_model,
        api_key=api_key,
        base_url=resolved_base_url,
        profile=profile,
        timeout=timeout,
        provider_name='opencode',
    )


def _try_opencode_gemini_client(
    provider: str,
    stripped_model: str,
    api_key: str,
    timeout: float | int | None,
    resolved_base_url: str | None,
) -> DirectLLMClient | None:
    if provider != 'opencode':
        return None
    from backend.inference.provider_resolver import opencode_required_endpoint
    from backend.inference.providers.opencode_gemini_ops import (
        OpenCodeGeminiClient,
    )

    endpoint = opencode_required_endpoint(stripped_model)
    if not endpoint.startswith('/models/'):
        return None
    return OpenCodeGeminiClient(
        model_name=stripped_model,
        api_key=api_key,
        endpoint_path=endpoint,
        base_url=resolved_base_url,
        timeout=timeout,
        provider_name='opencode',
    )


def _try_opencode_messages_client(
    provider, stripped_model, api_key, timeout, resolved_base_url
):
    if provider not in {'opencode', 'opencode-go'}:
        return None
    from backend.inference.provider_resolver import (
        opencode_go_required_endpoint,
        opencode_required_endpoint,
    )

    if provider == 'opencode-go':
        required_endpoint = opencode_go_required_endpoint(stripped_model)
    else:
        required_endpoint = opencode_required_endpoint(stripped_model)
    if required_endpoint != '/messages':
        return None
    anthropic_base_url = resolved_base_url
    if anthropic_base_url and anthropic_base_url.rstrip('/').endswith('/v1'):
        anthropic_base_url = anthropic_base_url.rstrip('/')[:-3]
    return AnthropicClient(
        model_name=stripped_model,
        api_key=api_key,
        timeout=timeout,
        base_url=anthropic_base_url,
        provider_name=provider,
    )


def _try_proxy_client(provider, resolved_base_url, model, api_key, timeout):
    if not resolved_base_url:
        return None
    _NATIVE_ENDPOINTS = {
        'anthropic': 'https://api.anthropic.com',
        'google': 'https://generativelanguage.googleapis.com',
    }
    native = _NATIVE_ENDPOINTS.get(provider or '', '')
    is_native = native and resolved_base_url.rstrip('/').startswith(native.rstrip('/'))
    if is_native or provider not in ('anthropic', 'google'):
        return None
    profile = _resolve_transport_profile(provider, resolved_base_url)
    return OpenAIClient(
        model_name=model,
        api_key=api_key,
        base_url=resolved_base_url,
        profile=profile,
        timeout=timeout,
        provider_name=provider,
    )


def _route_by_provider(
    provider,
    stripped_model,
    api_key,
    base_url,
    resolved_base_url,
    timeout,
    model,
    resolver,
):
    if provider == 'anthropic':
        return AnthropicClient(
            model_name=stripped_model,
            api_key=api_key,
            timeout=timeout,
            provider_name='anthropic',
        )

    from backend.inference.providers.gemini_ops import GeminiClient

    if provider == 'google':
        return GeminiClient(model_name=stripped_model, api_key=api_key, timeout=timeout)

    model_family = provider
    if '/' in stripped_model:
        try:
            model_family = resolver.resolve_provider(stripped_model)
        except (ValueError, Exception):
            pass
    profile = _resolve_transport_profile(model_family, resolved_base_url)
    return OpenAIClient(
        model_name=stripped_model,
        api_key=api_key,
        base_url=resolved_base_url,
        profile=profile,
        timeout=timeout,
        provider_name=provider,
    )
