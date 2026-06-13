"""Per-model reasoning effort resolution from catalog entries."""

from __future__ import annotations

from typing import Any

from backend.inference.catalog_loader import ModelEntry

TIER_ORDER: tuple[str, ...] = ('minimal', 'low', 'medium', 'high', 'xhigh', 'max')
TIER_ALIASES: dict[str, str] = {'off': 'none', 'disabled': 'none'}

_CONSERVATIVE_EFFORTS: tuple[str, ...] = ('low', 'medium', 'high')

_UPSTREAM_VENDOR_PREFIXES: frozenset[str] = frozenset(
    {
        'anthropic',
        'openai',
        'google',
        'xai',
        'deepseek',
        'meta-llama',
        'qwen',
        'mistral',
        'cohere',
        'moonshotai',
    }
)


def tier_order() -> tuple[str, ...]:
    return TIER_ORDER


def tier_aliases() -> dict[str, str]:
    return dict(TIER_ALIASES)


def split_upstream_model_id(model_id: str) -> tuple[str | None, str]:
    if '/' not in model_id:
        return None, model_id
    prefix, rest = model_id.split('/', 1)
    normalized = prefix.strip().lower()
    if normalized in _UPSTREAM_VENDOR_PREFIXES and rest.strip():
        return normalized, rest.strip()
    return None, model_id


def _metadata_dict(entry: ModelEntry) -> dict[str, Any]:
    return entry.metadata if isinstance(entry.metadata, dict) else {}


def _variants(entry: ModelEntry) -> dict[str, Any]:
    variants = _metadata_dict(entry).get('variants')
    return variants if isinstance(variants, dict) else {}


def _catalog_effort_override(entry: ModelEntry) -> tuple[str, ...] | None:
    variants = _variants(entry)
    if variants:
        return tuple(str(key).lower() for key in variants.keys())

    if entry.reasoning_efforts:
        return entry.reasoning_efforts

    metadata = _metadata_dict(entry)
    raw = metadata.get('reasoning_efforts')
    if isinstance(raw, list):
        efforts = tuple(
            str(item).strip().lower()
            for item in raw
            if isinstance(item, str) and str(item).strip()
        )
        if efforts:
            return efforts
    return None


def resolve_allowed_efforts(
    entry: ModelEntry,
    *,
    wire: str | None = None,
    family: str | None = None,
) -> tuple[str, ...]:
    """Resolve executable reasoning tiers for *entry* from catalog data."""
    _ = wire, family
    catalog = _catalog_effort_override(entry)
    if catalog is not None:
        return catalog
    return _CONSERVATIVE_EFFORTS


def normalize_effort_value(
    reasoning_effort: str | None,
    allowed: tuple[str, ...],
) -> str | None:
    """Map user/config effort to an executable allowed tier."""
    if not allowed:
        return 'medium'
    if reasoning_effort is None:
        return allowed[-1]

    effort = str(reasoning_effort).strip().lower()
    effort = tier_aliases().get(effort, effort)
    if effort in ('', 'none', 'off', 'disabled'):
        return None
    if effort in allowed:
        return effort

    cross_family = {'minimal': 'low'}
    mapped = cross_family.get(effort, effort)
    if mapped in allowed:
        return mapped

    order = tier_order()
    try:
        target_idx = order.index(effort)
    except ValueError:
        return allowed[len(allowed) // 2]

    best = allowed[0]
    best_dist = len(order) + 1
    for candidate in allowed:
        try:
            dist = abs(order.index(candidate) - target_idx)
        except ValueError:
            continue
        if dist < best_dist:
            best = candidate
            best_dist = dist
    return best
