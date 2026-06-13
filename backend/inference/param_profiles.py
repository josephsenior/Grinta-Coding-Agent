"""Family-level param profiles for models without full catalog runtime blocks."""

from __future__ import annotations

import functools
import json
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from backend.inference.catalog_loader import ModelEntry, lookup, lookup_provider_model
from backend.inference.registry import normalize_provider_name

_PROFILES_PATH = Path(__file__).with_name('param_profiles.json')


@functools.lru_cache(maxsize=1)
def _load_profile_data() -> dict[str, Any]:
    with _PROFILES_PATH.open(encoding='utf-8') as handle:
        return json.load(handle)


def _profiles() -> dict[str, dict[str, Any]]:
    data = _load_profile_data()
    raw = data.get('profiles', {})
    return raw if isinstance(raw, dict) else {}


def _provider_defaults() -> dict[str, str]:
    data = _load_profile_data()
    raw = data.get('provider_defaults', {})
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def infer_profile_family(model: str, provider: str | None) -> str | None:
    """Match model id to a param profile family via patterns."""
    from backend.inference.reasoning import infer_family

    entry = lookup(model)
    if entry is not None:
        family = infer_family(entry)
        mapped = _map_reasoning_family_to_profile(family, entry.provider)
        if mapped:
            return mapped

    bare = model.split('/')[-1] if '/' in model else model
    bare_lower = bare.lower()
    for item in _load_profile_data().get('family_patterns', []):
        if not isinstance(item, dict):
            continue
        family = item.get('family')
        patterns = item.get('patterns', [])
        if not isinstance(family, str) or not isinstance(patterns, list):
            continue
        for pattern in patterns:
            if isinstance(pattern, str) and fnmatch(bare_lower, pattern.lower()):
                return family
    return None


def _map_reasoning_family_to_profile(family: str, provider: str) -> str | None:
    if provider == 'openai':
        if family.startswith('gpt') and '5' in family:
            return 'openai_gpt5'
        if family in {'gpt'} or family.startswith('gpt'):
            normalized = family
            if '5' in normalized:
                return 'openai_gpt5'
        if family.startswith('o') or family in {'o1', 'o3', 'o4'}:
            return 'openai_o_series'
    if provider == 'anthropic' and family.startswith('claude'):
        return 'anthropic_claude4'
    if provider == 'google':
        if 'flash' in family:
            return 'gemini_flash'
        if family.startswith('gemini'):
            return 'gemini_pro'
    return None


def resolve_param_profile_id(model: str, provider: str | None) -> tuple[str, str]:
    """Return ``(profile_id, source)`` for *model*."""
    normalized_provider = normalize_provider_name(provider)
    entry = lookup(model)
    if entry is None and normalized_provider:
        bare = model.split('/')[-1] if model.startswith(f'{normalized_provider}/') else model
        entry = lookup_provider_model(normalized_provider, bare, allow_aliases=True)

    if entry is not None and _entry_has_runtime_overrides(entry):
        family = infer_profile_family(entry.name, entry.provider)
        if family:
            return family, 'catalog_family'
        default = _provider_defaults().get(entry.provider, 'provider_default')
        return default, 'catalog_provider'

    family = infer_profile_family(model, normalized_provider)
    if family and family in _profiles():
        return family, 'family'

    if normalized_provider:
        default = _provider_defaults().get(normalized_provider, 'provider_default')
        return default, 'provider_default'

    return 'conservative', 'conservative'


def _entry_has_runtime_overrides(entry: ModelEntry) -> bool:
    return any(
        (
            entry.strip_temperature,
            entry.strip_top_p,
            entry.strip_penalties,
            entry.use_max_completion_tokens,
            entry.thinking_mode,
            entry.supports_reasoning_effort,
            entry.default_temperature is not None,
        )
    )


def profile_fields(profile_id: str) -> dict[str, Any]:
    return dict(_profiles().get(profile_id, _profiles().get('conservative', {})))


