"""Family-driven reasoning wire mapping for LLM call kwargs.

User config exposes a single ``reasoning_effort`` knob. Catalog ``metadata``
(``capabilities.reasoning``, ``family``, ``variants``) plus a small wire registry
select the provider-specific request fields automatically — no per-model Python.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.inference.catalog_loader import (
    TRANSPORT_CLIENT_OPENAI,
    ModelEntry,
    _transport_client_for_entry,
)

# Wire schema identifiers (family registry — not per-model).
WIRE_OPENAI_REASONING_EFFORT = 'openai_reasoning_effort'
WIRE_OPENAI_THINKING_AND_EFFORT = 'openai_thinking_and_effort'
WIRE_OPENAI_THINKING_ENABLED = 'openai_thinking_enabled'
WIRE_ANTHROPIC_ADAPTIVE = 'anthropic_adaptive'
WIRE_ANTHROPIC_EXTENDED = 'anthropic_extended'
WIRE_GEMINI_NATIVE = 'gemini_native'
WIRE_GEMINI_OPENAI_COMPAT = 'gemini_openai_compat'
WIRE_GLM_THINKING = 'glm_thinking'
WIRE_NONE = 'none'

_DEFAULT_EFFORTS_BY_WIRE: dict[str, tuple[str, ...]] = {
    WIRE_OPENAI_REASONING_EFFORT: (
        'none',
        'minimal',
        'low',
        'medium',
        'high',
        'xhigh',
    ),
    WIRE_OPENAI_THINKING_AND_EFFORT: ('low', 'medium', 'high', 'max'),
    WIRE_OPENAI_THINKING_ENABLED: ('low', 'medium', 'high', 'max'),
    WIRE_ANTHROPIC_ADAPTIVE: ('low', 'medium', 'high', 'xhigh', 'max'),
    WIRE_ANTHROPIC_EXTENDED: ('low', 'medium', 'high'),
    WIRE_GEMINI_NATIVE: ('low', 'medium', 'high'),
    WIRE_GEMINI_OPENAI_COMPAT: ('low', 'medium', 'high'),
    WIRE_GLM_THINKING: ('low', 'medium', 'high'),
}

_EFFORT_TO_GEMINI_LEVEL: dict[str, str] = {
    'low': 'low',
    'medium': 'medium',
    'high': 'high',
    'minimal': 'low',
    'max': 'high',
    'xhigh': 'high',
}

_HAIKU_BUDGET_BY_EFFORT: dict[str, int] = {
    'low': 1024,
    'medium': 4096,
    'high': 8192,
}


@dataclass(frozen=True, slots=True)
class ReasoningPlan:
    """Executable reasoning configuration for one LLM call."""

    enabled: bool
    wire: str
    resolved_effort: str | None = None
    allowed_efforts: tuple[str, ...] = ()
    kwargs_patch: dict[str, Any] = field(default_factory=dict)
    keys_to_strip: frozenset[str] = frozenset()


def _camel_to_snake(name: str) -> str:
    s1 = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


def _metadata_dict(entry: ModelEntry) -> dict[str, Any]:
    return entry.metadata if isinstance(entry.metadata, dict) else {}


def _capabilities(entry: ModelEntry) -> dict[str, Any]:
    caps = _metadata_dict(entry).get('capabilities')
    return caps if isinstance(caps, dict) else {}


def _variants(entry: ModelEntry) -> dict[str, Any]:
    variants = _metadata_dict(entry).get('variants')
    return variants if isinstance(variants, dict) else {}


def infer_family(entry: ModelEntry) -> str:
    """Return a normalized family id for wire selection."""
    family = _metadata_dict(entry).get('family')
    if isinstance(family, str) and family.strip():
        return family.strip().lower()

    name = entry.name.lower()
    if name.startswith('gpt-') or 'codex' in name:
        return 'gpt'
    if name.startswith('claude-'):
        if 'haiku' in name:
            return 'claude-haiku'
        if 'sonnet' in name:
            return 'claude-sonnet'
        if 'opus' in name:
            return 'claude-opus'
        return 'claude'
    if 'deepseek' in name:
        return 'deepseek-thinking' if any(
            token in name for token in ('pro', 'reasoner', 'r1')
        ) else 'deepseek-flash'
    if 'gemini' in name:
        return 'gemini-flash' if 'flash' in name else 'gemini-pro'
    if 'kimi' in name:
        return 'kimi'
    if 'qwen' in name:
        return 'qwen'
    if 'glm' in name:
        return 'glm'
    if 'minimax' in name:
        return 'minimax'
    if 'grok' in name:
        return 'grok'
    return entry.provider.lower()


def supports_reasoning(entry: ModelEntry) -> bool:
    """Return whether reasoning should be applied for this catalog entry."""
    caps = _capabilities(entry)
    if caps.get('reasoning') is True:
        return True
    if caps.get('reasoning') is False:
        return False
    if entry.supports_reasoning_effort:
        return True

    family = infer_family(entry)
    if family.startswith(
        (
            'gpt',
            'claude',
            'deepseek',
            'gemini',
            'kimi',
            'qwen',
            'glm',
            'minimax',
            'grok',
        )
    ):
        return True
    normalized = entry.name.lower()
    return normalized.startswith(('o1', 'o3', 'o4', 'gpt-'))


def _resolve_wire_schema(entry: ModelEntry, family: str) -> str:
    runtime_reasoning = _metadata_dict(entry).get('runtime_reasoning')
    if isinstance(runtime_reasoning, dict):
        wire = runtime_reasoning.get('wire')
        if isinstance(wire, str) and wire.strip():
            return wire.strip()

    transport = _transport_client_for_entry(entry)
    endpoint = entry.inference_endpoint or ''

    if transport == 'google_native':
        return WIRE_GEMINI_NATIVE
    if transport == 'anthropic_native' or endpoint == '/messages':
        if family.startswith('claude') and family == 'claude-haiku':
            return WIRE_ANTHROPIC_EXTENDED
        if family.startswith(('claude', 'minimax')):
            return WIRE_ANTHROPIC_ADAPTIVE
        return WIRE_ANTHROPIC_ADAPTIVE
    if family.startswith('gpt') or (
        entry.provider == 'openai' and entry.supports_reasoning_effort
    ):
        return WIRE_OPENAI_REASONING_EFFORT
    if family.startswith('deepseek') or 'deepseek' in entry.name.lower():
        # OpenAI SDK chat.completions rejects top-level ``thinking``; DeepSeek
        # gateways on /chat/completions may expose ``reasoning_effort``, but
        # only send it when the provider catalog explicitly advertises support.
        if transport == TRANSPORT_CLIENT_OPENAI and entry.supports_reasoning_effort:
            return WIRE_OPENAI_REASONING_EFFORT
        if entry.supports_reasoning_effort:
            return WIRE_OPENAI_THINKING_AND_EFFORT
        return WIRE_NONE
    if family.startswith('gemini'):
        return WIRE_GEMINI_OPENAI_COMPAT
    if family.startswith(('kimi', 'qwen')):
        return WIRE_OPENAI_THINKING_ENABLED
    if family == 'glm':
        return WIRE_GLM_THINKING
    if family == 'grok':
        return WIRE_OPENAI_REASONING_EFFORT
    if entry.supports_reasoning_effort:
        return WIRE_OPENAI_REASONING_EFFORT
    return WIRE_NONE


def _allowed_efforts(entry: ModelEntry, wire: str) -> tuple[str, ...]:
    variants = _variants(entry)
    if variants:
        return tuple(str(key).lower() for key in variants.keys())
    return _DEFAULT_EFFORTS_BY_WIRE.get(wire, ('low', 'medium', 'high'))


def _normalize_effort(
    reasoning_effort: str | None, allowed: tuple[str, ...]
) -> str | None:
    if reasoning_effort is None:
        return allowed[-1] if allowed else 'medium'
    effort = str(reasoning_effort).strip().lower()
    if effort in ('', 'none', 'off', 'disabled'):
        return None
    if effort in allowed:
        return effort
    # Prefer exact case-insensitive match already handled; map common aliases.
    aliases = {
        'minimal': 'low',
        'max': 'high',
        'xhigh': 'high',
    }
    mapped = aliases.get(effort, effort)
    if mapped in allowed:
        return mapped
    # Fall back to closest tier by position in default ordering.
    default_order = ('minimal', 'low', 'medium', 'high', 'xhigh', 'max')
    try:
        target_idx = default_order.index(effort)
    except ValueError:
        return allowed[len(allowed) // 2] if allowed else 'medium'
    best = allowed[0]
    best_dist = 10
    for candidate in allowed:
        try:
            dist = abs(default_order.index(candidate) - target_idx)
        except ValueError:
            continue
        if dist < best_dist:
            best = candidate
            best_dist = dist
    return best


def _variant_to_kwargs(variant: dict[str, Any]) -> dict[str, Any]:
    """Convert a catalog variant payload into request kwargs."""
    patch: dict[str, Any] = {}
    for key, value in variant.items():
        snake = _camel_to_snake(key)
        if snake == 'effort':
            patch['output_config'] = {'effort': value}
        elif snake == 'reasoning_effort':
            patch['reasoning_effort'] = value
        elif snake == 'thinking' and isinstance(value, dict):
            patch['thinking'] = value
        else:
            patch[snake] = value
    return patch


def _build_wire_kwargs(wire: str, effort: str, entry: ModelEntry) -> dict[str, Any]:
    family = infer_family(entry)
    if wire == WIRE_OPENAI_REASONING_EFFORT:
        patch: dict[str, Any] = {'reasoning_effort': effort}
        if effort == 'none':
            patch = {}
        return patch

    if wire == WIRE_OPENAI_THINKING_AND_EFFORT:
        return {
            'thinking': {'type': 'enabled'},
            'reasoning_effort': effort,
        }

    if wire == WIRE_OPENAI_THINKING_ENABLED:
        thinking: dict[str, Any] = {'type': 'enabled'}
        if family.startswith('kimi'):
            thinking['keep'] = None
        patch = {'thinking': thinking}
        if family.startswith('qwen'):
            patch['enable_thinking'] = True
        return patch

    if wire == WIRE_ANTHROPIC_ADAPTIVE:
        return {
            'thinking': {'type': 'adaptive'},
            'output_config': {'effort': effort},
        }

    if wire == WIRE_ANTHROPIC_EXTENDED:
        budget = _HAIKU_BUDGET_BY_EFFORT.get(effort, 4096)
        return {'thinking': {'type': 'enabled', 'budget_tokens': budget}}

    if wire == WIRE_GEMINI_NATIVE:
        level = _EFFORT_TO_GEMINI_LEVEL.get(effort, 'medium')
        return {'thinking_config': {'thinking_level': level}}

    if wire == WIRE_GEMINI_OPENAI_COMPAT:
        level = _EFFORT_TO_GEMINI_LEVEL.get(effort, 'medium')
        return {
            'reasoning_effort': effort,
            'extra_body': {
                'google': {'thinking_config': {'thinking_level': level}}
            },
        }

    if wire == WIRE_GLM_THINKING:
        return {'thinking': {'type': 'enabled'}, 'reasoning_effort': effort}

    return {}


def _sampling_strips(wire: str, entry: ModelEntry) -> frozenset[str]:
    strips: set[str] = set()
    if wire == WIRE_OPENAI_REASONING_EFFORT or entry.strip_temperature:
        strips.update({'temperature', 'top_p'})
    if wire in {
        WIRE_OPENAI_THINKING_AND_EFFORT,
        WIRE_ANTHROPIC_ADAPTIVE,
        WIRE_ANTHROPIC_EXTENDED,
    }:
        strips.update({'temperature', 'top_p'})
    if entry.strip_temperature:
        strips.add('temperature')
    if entry.strip_top_p:
        strips.add('top_p')
    return frozenset(strips)


def resolve_reasoning_plan(
    entry: ModelEntry,
    reasoning_effort: str | None,
) -> ReasoningPlan:
    """Build an executable reasoning plan for a catalog entry."""
    if not supports_reasoning(entry):
        return ReasoningPlan(enabled=False, wire=WIRE_NONE)

    wire = _resolve_wire_schema(entry, infer_family(entry))
    if wire == WIRE_NONE:
        return ReasoningPlan(enabled=False, wire=WIRE_NONE)

    allowed = _allowed_efforts(entry, wire)
    resolved = _normalize_effort(reasoning_effort, allowed)
    if resolved is None:
        return ReasoningPlan(
            enabled=False,
            wire=wire,
            allowed_efforts=allowed,
        )

    variants = _variants(entry)
    if resolved in variants and isinstance(variants[resolved], dict):
        kwargs_patch = _variant_to_kwargs(variants[resolved])
        for key, value in _build_wire_kwargs(wire, resolved, entry).items():
            kwargs_patch.setdefault(key, value)
    else:
        kwargs_patch = _build_wire_kwargs(wire, resolved, entry)

    return ReasoningPlan(
        enabled=True,
        wire=wire,
        resolved_effort=resolved,
        allowed_efforts=allowed,
        kwargs_patch=kwargs_patch,
        keys_to_strip=_sampling_strips(wire, entry),
    )


def apply_reasoning_plan(call_kwargs: dict[str, Any], plan: ReasoningPlan) -> None:
    """Merge *plan* into *call_kwargs* in place."""
    for key in ('reasoning_effort', 'thinking', 'output_config', 'enable_thinking'):
        call_kwargs.pop(key, None)

    if not plan.enabled:
        call_kwargs.pop('reasoning_effort', None)
        call_kwargs.pop('thinking', None)
        call_kwargs.pop('output_config', None)
        call_kwargs.pop('enable_thinking', None)
        call_kwargs.pop('thinking_config', None)
        return

    for key in plan.keys_to_strip:
        call_kwargs.pop(key, None)

    for key, value in plan.kwargs_patch.items():
        if key == 'extra_body' and isinstance(value, dict):
            existing = call_kwargs.get('extra_body')
            if isinstance(existing, dict):
                merged = dict(existing)
                google = merged.get('google', {})
                patch_google = value.get('google', {})
                if isinstance(google, dict) and isinstance(patch_google, dict):
                    merged['google'] = {**google, **patch_google}
                else:
                    merged.update(value)
                call_kwargs['extra_body'] = merged
            else:
                call_kwargs['extra_body'] = value
        else:
            call_kwargs[key] = value
