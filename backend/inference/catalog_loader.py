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

from backend.core.constants import DEFAULT_LLM_TEMPERATURE

_CATALOG_PATH = Path(__file__).with_name('catalog.json')


@dataclass(frozen=True, slots=True)
class ModelEntry:
    """A single model's metadata from the catalog."""

    name: str
    provider: str
    provider_model_id: str | None = None
    aliases: tuple[str, ...] = ()
    context_window_tokens: int | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    input_price_per_m: float | None = None
    cached_input_price_per_m: float | None = None
    output_price_per_m: float | None = None
    long_context_threshold_tokens: int | None = None
    long_input_price_per_m: float | None = None
    long_cached_input_price_per_m: float | None = None
    long_output_price_per_m: float | None = None
    verified: bool = False
    featured: bool = False
    supports_function_calling: bool = False
    supports_parallel_tool_calls: bool = False
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
    use_max_completion_tokens: bool = (
        False  # Use max_completion_tokens instead of max_tokens
    )
    default_temperature: float | None = None  # Model-recommended temperature


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
                provider_model_id=info.get('provider_model_id'),
                aliases=tuple(info.get('aliases', ())),
                context_window_tokens=info.get('context_window_tokens'),
                max_input_tokens=info.get('max_input_tokens'),
                max_output_tokens=info.get('max_output_tokens'),
                input_price_per_m=info.get('input_price_per_m'),
                cached_input_price_per_m=info.get('cached_input_price_per_m'),
                output_price_per_m=info.get('output_price_per_m'),
                long_context_threshold_tokens=info.get(
                    'long_context_threshold_tokens'
                ),
                long_input_price_per_m=info.get('long_input_price_per_m'),
                long_cached_input_price_per_m=info.get(
                    'long_cached_input_price_per_m'
                ),
                long_output_price_per_m=info.get('long_output_price_per_m'),
                verified=info.get('verified', False),
                featured=info.get('featured', False),
                supports_function_calling=info.get('supports_function_calling', False),
                supports_parallel_tool_calls=info.get(
                    'supports_parallel_tool_calls', False
                ),
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
                default_temperature=info.get('default_temperature'),
            )
        )
    return tuple(entries)


@functools.lru_cache(maxsize=1)
def _name_index() -> dict[str, ModelEntry]:
    """Build a lookup dict: canonical name and all aliases → ModelEntry."""
    idx: dict[str, ModelEntry] = {}
    for entry in get_catalog():
        idx[entry.name] = entry
        idx[entry.name.lower()] = entry
        if entry.provider_model_id:
            idx[entry.provider_model_id] = entry
            idx[entry.provider_model_id.lower()] = entry
        for alias in entry.aliases:
            idx[alias] = entry
            idx[alias.lower()] = entry
    return idx


def runtime_model_id(entry: ModelEntry) -> str:
    """Return the exact model id that should be sent to the provider."""
    return entry.provider_model_id or entry.name


def _normalize_provider(provider: str | None) -> str | None:
    normalized = str(provider or '').strip().lower()
    return normalized or None


def _normalize_provider_model_key(provider: str, model: str | None) -> str:
    key = str(model or '').strip().lower()
    prefix = f'{provider.lower()}/'
    if key.startswith(prefix):
        key = key[len(prefix) :]
    return key


@functools.lru_cache(maxsize=1)
def _provider_exact_index() -> dict[tuple[str, str], ModelEntry]:
    idx: dict[tuple[str, str], ModelEntry] = {}
    for entry in get_catalog():
        provider = entry.provider.lower()
        for candidate in (entry.name, entry.provider_model_id):
            if candidate:
                idx[(provider, _normalize_provider_model_key(provider, candidate))] = (
                    entry
                )
    return idx


@functools.lru_cache(maxsize=1)
def _provider_alias_index() -> dict[tuple[str, str], ModelEntry]:
    idx = dict(_provider_exact_index())
    for entry in get_catalog():
        provider = entry.provider.lower()
        for alias in entry.aliases:
            idx[(provider, _normalize_provider_model_key(provider, alias))] = entry
    return idx


