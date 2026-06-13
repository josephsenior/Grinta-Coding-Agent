"""Unified provider and model registry — single read API for inference metadata.

Consolidates provider URLs, prefixes, model listing (static + remote + local),
and capability lookup. Prefer importing from this module for new code.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from backend.core.logger import app_logger as logger
from backend.inference.catalog_loader import (
    ModelEntry,
    get_catalog,
    get_models_for_provider,
)


def normalize_provider_name(provider: str | None) -> str | None:
    """Normalize provider names for stable comparisons."""
    if provider is None:
        return None
    normalized = str(provider).strip().lower()
    if not normalized:
        return None
    return normalized

if TYPE_CHECKING:
    from backend.inference.model_features import ModelFeatures
    from backend.inference.provider_capabilities import ProviderCapabilities

PROVIDER_DEFAULT_URLS: dict[str, str] = {
    'groq': 'https://api.groq.com/openai/v1',
    'xai': 'https://api.x.ai/v1',
    'deepseek': 'https://api.deepseek.com/v1',
    'openrouter': 'https://openrouter.ai/api/v1',
    'vercel': 'https://ai-gateway.vercel.sh/v1',
    'nvidia': 'https://integrate.api.nvidia.com/v1',
    'lightning': 'https://lightning.ai/api/v1',
    'digitalocean': 'https://inference.do-ai.run/v1',
    'deepinfra': 'https://api.deepinfra.com/v1/openai',
    'fireworks': 'https://api.fireworks.ai/inference/v1',
    'together': 'https://api.together.xyz/v1',
    'perplexity': 'https://api.perplexity.ai',
    'cerebras': 'https://api.cerebras.ai/v1',
    'mistral': 'https://api.mistral.ai/v1',
    'opencode': 'https://opencode.ai/zen/v1',
    'opencode-go': 'https://opencode.ai/zen/go/v1',
}

KNOWN_PROVIDER_PREFIXES: frozenset[str] = frozenset(
    {
        'anthropic',
        'cerebras',
        'deepinfra',
        'deepseek',
        'digitalocean',
        'fireworks',
        'google',
        'groq',
        'lightning',
        'lm_studio',
        'mistral',
        'nvidia',
        'ollama',
        'openai',
        'opencode',
        'opencode-go',
        'openrouter',
        'perplexity',
        'replicate',
        'together',
        'vercel',
        'vllm',
        'xai',
    }
)

LOCAL_PROVIDERS: frozenset[str] = frozenset({'ollama', 'lm_studio', 'vllm'})

OPENAI_COMPATIBLE_REMOTE_PROVIDERS: frozenset[str] = frozenset(
    {
        'openai',
        'groq',
        'xai',
        'deepseek',
        'vercel',
        'openrouter',
        'nvidia',
        'lightning',
        'cerebras',
        'mistral',
        'digitalocean',
        'deepinfra',
        'fireworks',
        'together',
        'perplexity',
        'opencode',
        'opencode-go',
    }
)

DYNAMIC_LISTING_PROVIDERS: frozenset[str] = frozenset(
    {
        'openrouter',
        'vercel',
        'nvidia',
        'deepinfra',
        'fireworks',
        'together',
        'groq',
        'mistral',
        'cerebras',
    }
)

_REMOTE_MODEL_CACHE_TTL_SECONDS = 600.0
_remote_model_cache: dict[tuple[str, str, str], tuple[float, list[str]]] = {}


def get_provider_ids() -> list[str]:
    """Return configured hosted provider ids (from core provider config)."""
    from backend.core.providers import PROVIDER_CONFIGURATIONS

    return sorted(PROVIDER_CONFIGURATIONS.keys())


TIER_1_PROVIDERS: frozenset[str] = frozenset(
    {'anthropic', 'openai', 'google', 'groq', 'ollama'}
)

TIER_2_PROVIDERS: frozenset[str] = frozenset(
    {'openrouter', 'vercel', 'mistral', 'deepseek', 'xai'}
)


def get_provider_tier(provider: str | None) -> int:
    normalized = normalize_provider_name(provider)
    if normalized in TIER_1_PROVIDERS or normalized in LOCAL_PROVIDERS:
        return 1
    if normalized in TIER_2_PROVIDERS:
        return 2
    return 3


def get_listable_providers() -> list[str]:
    """Providers shown in settings / onboarding pickers (Tier 1 + Tier 2 + local)."""
    hosted = get_provider_ids()
    tier12 = [provider for provider in hosted if get_provider_tier(provider) <= 2]
    extras = [provider for provider in sorted(LOCAL_PROVIDERS) if provider not in tier12]
    return tier12 + extras


def get_default_base_url(provider: str | None) -> str | None:
    normalized = normalize_provider_name(provider)
    if normalized is None:
        return None
    return PROVIDER_DEFAULT_URLS.get(normalized)


def get_provider_configuration(provider: str | None) -> dict[str, Any]:
    from backend.core.providers import PROVIDER_CONFIGURATIONS, UNKNOWN_PROVIDER_CONFIG

    normalized = normalize_provider_name(provider)
    if normalized is None:
        return UNKNOWN_PROVIDER_CONFIG
    return PROVIDER_CONFIGURATIONS.get(normalized, UNKNOWN_PROVIDER_CONFIG)


def supports_remote_model_listing(provider: str | None) -> bool:
    """Return True when dynamic listing is available for *provider*."""
    normalized = normalize_provider_name(provider)
    if normalized is None:
        return False
    if normalized in LOCAL_PROVIDERS:
        return True
    return True


def fetch_remote_models(
    provider: str | None,
    api_key: str | None,
    *,
    base_url: str | None = None,
    use_cache: bool = True,
) -> list[str]:
    """Fetch model ids via the unified listing backend."""
    from backend.inference.model_list_backends import (
        list_models_for_provider,
        resolve_listing_base_url,
    )

    normalized = normalize_provider_name(provider)
    if normalized is None:
        return []

    key = (api_key or '').strip()
    if normalized not in LOCAL_PROVIDERS and not key:
        return []

    resolved_base = resolve_listing_base_url(normalized, base_url)
    cache_key = (normalized, resolved_base or '', key[:12])
    if use_cache and normalized not in LOCAL_PROVIDERS:
        cached = _remote_model_cache.get(cache_key)
        if cached is not None:
            expires_at, models = cached
            if time.monotonic() < expires_at:
                return list(models)

    models = list_models_for_provider(
        normalized,
        api_key=key or None,
        base_url=resolved_base,
    )
    if use_cache and normalized not in LOCAL_PROVIDERS:
        _remote_model_cache[cache_key] = (
            time.monotonic() + _REMOTE_MODEL_CACHE_TTL_SECONDS,
            list(models),
        )
    return models


def include_remote_listing_for_provider(
    provider: str | None, api_key: str | None
) -> bool:
    normalized = normalize_provider_name(provider)
    if normalized is None:
        return False
    if normalized in LOCAL_PROVIDERS:
        return True
    return bool((api_key or '').strip())


def get_static_model_names(provider: str | None, *, featured_only: bool = False) -> list[str]:
    normalized = normalize_provider_name(provider)
    if normalized is None:
        return []
    return get_models_for_provider(normalized, featured_only=featured_only)


def get_local_model_names(provider: str | None) -> list[str]:
    normalized = normalize_provider_name(provider)
    if normalized is None or normalized not in LOCAL_PROVIDERS:
        return []
    from backend.inference.provider_resolver import get_resolver

    return get_resolver().get_available_local_models(normalized)


def list_model_names(
    provider: str | None,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    include_remote: bool = True,
    include_local: bool = True,
) -> list[str]:
    """Merge dynamic and catalog model ids for *provider* (API-first when available)."""
    normalized = normalize_provider_name(provider)
    if normalized is None:
        return []

    names: list[str] = []

    if include_local and normalized in LOCAL_PROVIDERS:
        names.extend(get_local_model_names(normalized))

    if include_remote and include_remote_listing_for_provider(normalized, api_key):
        names.extend(fetch_remote_models(normalized, api_key, base_url=base_url))

    if not names:
        names.extend(get_static_model_names(normalized, featured_only=True))

    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def _synthetic_model_entry(
    provider: str,
    name: str,
    *,
    source: str,
    display_name: str | None = None,
) -> ModelEntry:
    label = display_name or name
    return ModelEntry(
        name=name,
        provider=provider,
        metadata={'display_name': label, 'source': source},
    )


def _picker_entry_for_model_id(
    provider: str,
    model_id: str,
    *,
    source: str,
    display_name: str | None = None,
) -> ModelEntry:
    """Build a picker row: catalog + param profile overlay when available."""
    from backend.inference.catalog_loader import lookup_provider_model
    from backend.inference.param_profiles import resolve_effective_model_entry

    bare = model_id.split('/')[-1] if '/' in model_id else model_id
    for candidate in (model_id, bare):
        scoped = lookup_provider_model(provider, candidate, allow_aliases=True)
        if scoped is not None:
            entry, _, _ = resolve_effective_model_entry(scoped.name, provider)
            if entry is not None:
                return entry

    entry, _, _ = resolve_effective_model_entry(bare, provider)
    if entry is not None:
        return entry

    label = display_name or bare
    return _synthetic_model_entry(
        provider,
        bare,
        source=source,
        display_name=label if label != bare else None,
    )


def _catalog_fallback_entries(
    provider: str,
    catalog_entries: list[ModelEntry],
) -> list[ModelEntry]:
    """Offline picker fallback when dynamic listing is unavailable."""
    from backend.inference.param_profiles import resolve_effective_model_entry

    enriched: list[ModelEntry] = []
    for scoped in catalog_entries:
        entry, _, _ = resolve_effective_model_entry(scoped.name, provider)
        enriched.append(entry if entry is not None else scoped)
    return enriched


def _sort_picker_entries(entries: list[ModelEntry]) -> None:
    entries.sort(
        key=lambda item: (
            not bool(getattr(item, 'featured', False)),
            not bool(getattr(item, 'verified', False)),
            str((item.metadata or {}).get('display_name') or item.name),
        )
    )


def build_model_entries_by_provider(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    provider: str | None = None,
    include_remote: bool = True,
    include_local: bool = True,
) -> dict[str, list[ModelEntry]]:
    """Build picker entries grouped by provider (API-first listing, catalog overlay)."""
    providers = [provider] if provider else get_listable_providers()
    by_provider: dict[str, list[ModelEntry]] = {}

    catalog_by_provider: dict[str, list[ModelEntry]] = {}
    for entry in get_catalog():
        catalog_by_provider.setdefault(entry.provider, []).append(entry)

    for prov in providers:
        normalized = normalize_provider_name(prov)
        if normalized is None:
            continue

        catalog_entries = catalog_by_provider.get(normalized, [])
        entries: list[ModelEntry] = []
        known_names: set[str] = set()

        dynamic_ids: list[str] = []
        if include_local and normalized in LOCAL_PROVIDERS:
            dynamic_ids.extend(get_local_model_names(normalized))
        elif include_remote and include_remote_listing_for_provider(normalized, api_key):
            dynamic_ids.extend(
                fetch_remote_models(normalized, api_key, base_url=base_url)
            )

        if dynamic_ids:
            for model_id in dynamic_ids:
                bare = model_id.split('/')[-1] if '/' in model_id else model_id
                if bare in known_names or model_id in known_names:
                    continue
                source = 'local' if normalized in LOCAL_PROVIDERS else 'remote'
                entries.append(
                    _picker_entry_for_model_id(
                        normalized,
                        model_id,
                        source=source,
                        display_name=model_id if model_id != bare else None,
                    )
                )
                known_names.add(bare)
                if model_id != bare:
                    known_names.add(model_id)
        elif catalog_entries:
            entries = _catalog_fallback_entries(normalized, catalog_entries)
            known_names = {entry.name for entry in entries}

        _sort_picker_entries(entries)
        by_provider[normalized] = entries

    if provider is None:
        for prov in get_provider_ids():
            by_provider.setdefault(prov, [])
        for prov in LOCAL_PROVIDERS:
            by_provider.setdefault(prov, [])

    return dict(sorted(by_provider.items()))


def resolve_api_key_for_provider(config: Any, provider: str | None) -> str | None:
    """Best-effort API key for *provider* from config (for remote model listing)."""
    normalized = normalize_provider_name(provider)
    if normalized is None:
        return None
    try:
        llm_cfg = config.get_llm_config()
        current_provider = normalize_provider_name(getattr(llm_cfg, 'provider', None))
        key = getattr(llm_cfg, 'api_key', None)
        if key is not None and (current_provider is None or current_provider == normalized):
            raw = key.get_secret_value() if hasattr(key, 'get_secret_value') else str(key)
            if raw.strip():
                return raw.strip()
    except Exception:
        logger.debug('Could not read LLM api_key from config', exc_info=True)

    cfg = get_provider_configuration(normalized)
    env_var = cfg.get('env_var')
    if env_var:
        import os

        env_key = (os.environ.get(env_var) or '').strip()
        if env_key:
            return env_key
    return None


def get_model_capabilities(model: str) -> ModelFeatures:
    """Per-model capabilities (catalog first, glob fallbacks)."""
    from backend.inference.model_features import get_features

    return get_features(model)


def get_provider_capability_profile(provider: str | None) -> ProviderCapabilities:
    """Per-provider behavioural flags (native tools, cache, replay, etc.)."""
    from backend.inference.provider_capabilities import get_provider_capabilities

    return get_provider_capabilities(provider)


def get_combined_capabilities(
    model: str, provider: str | None = None
) -> tuple[ModelFeatures, ProviderCapabilities]:
    """Return model-level and provider-level capability objects."""
    return get_model_capabilities(model), get_provider_capability_profile(provider)


def provider_label(provider: str | None) -> str:
    labels = {
        'anthropic': 'Anthropic',
        'cerebras': 'Cerebras',
        'deepinfra': 'DeepInfra',
        'deepseek': 'DeepSeek',
        'digitalocean': 'DigitalOcean',
        'fireworks': 'Fireworks',
        'google': 'Google Gemini',
        'groq': 'Groq',
        'lightning': 'Lightning AI',
        'lm_studio': 'LM Studio',
        'mistral': 'Mistral AI',
        'nvidia': 'NVIDIA',
        'ollama': 'Ollama',
        'openai': 'OpenAI',
        'opencode': 'OpenCode Zen',
        'opencode-go': 'OpenCode Go',
        'openrouter': 'OpenRouter',
        'vercel': 'Vercel AI Gateway',
        'perplexity': 'Perplexity',
        'together': 'Together AI',
        'vllm': 'vLLM',
        'xai': 'xAI',
    }
    if not provider:
        return 'selected provider'
    normalized = normalize_provider_name(provider) or provider
    return labels.get(normalized, normalized.replace('_', ' ').replace('-', ' ').title())


def empty_model_picker_hint(provider: str | None) -> str:
    label = provider_label(provider)
    if normalize_provider_name(provider) in LOCAL_PROVIDERS:
        return (
            f'No local models found for {label}. Start the server '
            f'(e.g. ollama serve) or enter a custom model id.'
        )
    return (
        f'No predefined models for {label}. Enter a model id or configure an API key '
        f'to refresh from the provider.'
    )
