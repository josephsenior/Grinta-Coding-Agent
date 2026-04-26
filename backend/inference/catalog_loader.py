"""Unified model catalog loader.

Reads ``catalog.json`` once and exposes typed helpers consumed by
``cost_tracker``, ``model_features``, ``model_catalog``, and ``constants``.

Adding a new model requires editing **only** ``catalog.json`` — no Python
changes needed.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_CATALOG_PATH = Path(__file__).with_name('catalog.json')


@dataclass(frozen=True, slots=True)
class ModelEntry:
    """A single model's metadata from the catalog."""

    name: str
    provider: str
    aliases: tuple[str, ...] = ()
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    input_price_per_m: float | None = None
    output_price_per_m: float | None = None
    verified: bool = False
    featured: bool = False
    supports_function_calling: bool = False
    supports_reasoning_effort: bool = False
    supports_prompt_cache: bool = False
    supports_stop_words: bool = True
    supports_response_schema: bool = False
    supports_vision: bool = False
    # Model-specific parameter overrides for _get_call_kwargs().
    # These replace the brittle if-elif chain with data-driven config.
    strip_reasoning_effort: bool = False  # Remove reasoning_effort from kwargs
    thinking_mode: str | None = None  # "disabled", "budget:<N>", "enabled:<low>:<high>"
    strip_temperature: bool = False  # Remove temperature when thinking is active
    strip_top_p: bool = False  # Remove top_p from kwargs
    strip_penalties: bool = False  # Remove presence_penalty and frequency_penalty
    use_max_completion_tokens: bool = False  # Use max_completion_tokens instead of max_tokens


@functools.lru_cache(maxsize=1)
def _load_raw() -> dict:
    """Load and cache the raw catalog data."""
    with open(_CATALOG_PATH, encoding='utf-8') as f:
        return json.load(f)


@functools.lru_cache(maxsize=1)
def get_catalog() -> tuple[ModelEntry, ...]:
    """Return all model entries from ``catalog.json``."""
    data = _load_raw()
    entries: list[ModelEntry] = []
    for name, info in data.get('models', {}).items():
        entries.append(
            ModelEntry(
                name=name,
                provider=info['provider'],
                aliases=tuple(info.get('aliases', ())),
                max_input_tokens=info.get('max_input_tokens'),
                max_output_tokens=info.get('max_output_tokens'),
                input_price_per_m=info.get('input_price_per_m'),
                output_price_per_m=info.get('output_price_per_m'),
                verified=info.get('verified', False),
                featured=info.get('featured', False),
                supports_function_calling=info.get('supports_function_calling', False),
                supports_reasoning_effort=info.get('supports_reasoning_effort', False),
                supports_prompt_cache=info.get('supports_prompt_cache', False),
                supports_stop_words=info.get('supports_stop_words', True),
                supports_response_schema=info.get('supports_response_schema', False),
                supports_vision=info.get('supports_vision', False),
                strip_reasoning_effort=info.get('strip_reasoning_effort', False),
                thinking_mode=info.get('thinking_mode'),
                strip_temperature=info.get('strip_temperature', False),
                strip_top_p=info.get('strip_top_p', False),
                strip_penalties=info.get('strip_penalties', False),
                use_max_completion_tokens=info.get('use_max_completion_tokens', False),
            )
        )
    return tuple(entries)


@functools.lru_cache(maxsize=1)
def _name_index() -> dict[str, ModelEntry]:
    """Build a lookup dict: canonical name and all aliases → ModelEntry."""
    idx: dict[str, ModelEntry] = {}
    for entry in get_catalog():
        idx[entry.name] = entry
        for alias in entry.aliases:
            idx[alias] = entry
    return idx


def lookup(model: str) -> ModelEntry | None:
    """Look up a model by name or alias (case-insensitive, strips provider prefix)."""
    idx = _name_index()
    key = model.strip()
    # Try exact
    entry = idx.get(key) or idx.get(key.lower())
    if entry:
        return entry
    # Strip provider prefix (e.g. "openai/gpt-4o" → "gpt-4o")
    if '/' in key:
        bare = key.split('/')[-1]
        entry = idx.get(bare) or idx.get(bare.lower())
        if entry:
            return entry
    return None


def get_pricing(model: str) -> dict[str, float] | None:
    """Get pricing for a model, with tier fallback.

    Returns ``{"input": <per_1M>, "output": <per_1M>}`` or ``None``.
    """
    entry = lookup(model)
    if entry and entry.input_price_per_m is not None:
        return {
            'input': entry.input_price_per_m,
            'output': entry.output_price_per_m or 0.0,
        }

    # Tier fallback — substring matching
    data = _load_raw()
    tier = data.get('tier_pricing', {})
    bare = model.split('/')[-1].lower() if '/' in model else model.lower()
    for prefix, prices in tier.items():
        if prefix in bare:
            return {'input': prices['input'], 'output': prices['output']}
    return None


