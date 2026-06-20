"""Prompt/context cache mode resolution (vendor-specific, not one boolean)."""

from __future__ import annotations

from backend.inference.catalog.catalog_loader import (
    ModelEntry,
    lookup,
    lookup_provider_model,
    runtime_model_id,
)

PROMPT_CACHE_NONE = 'none'
PROMPT_CACHE_IMPLICIT = 'implicit'
PROMPT_CACHE_EXPLICIT_HINTS = 'explicit_hints'
PROMPT_CACHE_EXPLICIT_RESOURCE = 'explicit_resource'

VALID_PROMPT_CACHE_MODES: frozenset[str] = frozenset(
    {
        PROMPT_CACHE_NONE,
        PROMPT_CACHE_IMPLICIT,
        PROMPT_CACHE_EXPLICIT_HINTS,
        PROMPT_CACHE_EXPLICIT_RESOURCE,
    }
)

_GATEWAY_PROVIDERS: frozenset[str] = frozenset(
    {'vercel', 'openrouter', 'digitalocean', 'lightning'}
)


def _resolve_cache_catalog_entry(
    model: str,
    *,
    provider: str | None = None,
) -> ModelEntry | None:
    """Resolve a catalog entry for prompt-cache eligibility checks."""
    m = (model or '').strip()
    if not m:
        return None
    entry = lookup(m)
    if entry is not None:
        return entry
    if not provider:
        return None
    normalized = provider.strip().lower()
    if not normalized:
        return None
    candidates = [m]
    if m.startswith(f'{normalized}/'):
        candidates.append(m[len(normalized) + 1 :])
    elif '/' in m:
        candidates.append(m.split('/')[-1])
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        entry = lookup_provider_model(normalized, key, allow_aliases=True)
        if entry is not None:
            return entry
    return None


def resolve_prompt_cache_mode_from_runtime(
    *,
    provider: str,
    name: str,
    runtime: dict,
    client: str | None,
) -> str:
    """Derive catalog ``prompt_cache_mode`` from runtime metadata and provider."""
    raw = runtime.get('prompt_cache_mode')
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in VALID_PROMPT_CACHE_MODES:
            return normalized

    provider_l = provider.strip().lower()
    client_l = str(client or runtime.get('client') or '').strip().lower()
    name_l = name.lower()
    cached_price = runtime.get('cached_input_price_per_m')
    has_cached_pricing = isinstance(cached_price, (int, float)) and cached_price > 0

    if provider_l == 'google' or client_l == 'google_native':
        return PROMPT_CACHE_EXPLICIT_RESOURCE

    if runtime.get('supports_prompt_cache') is True:
        return PROMPT_CACHE_EXPLICIT_HINTS

    if provider_l == 'anthropic' or client_l in {
        'anthropic_native',
        'anthropic_compatible',
    }:
        return PROMPT_CACHE_EXPLICIT_HINTS

    if name_l.startswith('anthropic/') or 'claude' in name_l:
        if provider_l in _GATEWAY_PROVIDERS or client_l == 'anthropic_compatible':
            return PROMPT_CACHE_EXPLICIT_HINTS

    if has_cached_pricing:
        return PROMPT_CACHE_IMPLICIT

    return PROMPT_CACHE_NONE


def prompt_cache_mode_for_model(
    model: str,
    *,
    provider: str | None = None,
) -> str:
    entry = _resolve_cache_catalog_entry(model, provider=provider)
    if entry is None:
        return PROMPT_CACHE_NONE
    return entry.prompt_cache_mode


def model_supports_any_prompt_cache(
    model: str,
    *,
    provider: str | None = None,
) -> bool:
    return prompt_cache_mode_for_model(model, provider=provider) != PROMPT_CACHE_NONE


def model_supports_prompt_cache_hints(
    model: str,
    *,
    provider: str | None = None,
) -> bool:
    """True when Grinta should attach Anthropic-style ``cache_control`` markers."""
    return (
        prompt_cache_mode_for_model(model, provider=provider)
        == PROMPT_CACHE_EXPLICIT_HINTS
    )


def model_supports_explicit_resource_cache(
    model: str,
    *,
    provider: str | None = None,
) -> bool:
    """True when Grinta should request Gemini ``cachedContents`` resources."""
    return (
        prompt_cache_mode_for_model(model, provider=provider)
        == PROMPT_CACHE_EXPLICIT_RESOURCE
    )


def model_uses_implicit_prompt_cache(
    model: str,
    *,
    provider: str | None = None,
) -> bool:
    """True for OpenAI/DeepSeek-style automatic prefix caching."""
    return (
        prompt_cache_mode_for_model(model, provider=provider) == PROMPT_CACHE_IMPLICIT
    )


def should_mark_messages_for_prompt_cache(
    model: str,
    *,
    provider: str | None = None,
) -> bool:
    """True when ``ContextMemoryManager`` should set ``cache_prompt`` on messages."""
    mode = prompt_cache_mode_for_model(model, provider=provider)
    return mode in {PROMPT_CACHE_EXPLICIT_HINTS, PROMPT_CACHE_EXPLICIT_RESOURCE}


def implicit_prompt_cache_key(entry: ModelEntry) -> str:
    """Stable routing key for OpenAI-style implicit prompt caching."""
    model_id = runtime_model_id(entry)
    return f'grinta:{entry.provider}:{model_id}'