def synthetic_entry_from_profile(
    model: str,
    provider: str | None,
    *,
    profile_id: str | None = None,
) -> ModelEntry:
    """Build a synthetic catalog entry from a param profile."""
    normalized = normalize_provider_name(provider) or 'unknown'
    bare = model.split('/')[-1] if '/' in model else model
    pid = profile_id or resolve_param_profile_id(model, normalized)[0]
    fields = profile_fields(pid)
    return ModelEntry(
        name=bare,
        provider=normalized,
        metadata={'family': pid, 'source': 'param_profile'},
        strip_temperature=bool(fields.get('strip_temperature', False)),
        strip_top_p=bool(fields.get('strip_top_p', False)),
        strip_penalties=bool(fields.get('strip_penalties', False)),
        strip_reasoning_effort=bool(fields.get('strip_reasoning_effort', False)),
        use_max_completion_tokens=bool(fields.get('use_max_completion_tokens', False)),
        supports_function_calling=bool(fields.get('supports_function_calling', True)),
        supports_parallel_tool_calls=bool(
            fields.get('supports_parallel_tool_calls', False)
        ),
        supports_reasoning_effort=bool(fields.get('supports_reasoning_effort', False))
        and not fields.get('strip_reasoning_effort', False),
        supports_prompt_cache=bool(fields.get('supports_prompt_cache', False)),
        default_temperature=fields.get('default_temperature'),
        thinking_mode=fields.get('thinking_mode'),
    )


def resolve_effective_model_entry(
    model: str,
    provider: str | None = None,
) -> tuple[ModelEntry | None, str, str]:
    """Return catalog entry or synthetic profile entry plus profile metadata."""
    entry = lookup(model)
    if entry is not None:
        profile_id, source = resolve_param_profile_id(model, provider or entry.provider)
        if not _entry_has_runtime_overrides(entry):
            synthetic = synthetic_entry_from_profile(
                model,
                provider or entry.provider,
                profile_id=profile_id,
            )
            merged = _merge_entry(entry, synthetic)
            return merged, profile_id, source
        return entry, profile_id, 'catalog'

    normalized = normalize_provider_name(provider)
    profile_id, source = resolve_param_profile_id(model, normalized)
    synthetic = synthetic_entry_from_profile(model, normalized, profile_id=profile_id)
    return synthetic, profile_id, source


def _merge_entry(catalog: ModelEntry, profile: ModelEntry) -> ModelEntry:
    """Catalog listing fields win; profile fills unset runtime flags."""
    return ModelEntry(
        name=catalog.name,
        provider=catalog.provider,
        client=catalog.client,
        catalog_file=catalog.catalog_file,
        metadata=catalog.metadata,
        inference_endpoint=catalog.inference_endpoint,
        provider_model_id=catalog.provider_model_id,
        aliases=catalog.aliases,
        context_window_tokens=catalog.context_window_tokens,
        max_input_tokens=catalog.max_input_tokens,
        max_output_tokens=catalog.max_output_tokens,
        input_price_per_m=catalog.input_price_per_m,
        cached_input_price_per_m=catalog.cached_input_price_per_m,
        cached_write_price_per_m=catalog.cached_write_price_per_m,
        output_price_per_m=catalog.output_price_per_m,
        long_context_threshold_tokens=catalog.long_context_threshold_tokens,
        long_input_price_per_m=catalog.long_input_price_per_m,
        long_cached_input_price_per_m=catalog.long_cached_input_price_per_m,
        long_cached_write_price_per_m=catalog.long_cached_write_price_per_m,
        long_output_price_per_m=catalog.long_output_price_per_m,
        verified=catalog.verified,
        featured=catalog.featured,
        supports_function_calling=catalog.supports_function_calling
        or profile.supports_function_calling,
        supports_parallel_tool_calls=catalog.supports_parallel_tool_calls
        or profile.supports_parallel_tool_calls,
        supports_reasoning_effort=catalog.supports_reasoning_effort
        or profile.supports_reasoning_effort,
        supports_prompt_cache=catalog.supports_prompt_cache
        or profile.supports_prompt_cache,
        supports_stop_words=catalog.supports_stop_words,
        supports_response_schema=catalog.supports_response_schema,
        supports_vision=catalog.supports_vision,
        strip_reasoning_effort=catalog.strip_reasoning_effort
        or profile.strip_reasoning_effort,
        thinking_mode=catalog.thinking_mode or profile.thinking_mode,
        strip_temperature=catalog.strip_temperature or profile.strip_temperature,
        strip_top_p=catalog.strip_top_p or profile.strip_top_p,
        strip_penalties=catalog.strip_penalties or profile.strip_penalties,
        use_max_completion_tokens=catalog.use_max_completion_tokens
        or profile.use_max_completion_tokens,
        default_temperature=catalog.default_temperature or profile.default_temperature,
    )
