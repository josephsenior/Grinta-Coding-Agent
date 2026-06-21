"""Unified provider and model registry — single read API for inference metadata.

Consolidates provider URLs, prefixes, static catalog model listing, local probes,
and capability lookup. Prefer importing from this module for new code.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.core.logging.logger import app_logger as logger
from backend.inference.catalog.catalog_loader import (
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
    from backend.inference.capabilities.model_features import ModelFeatures
    from backend.inference.capabilities.provider_capabilities import (
        ProviderCapabilities,
    )

PROVIDER_DEFAULT_URLS: dict[str, str] = {
    'groq': 'https://api.groq.com/openai/v1',
    'xai': 'https://api.x.ai/v1',
    'deepseek': 'https://api.deepseek.com/v1',
    'moonshot': 'https://api.moonshot.ai/v1',
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
    'zai': 'https://api.z.ai/api/paas/v4',
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
        'moonshot',
        'nvidia',
        'ollama',
        'openai',
        'opencode',
        'opencode-go',
        'zai',
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
        'moonshot',
        'digitalocean',
        'deepinfra',
        'fireworks',
        'together',
        'perplexity',
        'opencode',
        'opencode-go',
        'zai',
    }
)


def get_provider_ids() -> list[str]:
    """Return configured hosted provider ids (from core provider config)."""
    from backend.core.providers.configurations import PROVIDER_CONFIGURATIONS

    return sorted(PROVIDER_CONFIGURATIONS.keys())


TIER_1_PROVIDERS: frozenset[str] = frozenset(
    {'anthropic', 'openai', 'google', 'groq', 'ollama'}
)

TIER_2_PROVIDERS: frozenset[str] = frozenset(
    {'openrouter', 'vercel', 'mistral', 'deepseek', 'moonshot', 'xai'}
)


def get_provider_tier(provider: str | None) -> int:
    normalized = normalize_provider_name(provider)
    if normalized in TIER_1_PROVIDERS or normalized in LOCAL_PROVIDERS:
        return 1
    if normalized in TIER_2_PROVIDERS:
        return 2
    return 3


def get_listable_providers() -> list[str]:
    """Providers shown in settings / onboarding pickers (all configured + local)."""
    hosted = get_provider_ids()
    extras = [
        provider for provider in sorted(LOCAL_PROVIDERS) if provider not in hosted
    ]
    return hosted + extras


def get_default_base_url(provider: str | None) -> str | None:
    normalized = normalize_provider_name(provider)
    if normalized is None:
        return None
    return PROVIDER_DEFAULT_URLS.get(normalized)


def get_provider_configuration(provider: str | None) -> dict[str, Any]:
    from backend.core.providers.configurations import (
        PROVIDER_CONFIGURATIONS,
        UNKNOWN_PROVIDER_CONFIG,
    )

    normalized = normalize_provider_name(provider)
    if normalized is None:
        return UNKNOWN_PROVIDER_CONFIG
    return PROVIDER_CONFIGURATIONS.get(normalized, UNKNOWN_PROVIDER_CONFIG)


def get_static_model_names(
    provider: str | None, *, featured_only: bool = False
) -> list[str]:
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
    include_local: bool = True,
) -> list[str]:
    """Return model ids for *provider* (catalog for hosted; live probe for local)."""
    normalized = normalize_provider_name(provider)
    if normalized is None:
        return []

    names: list[str] = []

    if include_local and normalized in LOCAL_PROVIDERS:
        names.extend(get_local_model_names(normalized))

    if normalized in LOCAL_PROVIDERS:
        if not names:
            names.extend(get_static_model_names(normalized, featured_only=True))
    else:
        names.extend(get_static_model_names(normalized, featured_only=False))

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
    from backend.inference.capabilities.param_profiles import (
        resolve_effective_model_entry,
    )
    from backend.inference.catalog.catalog_loader import lookup_provider_model

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


def _catalog_picker_entries(
    provider: str,
    catalog_entries: list[ModelEntry],
) -> list[ModelEntry]:
    """Build picker rows from static catalog entries."""
    from backend.inference.capabilities.param_profiles import (
        resolve_effective_model_entry,
    )

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
    provider: str | None = None,
    include_local: bool = True,
) -> dict[str, list[ModelEntry]]:
    """Build picker entries grouped by provider (catalog or local probe only)."""
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

        if normalized in LOCAL_PROVIDERS:
            if include_local:
                for model_id in get_local_model_names(normalized):
                    bare = model_id.split('/')[-1] if '/' in model_id else model_id
                    if bare in known_names or model_id in known_names:
                        continue
                    entries.append(
                        _picker_entry_for_model_id(
                            normalized,
                            model_id,
                            source='local',
                            display_name=model_id if model_id != bare else None,
                        )
                    )
                    known_names.add(bare)
                    if model_id != bare:
                        known_names.add(model_id)
            if not entries and catalog_entries:
                entries = _catalog_picker_entries(normalized, catalog_entries)
        elif catalog_entries:
            entries = _catalog_picker_entries(normalized, catalog_entries)

        _sort_picker_entries(entries)
        by_provider[normalized] = entries

    if provider is None:
        for prov in get_provider_ids():
            by_provider.setdefault(prov, [])
        for prov in LOCAL_PROVIDERS:
            by_provider.setdefault(prov, [])

    return dict(sorted(by_provider.items()))


def resolve_api_key_for_provider(config: Any, provider: str | None) -> str | None:
    """Best-effort API key for *provider* from config or environment."""
    normalized = normalize_provider_name(provider)
    if normalized is None:
        return None
    try:
        llm_cfg = config.get_llm_config()
        current_provider = normalize_provider_name(getattr(llm_cfg, 'provider', None))
        key = getattr(llm_cfg, 'api_key', None)
        if key is not None and (
            current_provider is None or current_provider == normalized
        ):
            raw = (
                key.get_secret_value() if hasattr(key, 'get_secret_value') else str(key)
            )
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
    from backend.inference.capabilities.model_features import get_features

    return get_features(model)


def get_provider_capability_profile(provider: str | None) -> ProviderCapabilities:
    """Per-provider behavioural flags (native tools, cache, replay, etc.)."""
    from backend.inference.capabilities.provider_capabilities import (
        get_provider_capabilities,
    )

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
    return labels.get(
        normalized, normalized.replace('_', ' ').replace('-', ' ').title()
    )


def empty_model_picker_hint(provider: str | None) -> str:
    label = provider_label(provider)
    if normalize_provider_name(provider) in LOCAL_PROVIDERS:
        return (
            f'No local models found for {label}. Start the server '
            f'(e.g. ollama serve) or enter a custom model id.'
        )
    return (
        f'No catalog models for {label}. Enter a model id manually or add a row to '
        f'the provider catalog.'
    )
