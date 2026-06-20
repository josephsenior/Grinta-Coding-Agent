"""Pinned runtime model profile for stable params and context limits within a session."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from backend.inference.capabilities.context_limits import (
    DEFAULT_UNKNOWN_CONTEXT_WINDOW_TOKENS,
    ModelContextLimits,
    derive_usable_input_tokens,
    limits_from_catalog,
)
from backend.inference.capabilities.param_profiles import resolve_param_profile_id
from backend.inference.catalog.catalog_loader import lookup
from backend.inference.catalog.provider_catalog import normalize_provider_name

_RUNTIME_PROFILE_KEY = '_grinta_runtime_profile'


@dataclass(frozen=True, slots=True)
class RuntimeModelProfile:
    model: str
    provider: str | None
    param_profile_id: str
    context_limits: ModelContextLimits
    resolved_at: float
    source: str


def resolve_runtime_profile(
    llm_config: object | None,
    *,
    provider: str | None = None,
) -> RuntimeModelProfile:
    """Resolve and return the runtime profile for an LLM config."""
    model = str(getattr(llm_config, 'model', '') or '').strip()
    configured_provider = normalize_provider_name(
        provider or getattr(llm_config, 'custom_llm_provider', None)
    )
    if configured_provider is None and '/' in model:
        configured_provider = normalize_provider_name(model.split('/', 1)[0])

    profile_id, param_source = resolve_param_profile_id(model, configured_provider)
    limits = _resolve_context_limits(llm_config, model)
    source = _combine_source(param_source, limits.source)
    return RuntimeModelProfile(
        model=model,
        provider=configured_provider,
        param_profile_id=profile_id,
        context_limits=limits,
        resolved_at=time.time(),
        source=source,
    )


def _combine_source(param_source: str, limits_source: str) -> str:
    if limits_source.startswith('config'):
        return limits_source
    return param_source


def _resolve_context_limits(
    llm_config: object | None,
    model: str,
) -> ModelContextLimits:
    configured_context = _positive_int(
        getattr(llm_config, 'context_window_tokens', None)
    )
    configured_output = _positive_int(getattr(llm_config, 'max_output_tokens', None))
    configured_input = _positive_int(getattr(llm_config, 'max_input_tokens', None))

    if configured_context is not None:
        usable = derive_usable_input_tokens(
            context_window_tokens=configured_context,
            max_output_tokens=configured_output,
            fallback_input_tokens=configured_input,
        )
        return ModelContextLimits(
            configured_context,
            configured_output,
            usable,
            'settings_override',
        )

    catalog = limits_from_catalog(model)
    if (
        catalog.context_window_tokens is not None
        or catalog.usable_input_tokens is not None
    ):
        max_output = configured_output or catalog.max_output_tokens
        usable = derive_usable_input_tokens(
            context_window_tokens=catalog.context_window_tokens,
            max_output_tokens=max_output,
            fallback_input_tokens=configured_input or catalog.usable_input_tokens,
        )
        return ModelContextLimits(
            catalog.context_window_tokens,
            max_output,
            usable,
            catalog.source,
        )

    if configured_input is not None:
        context = configured_input + (configured_output or 0)
        return ModelContextLimits(
            context,
            configured_output,
            configured_input,
            'settings_override',
        )

    entry = lookup(model)
    if entry is not None and entry.context_window_tokens:
        usable = derive_usable_input_tokens(
            context_window_tokens=entry.context_window_tokens,
            max_output_tokens=configured_output or entry.max_output_tokens,
        )
        return ModelContextLimits(
            entry.context_window_tokens,
            configured_output or entry.max_output_tokens,
            usable,
            'catalog',
        )

    usable = derive_usable_input_tokens(
        context_window_tokens=DEFAULT_UNKNOWN_CONTEXT_WINDOW_TOKENS,
        max_output_tokens=configured_output,
    )
    return ModelContextLimits(
        DEFAULT_UNKNOWN_CONTEXT_WINDOW_TOKENS,
        configured_output,
        usable,
        'provider_default',
    )


def attach_runtime_profile(llm_config: object, profile: RuntimeModelProfile) -> None:
    """Attach a pinned profile to a config object for context budgeting."""
    try:
        object.__setattr__(llm_config, _RUNTIME_PROFILE_KEY, profile)
    except Exception:
        setattr(llm_config, _RUNTIME_PROFILE_KEY, profile)


def get_attached_runtime_profile(
    llm_config: object | None,
) -> RuntimeModelProfile | None:
    if llm_config is None:
        return None
    profile = getattr(llm_config, _RUNTIME_PROFILE_KEY, None)
    return profile if isinstance(profile, RuntimeModelProfile) else None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