def lookup_provider_model(
    provider: str | None,
    model: str | None,
    *,
    allow_aliases: bool = False,
) -> ModelEntry | None:
    """Look up a catalog entry by an explicit provider/model pair.

    This is the deterministic path used by settings and provider-scoped UI.
    Aliases are disabled by default so selected provider/model ids cannot
    silently resolve to another provider's entry.
    """
    normalized_provider = _normalize_provider(provider)
    if normalized_provider is None:
        return None
    key = _normalize_provider_model_key(normalized_provider, model)
    if not key:
        return None
    index = _provider_alias_index() if allow_aliases else _provider_exact_index()
    return index.get((normalized_provider, key))


def lookup(model: str) -> ModelEntry | None:
    """Look up a model by name or alias.

    Provider-prefixed names resolve provider-scoped first. This avoids the old
    brittle behavior where ``xai/gpt-5`` could strip to ``gpt-5`` and match the
    OpenAI catalog entry.
    """
    idx = _name_index()
    key = model.strip()
    entry = idx.get(key) or idx.get(key.lower())
    if entry:
        return entry

    if '/' in key:
        provider, bare = key.split('/', 1)
        provider_match = lookup_provider_model(provider, bare, allow_aliases=True)
        if provider_match is not None:
            return provider_match
        catalog_providers = {entry.provider.lower() for entry in get_catalog()}
        if provider.strip().lower() in catalog_providers:
            return None

        # Legacy compatibility for non-catalog provider prefixes embedded in
        # aliases, e.g. moonshotai/kimi-k2.5.
        return idx.get(bare) or idx.get(bare.lower())
    return None


def _pricing_for_entry(
    entry: ModelEntry, *, prompt_tokens: int | None = None
) -> dict[str, float] | None:
    input_price = entry.input_price_per_m
    output_price = entry.output_price_per_m
    cached_input = entry.cached_input_price_per_m
    threshold = entry.long_context_threshold_tokens
    if (
        prompt_tokens is not None
        and threshold is not None
        and prompt_tokens > threshold
    ):
        input_price = entry.long_input_price_per_m or input_price
        output_price = entry.long_output_price_per_m or output_price
        cached_input = entry.long_cached_input_price_per_m or cached_input
    if input_price is None:
        return None
    return {
        'input': input_price,
        'output': output_price or 0.0,
        'cached_input': cached_input or input_price,
    }


def get_pricing(
    model: str, *, prompt_tokens: int | None = None
) -> dict[str, float] | None:
    """Get pricing for a model, with tier fallback.

    Returns ``{"input": <per_1M>, "output": <per_1M>}`` or ``None``.
    """
    entry = lookup(model)
    if entry:
        prices = _pricing_for_entry(entry, prompt_tokens=prompt_tokens)
        if prices is not None:
            return prices

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
        from backend.inference.context_limits import derive_usable_input_tokens

        usable_input = derive_usable_input_tokens(
            context_window_tokens=entry.context_window_tokens,
            max_output_tokens=entry.max_output_tokens,
            fallback_input_tokens=entry.max_input_tokens,
        )
        return usable_input, entry.max_output_tokens
    return None, None


def get_context_window_tokens(model: str) -> int | None:
    """Return total context-window tokens for *model* when known."""
    entry = lookup(model)
    if entry is None:
        return None
    if entry.context_window_tokens is not None:
        return entry.context_window_tokens
    if entry.max_input_tokens is not None and entry.max_output_tokens is not None:
        return entry.max_input_tokens + entry.max_output_tokens
    return None


def get_featured_models() -> list[str]:
    """Return ``provider/name`` strings for models marked ``featured = true``."""
    return [f'{e.provider}/{runtime_model_id(e)}' for e in get_catalog() if e.featured]


