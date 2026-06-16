"""Catalog-driven reasoning wire mapping for LLM call kwargs.

User config exposes a single ``reasoning_effort`` knob. Resolution is deterministic:

1. Catalog ``runtime.reasoning_efforts`` or ``metadata.variants`` (per-model tiers)
2. Catalog ``runtime.reasoning_wire`` selects the provider-specific request wire
3. Conservative fallback tiers when a model omits explicit efforts
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
from backend.inference.reasoning_profiles import (
    normalize_effort_value,
    resolve_allowed_efforts,
)
from backend.inference.reasoning_profiles import (
    split_upstream_model_id as _split_upstream_model_id,
)

# Wire schema identifiers (family registry — not per-model).
WIRE_OPENAI_REASONING_EFFORT = 'openai_reasoning_effort'
WIRE_VERCEL_GATEWAY_REASONING = 'vercel_gateway_reasoning'
WIRE_OPENAI_THINKING_AND_EFFORT = 'openai_thinking_and_effort'
WIRE_OPENAI_THINKING_ENABLED = 'openai_thinking_enabled'
WIRE_ANTHROPIC_ADAPTIVE = 'anthropic_adaptive'
WIRE_ANTHROPIC_EXTENDED = 'anthropic_extended'
WIRE_GEMINI_NATIVE = 'gemini_native'
WIRE_GEMINI_OPENAI_COMPAT = 'gemini_openai_compat'
WIRE_GLM_THINKING = 'glm_thinking'
WIRE_NONE = 'none'

# Vercel AI Gateway chat-completions ``reasoning.effort`` values (official docs).
VERCEL_GATEWAY_EFFORTS: frozenset[str] = frozenset(
    {'none', 'minimal', 'low', 'medium', 'high', 'xhigh'}
)

_EFFORT_TO_GEMINI_LEVEL: dict[str, str] = {
    'minimal': 'minimal',
    'low': 'low',
    'medium': 'medium',
    'high': 'high',
    'max': 'high',
    'xhigh': 'high',
}

_ANTHROPIC_BUDGET_BY_EFFORT: dict[str, int] = {
    'minimal': 1024,
    'low': 1024,
    'medium': 4096,
    'high': 8192,
    'xhigh': 16000,
    'max': 31999,
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


def _logical_model_name(entry: ModelEntry) -> str:
    """Bare model id used for family and capability heuristics."""
    _vendor, bare = _split_upstream_model_id(entry.name)
    return bare


def _metadata_dict(entry: ModelEntry) -> dict[str, Any]:
    return entry.metadata if isinstance(entry.metadata, dict) else {}


def _capabilities(entry: ModelEntry) -> dict[str, Any]:
    caps = _metadata_dict(entry).get('capabilities')
    return caps if isinstance(caps, dict) else {}


def _variants(entry: ModelEntry) -> dict[str, Any]:
    variants = _metadata_dict(entry).get('variants')
    return variants if isinstance(variants, dict) else {}


def _openai_logical_supports_reasoning(logical_lower: str) -> bool:
    """Return True when an OpenAI-family model id is a known reasoning model."""
    if logical_lower.startswith(('o1', 'o3', 'o4')):
        return True
    if 'codex' in logical_lower:
        return True
    if logical_lower.startswith('gpt-'):
        version = logical_lower[4:]
        return version.startswith('5') or version.startswith('5.')
    return False


def _model_name_supports_reasoning(entry: ModelEntry) -> bool:
    """Best-effort reasoning detection from bare/upstream model ids."""
    logical = _logical_model_name(entry).lower()
    if _openai_logical_supports_reasoning(logical):
        return True
    if logical.startswith(('o1', 'o3', 'o4')):
        return True
    if logical.startswith('claude-'):
        return True
    if logical.startswith('grok-4'):
        return True
    if 'gemini' in logical and any(
        token in logical for token in ('2.5', '2-', '3', '3.')
    ):
        return True
    if any(token in logical for token in ('reasoner', 'r1', 'thinking', 'qwq')):
        return True
    return False


def infer_family(entry: ModelEntry) -> str:
    """Return a normalized family id for wire selection."""
    family = _metadata_dict(entry).get('family')
    if isinstance(family, str) and family.strip():
        return family.strip().lower()

    name = _logical_model_name(entry).lower()
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
        return (
            'deepseek-thinking'
            if any(token in name for token in ('pro', 'reasoner', 'r1'))
            else 'deepseek-flash'
        )
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
    """Return whether Grinta can safely configure reasoning for this entry."""
    caps = _capabilities(entry)
    variants = _variants(entry)
    if caps.get('reasoning') is True:
        if variants or entry.provider in {'anthropic', 'google', 'openai', 'xai'}:
            return True
    if caps.get('reasoning') is False:
        return False
    if entry.thinking_mode:
        return True
    if entry.supports_reasoning_effort:
        return True

    if entry.provider == 'anthropic':
        return infer_family(entry).startswith('claude')
    if entry.provider == 'google':
        return infer_family(entry).startswith(
            'gemini'
        ) and _model_name_supports_reasoning(entry)
    if entry.provider == 'openai':
        return entry.supports_reasoning_effort or _model_name_supports_reasoning(entry)
    if entry.provider == 'xai' and _logical_model_name(entry).lower().startswith(
        'grok-4'
    ):
        return True

    vendor, logical = _split_upstream_model_id(entry.name)
    logical_lower = logical.lower()
    if vendor == 'anthropic' and logical_lower.startswith('claude'):
        return True
    if vendor == 'openai':
        return _openai_logical_supports_reasoning(logical_lower)
    if vendor == 'google' and 'gemini' in logical_lower:
        return any(token in logical_lower for token in ('2.5', '2-', '3', '3.'))
    if vendor == 'xai' and logical_lower.startswith('grok-4'):
        return True
    if vendor == 'deepseek' and any(
        token in logical_lower for token in ('reasoner', 'r1', 'thinking')
    ):
        return True

    return _model_name_supports_reasoning(entry)


def _resolve_wire_schema(entry: ModelEntry, family: str) -> str:
    if entry.reasoning_wire == WIRE_VERCEL_GATEWAY_REASONING:
        return WIRE_VERCEL_GATEWAY_REASONING
    if entry.provider == 'vercel' and entry.supports_reasoning_effort:
        if entry.reasoning_wire in {
            WIRE_OPENAI_REASONING_EFFORT,
            WIRE_GEMINI_OPENAI_COMPAT,
        }:
            return WIRE_VERCEL_GATEWAY_REASONING

    if entry.reasoning_wire:
        return entry.reasoning_wire

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
        if family.startswith(('claude', 'minimax', 'qwen')):
            return WIRE_ANTHROPIC_EXTENDED
        return WIRE_ANTHROPIC_EXTENDED
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
    if family.startswith('claude') and transport == TRANSPORT_CLIENT_OPENAI:
        return WIRE_OPENAI_REASONING_EFFORT
    if entry.supports_reasoning_effort:
        return WIRE_OPENAI_REASONING_EFFORT
    return WIRE_NONE


def _allowed_efforts(entry: ModelEntry, wire: str, family: str) -> tuple[str, ...]:
    return resolve_allowed_efforts(entry, wire=wire, family=family)


_EFFORT_DISPLAY_LABELS: dict[str, str] = {
    'none': 'Off (omit)',
    'minimal': 'Minimal',
    'low': 'Low',
    'medium': 'Medium',
    'high': 'High',
    'xhigh': 'Extra high',
    'max': 'Max',
}


def reasoning_effort_label(value: str, entry: ModelEntry) -> str:
    """Return a display label for one executable reasoning effort value."""
    variants = _variants(entry)
    variant = variants.get(value) if isinstance(variants, dict) else None
    if isinstance(variant, dict):
        effort = variant.get('effort') or variant.get('reasoningEffort')
        if isinstance(effort, str) and effort.strip():
            return effort.strip().replace('_', ' ').title()
    return _EFFORT_DISPLAY_LABELS.get(value, value.replace('_', ' ').title())


def reasoning_control_label(entry: ModelEntry | None) -> str:
    """Return the settings-field title for the reasoning selector."""
    if entry is None or not supports_reasoning(entry):
        return 'Reasoning effort'
    wire = _resolve_wire_schema(entry, infer_family(entry))
    if wire in {WIRE_GEMINI_NATIVE, WIRE_GEMINI_OPENAI_COMPAT}:
        return 'Thinking level'
    if wire in {WIRE_ANTHROPIC_ADAPTIVE, WIRE_ANTHROPIC_EXTENDED}:
        return 'Thinking effort'
    if wire in {
        WIRE_OPENAI_THINKING_AND_EFFORT,
        WIRE_OPENAI_THINKING_ENABLED,
        WIRE_GLM_THINKING,
    }:
        return 'Thinking mode'
    return 'Reasoning effort'


def reasoning_effort_display_options(
    entry: ModelEntry | None,
    *,
    include_disabled: bool = False,
) -> list[tuple[str, str]]:
    """Return ``(label, value)`` pairs for UI selectors."""
    values = reasoning_effort_options(entry, include_disabled=include_disabled)
    if not values or entry is None:
        return []
    options: list[tuple[str, str]] = [('Default', '')]
    options.extend((reasoning_effort_label(value, entry), value) for value in values)
    return options


def reasoning_effort_options(
    entry: ModelEntry | None,
    *,
    include_disabled: bool = False,
) -> tuple[str, ...]:
    """Return executable reasoning effort values for UI/config surfaces.

    The list is derived from the same wire plan used for real calls, so the TUI
    cannot show labels that the runtime would never be able to apply.
    """
    if entry is None or not supports_reasoning(entry):
        return ()
    family = infer_family(entry)
    wire = _resolve_wire_schema(entry, family)
    if wire == WIRE_NONE:
        return ()
    values = _allowed_efforts(entry, wire, family)
    if include_disabled:
        return ('none', *tuple(value for value in values if value != 'none'))
    return values


def _normalize_effort(
    reasoning_effort: str | None, allowed: tuple[str, ...]
) -> str | None:
    return normalize_effort_value(reasoning_effort, allowed)


def _variant_to_kwargs(variant: dict[str, Any]) -> dict[str, Any]:
    """Convert a catalog variant payload into request kwargs."""
    patch: dict[str, Any] = {}
    for key, value in variant.items():
        snake = _camel_to_snake(key)
        if snake == 'effort':
            # AI SDK metadata. The Python Anthropic SDK used by Grinta does
            # not accept a top-level output_config field, so effort labels are
            # mapped by _anthropic_thinking_for_effort() instead.
            continue
        elif snake == 'reasoning_effort':
            patch['reasoning_effort'] = value
        elif snake == 'thinking' and isinstance(value, dict):
            patch['thinking'] = _normalize_thinking_dict(value)
        elif snake == 'thinking_config' and isinstance(value, dict):
            patch['thinking_config'] = _normalize_thinking_config_dict(value)
        else:
            patch[snake] = value
    return patch


def _normalize_thinking_dict(value: dict[str, Any]) -> dict[str, Any]:
    thinking: dict[str, Any] = {}
    for key, raw in value.items():
        snake = _camel_to_snake(str(key))
        if snake == 'budget_tokens':
            thinking['budget_tokens'] = raw
        elif snake == 'type':
            thinking['type'] = raw
        elif snake == 'display':
            # AI SDK metadata, not accepted by the Anthropic Python SDK.
            continue
        else:
            thinking[snake] = raw
    return thinking


def _normalize_thinking_config_dict(value: dict[str, Any]) -> dict[str, Any]:
    config: dict[str, Any] = {}
    for key, raw in value.items():
        snake = _camel_to_snake(str(key))
        if snake == 'thinking_level' and isinstance(raw, str):
            config[snake] = raw.lower()
        else:
            config[snake] = raw
    return config


def _anthropic_thinking_for_effort(effort: str, entry: ModelEntry) -> dict[str, Any]:
    variants = _variants(entry)
    variant = variants.get(effort)
    if isinstance(variant, dict):
        thinking = variant.get('thinking')
        if isinstance(thinking, dict):
            normalized = _normalize_thinking_dict(thinking)
            budget = normalized.get('budget_tokens')
            if budget is not None:
                return {'type': 'enabled', 'budget_tokens': int(budget)}
    budget = _ANTHROPIC_BUDGET_BY_EFFORT.get(effort, 4096)
    return {'type': 'enabled', 'budget_tokens': budget}


def _map_vercel_gateway_effort(effort: str) -> str:
    """Map catalog/config tiers onto Vercel gateway ``reasoning.effort`` values."""
    normalized = str(effort or '').strip().lower()
    if normalized in ('', 'none'):
        return 'none'
    if normalized == 'max':
        return 'xhigh'
    if normalized in VERCEL_GATEWAY_EFFORTS:
        return normalized
    return 'high'


def _vercel_gateway_provider_passthrough(entry: ModelEntry) -> dict[str, Any]:
    """Provider-native knobs tunneled alongside Vercel ``reasoning`` (extra_body).

    Vercel gateway maps ``reasoning.effort`` for most vendors automatically
    (see Advanced Configuration).  MiniMax and Moonshot Kimi also accept
    OpenAI-compat ``thinking`` / ``reasoning_split`` per their official APIs.
    """
    family = infer_family(entry)
    name_lower = _logical_model_name(entry).lower()

    if family == 'minimax' or 'minimax' in name_lower:
        # platform.minimax.io/docs/api-reference/text-chat-openai
        passthrough: dict[str, Any] = {
            'thinking': {'type': 'adaptive'},
            'reasoning_split': True,
        }
        # M2.x cannot disable thinking; omit disabled when not M3.
        if 'minimax-m3' not in name_lower and 'm3' not in name_lower.split('/')[-1]:
            passthrough.pop('thinking', None)
        return passthrough

    if family.startswith('kimi') or 'kimi' in name_lower:
        thinking: dict[str, Any] = {'type': 'enabled'}
        thinking['keep'] = None
        return {'thinking': thinking}

    return {}


def _build_wire_kwargs(wire: str, effort: str, entry: ModelEntry) -> dict[str, Any]:
    family = infer_family(entry)
    if wire == WIRE_VERCEL_GATEWAY_REASONING:
        api_effort = _map_vercel_gateway_effort(effort)
        if api_effort == 'none':
            name_lower = _logical_model_name(entry).lower()
            if family == 'minimax' and (
                'minimax-m3' in name_lower or name_lower.endswith('/m3')
            ):
                return {'thinking': {'type': 'disabled'}}
            return {}
        # Vercel AI Gateway (OpenAI Chat Completions advanced):
        # https://vercel.com/docs/ai-gateway/sdks-and-apis/openai-chat-completions/advanced
        patch: dict[str, Any] = {
            'reasoning': {'effort': api_effort, 'enabled': True},
        }
        patch.update(_vercel_gateway_provider_passthrough(entry))
        return patch

    if wire == WIRE_OPENAI_REASONING_EFFORT:
        res_patch: dict[str, Any] = {'reasoning_effort': effort}
        if effort == 'none':
            res_patch = {}
        return res_patch

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
        return {'thinking': _anthropic_thinking_for_effort(effort, entry)}

    if wire == WIRE_ANTHROPIC_EXTENDED:
        return {'thinking': _anthropic_thinking_for_effort(effort, entry)}

    if wire == WIRE_GEMINI_NATIVE:
        level = _EFFORT_TO_GEMINI_LEVEL.get(effort, 'medium')
        return {'thinking_config': {'thinking_level': level}}

    if wire == WIRE_GEMINI_OPENAI_COMPAT:
        level = _EFFORT_TO_GEMINI_LEVEL.get(effort, 'medium')
        return {
            'reasoning_effort': effort,
            'extra_body': {'google': {'thinking_config': {'thinking_level': level}}},
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

    family = infer_family(entry)
    allowed = _allowed_efforts(entry, wire, family)
    resolved = _normalize_effort(reasoning_effort, allowed)
    if wire == WIRE_VERCEL_GATEWAY_REASONING and resolved == 'max':
        resolved = 'xhigh' if 'xhigh' in allowed else resolved
    if resolved is None:
        if wire == WIRE_OPENAI_THINKING_ENABLED and family.startswith('qwen'):
            return ReasoningPlan(
                enabled=True,
                wire=wire,
                resolved_effort='none',
                allowed_efforts=allowed,
                kwargs_patch={'enable_thinking': False},
            )
        return ReasoningPlan(
            enabled=False,
            wire=wire,
            allowed_efforts=allowed,
        )

    variants = _variants(entry)
    if resolved in variants and isinstance(variants[resolved], dict):
        kwargs_patch = _variant_to_kwargs(variants[resolved])
        wire_patch = _build_wire_kwargs(wire, resolved, entry)
        if wire in {WIRE_ANTHROPIC_ADAPTIVE, WIRE_ANTHROPIC_EXTENDED}:
            kwargs_patch = {**kwargs_patch, **wire_patch}
            kwargs_patch.pop('output_config', None)
            kwargs_patch.pop('effort', None)
        else:
            for key, value in wire_patch.items():
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
    for key in (
        'reasoning_effort',
        'reasoning',
        'thinking',
        'output_config',
        'enable_thinking',
        'thinking_config',
        'reasoning_split',
    ):
        call_kwargs.pop(key, None)

    if not plan.enabled:
        call_kwargs.pop('reasoning_effort', None)
        call_kwargs.pop('reasoning', None)
        call_kwargs.pop('thinking', None)
        call_kwargs.pop('output_config', None)
        call_kwargs.pop('enable_thinking', None)
        call_kwargs.pop('thinking_config', None)
        call_kwargs.pop('reasoning_split', None)
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