def get_token_limits(model: str) -> tuple[int | None, int | None]:
    """Return ``(max_input_tokens, max_output_tokens)`` for *model*."""
    entry = lookup(model)
    if entry:
        return entry.max_input_tokens, entry.max_output_tokens
    return None, None


def get_featured_models() -> list[str]:
    """Return ``provider/name`` strings for models marked ``featured = true``."""
    return [f'{e.provider}/{e.name}' for e in get_catalog() if e.featured]


def get_verified_models(provider: str | None = None) -> list[str]:
    """Return canonical names for models marked ``verified = true``.

    If *provider* is given, filter to that provider only.
    """
    return [
        e.name
        for e in get_catalog()
        if e.verified and (provider is None or e.provider == provider)
    ]


def get_all_model_names() -> Sequence[str]:
    """Return all known canonical model names."""
    return [e.name for e in get_catalog()]


def is_openai_compatible(model: str) -> bool:
    """Check if a model uses OpenAI-compatible API.

    Returns:
        True if model should use OpenAI client
    """
    entry = lookup(model)
    if entry:
        # These providers are OpenAI-compatible
        return entry.provider in ['openai', 'deepseek', 'mistral', 'xai']

    from backend.inference.provider_resolver import extract_provider_prefix

    provider = extract_provider_prefix(model)
    return provider in {'openai', 'deepseek', 'mistral', 'xai'}


def supports_tool_choice(model: str) -> bool:
    """Return whether model/provider supports explicit ``tool_choice`` parameter.

    ``tool_choice`` is safe for OpenAI-compatible providers and Anthropic,
    but not for native Google Gemini SDK calls.
    """
    entry = lookup(model)
    if entry is not None:
        if not entry.supports_function_calling:
            return False
        return entry.provider != 'google'

    from backend.inference.provider_resolver import extract_provider_prefix

    provider = extract_provider_prefix(model)
    if provider is None:
        return False
    return provider != 'google'


def prefers_short_tool_descriptions(model: str) -> bool:
    """Return whether planner should use compact tool descriptions for *model*."""
    entry = lookup(model)
    if entry is None:
        return False
    normalized = entry.name.lower()
    if entry.provider not in {'openai', 'deepseek', 'mistral', 'xai'}:
        return False
    if normalized in {'o1', 'o3', 'o4'}:
        return True
    return normalized.startswith(('gpt-', 'o1-', 'o3-', 'o4-', 'codex'))


def get_provider_info(model: str) -> dict[str, Any]:
    """Get provider information for a model.

    Returns:
        Dictionary with provider metadata
    """
    entry = lookup(model)
    if entry:
        return {
            'provider': entry.provider,
            'supports_function_calling': entry.supports_function_calling,
            'supports_vision': entry.supports_vision,
            'supports_prompt_cache': entry.supports_prompt_cache,
            'max_input_tokens': entry.max_input_tokens,
            'max_output_tokens': entry.max_output_tokens,
        }

    from backend.inference.provider_resolver import extract_provider_prefix

    provider = extract_provider_prefix(model)
    return {
        'provider': provider or 'unknown',
        'supports_function_calling': False,
        'supports_vision': False,
        'supports_prompt_cache': False,
        'max_input_tokens': None,
        'max_output_tokens': None,
    }


def _resolve_provider_for_sanitization(model: str) -> str:
    """Resolve provider name for parameter sanitization."""
    entry = lookup(model)
    if entry:
        return entry.provider

    from backend.inference.provider_resolver import extract_provider_prefix

    return extract_provider_prefix(model) or 'unknown'


def sanitize_call_kwargs_for_provider(model: str, call_kwargs: dict) -> dict:
    """Remove provider-incompatible kwargs from ``call_kwargs``.

    This function is the canonical sanitization layer used before SDK calls.
    It keeps planner/executor behavior stable while preventing provider-specific
    transport errors from unsupported OpenAI-style parameters.
    """
    sanitized = dict(call_kwargs)
    provider = _resolve_provider_for_sanitization(model)

    # Google Gemini native SDK accepts a narrower send_message() surface.
    if provider == 'google':
        for key in (
            'tool_choice',
            'extra_body',
            'extra_headers',
            'response_format',
            'frequency_penalty',
            'presence_penalty',
            'logit_bias',
            'seed',
            'user',
            'reasoning_effort',
            'reasoning',
            'parallel_tool_calls',
            'metadata',
        ):
            sanitized.pop(key, None)
        return sanitized

    # Anthropic SDK is not OpenAI-chat API compatible for several optional fields.
    if provider == 'anthropic':
        for key in (
            'tool_choice',
            'response_format',
            'frequency_penalty',
            'presence_penalty',
            'logit_bias',
            'parallel_tool_calls',
            'extra_body',
            'extra_headers',
        ):
            sanitized.pop(key, None)

    return sanitized