def get_models_for_provider(
    provider: str, *, featured_only: bool = True
) -> list[str]:
    """Return exact provider model ids for a provider."""
    normalized_provider = _normalize_provider(provider)
    if normalized_provider is None:
        return []
    return [
        runtime_model_id(entry)
        for entry in get_catalog()
        if entry.provider == normalized_provider
        and (entry.featured or not featured_only)
    ]


def get_model_options_by_provider(*, featured_only: bool = True) -> dict[str, list[str]]:
    """Return exact predefined model ids grouped by provider."""
    options: dict[str, list[str]] = {}
    for entry in get_catalog():
        if featured_only and not entry.featured:
            continue
        options.setdefault(entry.provider, []).append(runtime_model_id(entry))
    return options


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
        return entry.provider in [
            'openai',
            'cerebras',
            'deepseek',
            'groq',
            'lightning',
            'mistral',
            'nvidia',
            'opencode',
            'opencode-go',
            'openrouter',
            'xai',
        ]

    from backend.inference.provider_resolver import extract_provider_prefix

    provider = extract_provider_prefix(model)
    return provider in {
        'openai',
        'cerebras',
        'deepseek',
        'groq',
        'lightning',
        'mistral',
        'nvidia',
        'opencode',
        'opencode-go',
        'openrouter',
        'xai',
    }


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


def supports_function_calling(model: str) -> bool:
    """Return whether the model should receive native tool schemas.

    Models in the catalog use their catalog entry; uncataloged models
    with a recognised provider prefix default to ``True`` so that
    arbitrary provider/model combos (e.g. ``digitalocean/deepseek-v4-pro``)
    work without catalog changes.
    """
    entry = lookup(model)
    if entry is not None:
        return entry.supports_function_calling

    from backend.inference.provider_resolver import (
        KNOWN_PROVIDER_PREFIXES,
        extract_provider_prefix,
    )

    provider = extract_provider_prefix(model)
    if provider is None:
        return False
    return provider in KNOWN_PROVIDER_PREFIXES


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
            'context_window_tokens': entry.context_window_tokens,
            'max_input_tokens': get_token_limits(model)[0],
            'max_output_tokens': entry.max_output_tokens,
        }

    from backend.inference.provider_resolver import extract_provider_prefix

    provider = extract_provider_prefix(model)
    return {
        'provider': provider or 'unknown',
        'supports_function_calling': False,
        'supports_vision': False,
        'supports_prompt_cache': False,
        'context_window_tokens': None,
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


def _apply_catalog_token_and_penalty_strips(
    entry: ModelEntry, call_kwargs: dict
) -> None:
    if entry.strip_top_p:
        call_kwargs.pop('top_p', None)
    if entry.strip_temperature:
        call_kwargs.pop('temperature', None)
    if entry.strip_penalties:
        call_kwargs.pop('presence_penalty', None)
        call_kwargs.pop('frequency_penalty', None)
    if entry.use_max_completion_tokens and 'max_tokens' in call_kwargs:
        call_kwargs['max_completion_tokens'] = call_kwargs.pop('max_tokens')


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

    _apply_catalog_token_and_penalty_strips(entry, call_kwargs)

    # Apply model-recommended default temperature when user hasn't explicitly
    # overridden (i.e. it's still the global default).
    if (
        entry.default_temperature is not None
        and call_kwargs.get('temperature') == DEFAULT_LLM_TEMPERATURE
    ):
        call_kwargs['temperature'] = entry.default_temperature

    # Provider-side parallel tool_calls. Strictly capability-driven: only set
    # when the catalog entry advertises support. Provider sanitizers below
    # still strip it for providers whose SDK rejects the kwarg (e.g. Anthropic,
    # Google native), so this is safe to set unconditionally here.
    if entry.supports_parallel_tool_calls and 'parallel_tool_calls' not in call_kwargs:
        call_kwargs['parallel_tool_calls'] = True

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
