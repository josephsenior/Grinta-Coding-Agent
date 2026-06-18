"""Catalog-first model entry resolution for runtime capabilities."""

from __future__ import annotations

from backend.inference.catalog_loader import ModelEntry, lookup, lookup_provider_model
from backend.inference.registry import normalize_provider_name


def _conservative_unknown_entry(model: str, provider: str | None) -> ModelEntry:
    """Conservative defaults for manual/local model ids outside the catalog."""
    normalized = normalize_provider_name(provider) or 'unknown'
    bare = model.split('/')[-1] if '/' in model else model
    return ModelEntry(
        name=bare,
        provider=normalized,
        metadata={'source': 'conservative_unknown'},
        supports_function_calling=True,
        strip_reasoning_effort=True,
    )


def resolve_effective_model_entry(
    model: str,
    provider: str | None = None,
) -> tuple[ModelEntry | None, str, str]:
    """Return a catalog entry or conservative fallback for *model*."""
    normalized = normalize_provider_name(provider)
    entry: ModelEntry | None = None
    if normalized:
        bare = model.split('/')[-1] if model.startswith(f'{normalized}/') else model
        entry = lookup_provider_model(normalized, model, allow_aliases=True)
        if entry is None:
            entry = lookup_provider_model(normalized, bare, allow_aliases=True)
    if entry is None:
        entry = lookup(model)
    if entry is not None:
        return entry, entry.name, 'catalog'
    synthetic = _conservative_unknown_entry(model, normalized)
    return synthetic, 'conservative', 'conservative'


def resolve_model_entry_for_capabilities(
    model: str | None,
    provider: str | None = None,
    *,
    fallback: ModelEntry | None = None,
) -> ModelEntry | None:
    """Resolve a catalog entry for capability UI (reasoning, tools, etc.)."""
    if not model or model == '__custom__':
        return None

    scoped = lookup_provider_model(provider, model, allow_aliases=True)
    if scoped is None and fallback is not None and fallback.name == model:
        scoped = fallback

    if scoped is not None:
        return scoped

    entry, _, _ = resolve_effective_model_entry(model, provider)
    return entry


def synthetic_entry_from_profile(
    model: str,
    provider: str | None,
    *,
    profile_id: str | None = None,
) -> ModelEntry:
    """Build a conservative synthetic entry for uncataloged models."""
    _ = profile_id
    return _conservative_unknown_entry(model, provider)


def resolve_param_profile_id(model: str, provider: str | None) -> tuple[str, str]:
    """Return ``(profile_id, source)`` — catalog id or ``conservative``."""
    entry, profile_id, source = resolve_effective_model_entry(model, provider)
    if entry is None:
        return 'conservative', 'conservative'
    if source == 'catalog':
        return profile_id, source
    return 'conservative', source