def apply_model_param_overrides(
    model: str,
    call_kwargs: dict,
    reasoning_effort: str | None = None,
    is_stream: bool = False,
) -> dict:
    """Apply data-driven model-specific parameter overrides from the catalog.

    This replaces hand-coded if-elif chains in ``_get_call_kwargs``.
    If the model is not in the catalog or has no overrides, the kwargs
    are returned unchanged.

    Args:
        model: Model name/alias.
        call_kwargs: The kwargs dict being built for the LLM call.
        reasoning_effort: The configured reasoning effort level.
        is_stream: Whether this is a streaming call.

    Returns:
        The (potentially modified) call_kwargs dict.
    """
    entry = lookup(model)
    if entry is None:
        # Unknown model - keep the call surface conservative.
        # Optional provider/model-specific knobs like reasoning_effort should
        # only be sent when the catalog explicitly says the target supports them.
        call_kwargs.pop('reasoning_effort', None)
        return call_kwargs

    # Strip reasoning_effort if the model doesn't support it natively
    if entry.strip_reasoning_effort:
        call_kwargs.pop('reasoning_effort', None)

    # Apply thinking mode configuration
    if entry.thinking_mode:
        _apply_thinking_mode(call_kwargs, entry, reasoning_effort, is_stream)
    elif reasoning_effort is not None and not entry.strip_reasoning_effort:
        call_kwargs['reasoning_effort'] = reasoning_effort

    # Conditional param stripping
    if entry.strip_top_p:
        call_kwargs.pop('top_p', None)
    if entry.strip_temperature:
        call_kwargs.pop('temperature', None)
    if entry.strip_penalties:
        call_kwargs.pop('presence_penalty', None)
        call_kwargs.pop('frequency_penalty', None)

    if entry.use_max_completion_tokens and 'max_tokens' in call_kwargs:
        call_kwargs['max_completion_tokens'] = call_kwargs.pop('max_tokens')

    return call_kwargs


def _apply_thinking_disabled(call_kwargs: dict) -> None:
    call_kwargs['thinking'] = {'type': 'disabled'}
    call_kwargs.pop('reasoning_effort', None)


def _apply_thinking_budget(
    call_kwargs: dict, mode: str, entry: ModelEntry, is_stream: bool
) -> None:
    tokens = int(mode.split(':')[1])
    if not is_stream:
        call_kwargs['thinking'] = {'budget_tokens': tokens}
        if entry.strip_temperature:
            call_kwargs.pop('temperature', None)
        if entry.strip_top_p:
            call_kwargs.pop('top_p', None)
    call_kwargs.pop('reasoning_effort', None)


def _apply_thinking_enabled(
    call_kwargs: dict, mode: str, reasoning_effort: str | None
) -> None:
    parts = mode.split(':')
    low = int(parts[1]) if len(parts) > 1 else 1024
    high = int(parts[2]) if len(parts) > 2 else 4096
    budget = low if reasoning_effort in ('low', None) else high
    call_kwargs['thinking'] = {'type': 'enabled', 'budget_tokens': budget}
    call_kwargs.pop('reasoning_effort', None)


def _apply_thinking_mode(
    call_kwargs: dict,
    entry: ModelEntry,
    reasoning_effort: str | None,
    is_stream: bool,
) -> None:
    """Parse ``thinking_mode`` from the catalog and set appropriate kwargs.

    Supported formats:
    - ``"disabled"`` → ``{"type": "disabled"}``
    - ``"budget:<N>"`` → ``{"budget_tokens": N}`` (skip in stream if needed)
    - ``"enabled:<low_budget>:<high_budget>"`` → maps reasoning_effort to budget
    """
    mode = entry.thinking_mode
    if mode == 'disabled':
        _apply_thinking_disabled(call_kwargs)
    elif mode and mode.startswith('budget:'):
        _apply_thinking_budget(call_kwargs, mode, entry, is_stream)
    elif mode and mode.startswith('enabled:'):
        _apply_thinking_enabled(call_kwargs, mode, reasoning_effort)
