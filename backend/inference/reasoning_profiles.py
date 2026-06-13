"""Family-level reasoning effort profiles.

Resolution order (deterministic, highest priority first):

1. Catalog ``metadata.variants`` keys — per-model override with optional API payloads
2. Catalog ``metadata.reasoning_efforts`` — lightweight per-model tier list
3. Family profile from :data:`reasoning_profiles.json` (prefix inheritance)
4. Gateway vendor profile when the entry is a prefixed upstream id
5. Wire default from :data:`reasoning_profiles.json`
6. Conservative fallback ``('low', 'medium', 'high')``

Add a new model family once in ``reasoning_profiles.json``; individual catalog entries
only need overrides when a specific model diverges from its family.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any

from backend.inference.catalog_loader import ModelEntry

_PROFILES_PATH = Path(__file__).with_name('reasoning_profiles.json')

_GATEWAY_PROVIDERS: frozenset[str] = frozenset(
    {'openrouter', 'vercel', 'opencode', 'opencode-go'}
)

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


@functools.lru_cache(maxsize=1)
def _load_profile_data() -> dict[str, Any]:
    with _PROFILES_PATH.open(encoding='utf-8') as handle:
        return json.load(handle)


def _as_effort_tuple(raw: Any) -> tuple[str, ...] | None:
    if not isinstance(raw, list):
        return None
    efforts: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            efforts.append(item.strip().lower())
    return tuple(efforts) if efforts else None


def tier_order() -> tuple[str, ...]:
    order = _as_effort_tuple(_load_profile_data().get('tier_order'))
    return order or ('minimal', 'low', 'medium', 'high', 'xhigh', 'max')


def tier_aliases() -> dict[str, str]:
    raw = _load_profile_data().get('tier_aliases', {})
    if not isinstance(raw, dict):
        return {}
    return {
        str(key).strip().lower(): str(value).strip().lower()
        for key, value in raw.items()
        if str(key).strip() and str(value).strip()
    }


def wire_default_efforts(wire: str) -> tuple[str, ...]:
    wires = _load_profile_data().get('wires', {})
    if isinstance(wires, dict):
        efforts = _as_effort_tuple(wires.get(wire))
        if efforts is not None:
            return efforts
    return ('low', 'medium', 'high')


def family_profile_efforts(family: str) -> tuple[str, ...] | None:
    """Return efforts for *family*, walking prefix segments for inheritance."""
    families = _load_profile_data().get('families', {})
    if not isinstance(families, dict):
        return None
    normalized = family.strip().lower()
    if not normalized:
        return None
    parts = normalized.split('-')
    for end in range(len(parts), 0, -1):
        key = '-'.join(parts[:end])
        efforts = _as_effort_tuple(families.get(key))
        if efforts is not None:
            return efforts
    return None


def vendor_gateway_efforts(vendor: str) -> tuple[str, ...] | None:
    gateways = _load_profile_data().get('vendor_gateways', {})
    if not isinstance(gateways, dict):
        return None
    return _as_effort_tuple(gateways.get(vendor.strip().lower()))


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
    metadata = _metadata_dict(entry)
    variants = _variants(entry)
    if variants:
        return tuple(str(key).lower() for key in variants.keys())
    return _as_effort_tuple(metadata.get('reasoning_efforts'))


def resolve_allowed_efforts(
    entry: ModelEntry,
    *,
    wire: str,
    family: str,
) -> tuple[str, ...]:
    """Resolve executable reasoning tiers for *entry*."""
    catalog = _catalog_effort_override(entry)
    if catalog is not None:
        return catalog

    family_efforts = family_profile_efforts(family)
    if family_efforts is not None:
        return family_efforts

    if entry.provider in _GATEWAY_PROVIDERS:
        vendor, _logical = split_upstream_model_id(entry.name)
        if vendor is not None:
            vendor_efforts = vendor_gateway_efforts(vendor)
            if vendor_efforts is not None:
                return vendor_efforts

    return wire_default_efforts(wire)


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

    # Cross-family aliases only when the target tier exists in *allowed*.
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
