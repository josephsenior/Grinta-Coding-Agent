"""Provider-scoped model catalog loader.

Reads ``catalogs/*.json`` once and exposes typed helpers consumed by
``cost_tracker``, ``model_features``, ``model_catalog``, and ``constants``.

Each catalog file belongs to one provider/client route.  This keeps resolution
deterministic: provider/model pairs resolve only inside that provider's file.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.core.constants import DEFAULT_LLM_TEMPERATURE

_CATALOG_DIR = Path(__file__).with_name('catalogs')


@dataclass(frozen=True, slots=True)
class ModelEntry:
    """A single model entry from the provider catalog."""

    name: str
    provider: str
    client: str | None = None
    catalog_file: str | None = None
    metadata: dict[str, Any] | None = None
    inference_endpoint: str | None = None
    provider_model_id: str | None = None
    aliases: tuple[str, ...] = ()
    context_window_tokens: int | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    input_price_per_m: float | None = None
    cached_input_price_per_m: float | None = None
    cached_write_price_per_m: float | None = None
    output_price_per_m: float | None = None
    long_context_threshold_tokens: int | None = None
    long_input_price_per_m: float | None = None
    long_cached_input_price_per_m: float | None = None
    long_cached_write_price_per_m: float | None = None
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


TRANSPORT_CLIENT_GOOGLE = 'google_native'
TRANSPORT_CLIENT_ANTHROPIC = 'anthropic_native'
TRANSPORT_CLIENT_OPENAI = 'openai_compatible'
TRANSPORT_CLIENT_UNSUPPORTED = 'unsupported'

_GOOGLE_INCOMPATIBLE_KWARGS: frozenset[str] = frozenset(
    {
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
    }
)

_ANTHROPIC_INCOMPATIBLE_KWARGS: frozenset[str] = frozenset(
    {
        'tool_choice',
        'response_format',
        'frequency_penalty',
        'presence_penalty',
        'logit_bias',
        'parallel_tool_calls',
        'extra_body',
        'extra_headers',
        'stream',
        'stream_options',
        'reasoning_effort',
    }
)

GEMINI_SDK_EXTRA_INCOMPATIBLE_KWARGS: frozenset[str] = frozenset(
    {
        'stream',
        'stream_options',
        'logprobs',
        'top_logprobs',
        'n',
        'timeout',
    }
)

# Vendor extensions accepted by OpenAI-compatible HTTP APIs but not as direct
# kwargs on ``chat.completions.create`` — tunneled via ``extra_body``.
_OPENAI_PASSTHROUGH_KWARGS: frozenset[str] = frozenset(
    {
        'thinking',
        'enable_thinking',
        'output_config',
    }
)

_INCOMPATIBLE_KWARGS_BY_TRANSPORT: dict[str, frozenset[str]] = {
    TRANSPORT_CLIENT_GOOGLE: _GOOGLE_INCOMPATIBLE_KWARGS,
    TRANSPORT_CLIENT_ANTHROPIC: _ANTHROPIC_INCOMPATIBLE_KWARGS,
    TRANSPORT_CLIENT_OPENAI: frozenset(),
}

_SUPPORTED_INFERENCE_ENDPOINTS: frozenset[str] = frozenset(
    {'/chat/completions', '/messages'}
)


def _parse_model_catalog_info(
    info: dict[str, Any],
    *,
    source_file: str,
    model_name: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(runtime, metadata)`` from a catalog model record."""
    runtime = info.get('runtime')
    if not isinstance(runtime, dict):
        raise ValueError(
            f"Model {model_name!r} in {source_file} must define a 'runtime' object"
        )
    metadata = info.get('metadata')
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError(
            f"Model {model_name!r} in {source_file} must define 'metadata' as an object"
        )
    return runtime, metadata


def _strip_transport_prefix(model: str, provider: str) -> str:
    if not provider or '/' not in model:
        return model
    prefix, stripped = model.split('/', 1)
    if prefix.strip().lower() == provider.strip().lower():
        return stripped
    return model


def _transport_client_for_entry(entry: ModelEntry) -> str:
    if entry.provider == 'google':
        return TRANSPORT_CLIENT_GOOGLE
    if entry.provider == 'anthropic':
        return TRANSPORT_CLIENT_ANTHROPIC
    if entry.provider in {'opencode', 'opencode-go'}:
        endpoint = entry.inference_endpoint
        if endpoint == '/messages':
            return TRANSPORT_CLIENT_ANTHROPIC
        if endpoint in _SUPPORTED_INFERENCE_ENDPOINTS:
            return TRANSPORT_CLIENT_OPENAI
        return TRANSPORT_CLIENT_UNSUPPORTED
    return TRANSPORT_CLIENT_OPENAI


def _transport_client_for_provider_prefix(
    provider: str,
    model: str,
    *,
    config_provider: str | None = None,
) -> str:
    from backend.inference.provider_resolver import (
        opencode_go_required_endpoint,
        opencode_required_endpoint,
    )

    stripped = _strip_transport_prefix(model, provider)
    if provider == 'google':
        return TRANSPORT_CLIENT_GOOGLE
    if provider == 'anthropic':
        return TRANSPORT_CLIENT_ANTHROPIC
    if provider == 'opencode':
        endpoint = opencode_required_endpoint(stripped)
        if endpoint == '/messages':
            return TRANSPORT_CLIENT_ANTHROPIC
        if endpoint in _SUPPORTED_INFERENCE_ENDPOINTS:
            return TRANSPORT_CLIENT_OPENAI
        return TRANSPORT_CLIENT_UNSUPPORTED
    if provider == 'opencode-go':
        endpoint = opencode_go_required_endpoint(stripped)
        if endpoint == '/messages':
            return TRANSPORT_CLIENT_ANTHROPIC
        if endpoint in _SUPPORTED_INFERENCE_ENDPOINTS:
            return TRANSPORT_CLIENT_OPENAI
        return TRANSPORT_CLIENT_UNSUPPORTED
    return TRANSPORT_CLIENT_OPENAI


def resolve_transport_client(
    model: str,
    *,
    config_provider: str | None = None,
) -> str:
    """Resolve the executable transport client for *model*."""
    entry = lookup(model)
    if entry is not None:
        return _transport_client_for_entry(entry)

    if config_provider:
        bare = model.split('/', 1)[-1] if '/' in model else model
        entry = lookup_provider_model(config_provider, bare, allow_aliases=True)
        if entry is not None:
            return _transport_client_for_entry(entry)

    if '/' not in model.strip():
        return TRANSPORT_CLIENT_OPENAI

    from backend.inference.provider_resolver import get_resolver

    try:
        provider = get_resolver().resolve_provider(
            model, config_provider=config_provider
        )
    except ValueError:
        return TRANSPORT_CLIENT_OPENAI
    return _transport_client_for_provider_prefix(
        provider, model, config_provider=config_provider
    )


def incompatible_kwargs_for_transport(transport_client: str) -> frozenset[str]:
    return _INCOMPATIBLE_KWARGS_BY_TRANSPORT.get(transport_client, frozenset())


def pop_incompatible_kwargs(
    kwargs: dict[str, Any],
    transport_client: str,
    *,
    extra: frozenset[str] | None = None,
) -> None:
    """Remove transport-incompatible keys from *kwargs* in place."""
    keys = incompatible_kwargs_for_transport(transport_client)
    if extra:
        keys = keys | extra
    for key in keys:
        kwargs.pop(key, None)


def _tunnel_openai_passthrough_kwargs(sanitized: dict[str, Any]) -> None:
    """Move vendor extension fields into ``extra_body`` for OpenAI SDK passthrough."""
    passthrough: dict[str, Any] = {}
    for key in _OPENAI_PASSTHROUGH_KWARGS:
        if key in sanitized:
            passthrough[key] = sanitized.pop(key)
    if not passthrough:
        return
    existing = sanitized.get('extra_body')
    if isinstance(existing, dict):
        sanitized['extra_body'] = {**existing, **passthrough}
    else:
        sanitized['extra_body'] = passthrough


def sanitize_call_kwargs_for_provider(model: str, call_kwargs: dict) -> dict:
    """Remove transport-incompatible kwargs before SDK calls."""
    transport = resolve_transport_client(model)
    sanitized = dict(call_kwargs)
    entry = lookup(model)
    if entry is not None and (
        not entry.supports_reasoning_effort or entry.strip_reasoning_effort
    ):
        sanitized.pop('reasoning_effort', None)
    for key in incompatible_kwargs_for_transport(transport):
        sanitized.pop(key, None)
    if transport == TRANSPORT_CLIENT_OPENAI:
        _tunnel_openai_passthrough_kwargs(sanitized)
    return sanitized


def validate_model_transport(
    model: str,
    *,
    config_provider: str | None = None,
) -> None:
    """Fail fast when a catalog model uses an unsupported transport surface."""
    from backend.inference.exceptions import BadRequestError

    entry = lookup(model)
    if entry is None and config_provider:
        bare = model.split('/', 1)[-1] if '/' in model else model
        entry = lookup_provider_model(config_provider, bare, allow_aliases=True)
    if entry is None:
        return

    transport = _transport_client_for_entry(entry)
    if transport != TRANSPORT_CLIENT_UNSUPPORTED:
        return

    endpoint = entry.inference_endpoint
    provider = entry.provider
    if endpoint == '/responses':
        raise BadRequestError(
            (
                f"Model {model!r} is served via OpenCode '/responses', which Grinta "
                'does not implement yet. Select a model on '
                "'/chat/completions' or '/messages'."
            ),
            llm_provider=provider,
            model=model,
        )
    if endpoint and endpoint.startswith('/models/'):
        raise BadRequestError(
            (
                f"Model {model!r} is served via OpenCode native Gemini endpoint "
                f"{endpoint!r}, which Grinta does not implement yet. Select a "
                "model on '/chat/completions' or use provider 'google/'."
            ),
            llm_provider=provider,
            model=model,
        )
    raise BadRequestError(
        (
            f'Model {model!r} requires unsupported transport endpoint '
            f'{endpoint!r}.'
        ),
        llm_provider=provider,
        model=model,
    )


@functools.lru_cache(maxsize=1)
def _load_raw() -> dict:
    """Load and cache provider catalog files."""
    if not _CATALOG_DIR.exists():
        return {'providers': {}}

    providers: dict[str, dict[str, Any]] = {}
    for path in sorted(_CATALOG_DIR.glob('*.json')):
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)

        provider = str(raw.get('provider') or path.stem).strip().lower()
        if not provider:
            continue
        if provider in providers:
            raise ValueError(f'Duplicate catalog for provider {provider!r}')

        catalog = dict(raw)
        catalog['provider'] = provider
        catalog['source_file'] = path.name
        providers[provider] = catalog

    return {'providers': providers}


def _entry_from_catalog(
    *,
    provider: str,
    provider_client: str | None,
    source_file: str | None,
    name: str,
    runtime: dict[str, Any],
    metadata: dict[str, Any],
) -> ModelEntry:
    endpoint = runtime.get('inference_endpoint')
    if isinstance(endpoint, str) and endpoint.startswith('/'):
        inference_endpoint = endpoint
    else:
        inference_endpoint = None
    return ModelEntry(
        name=name,
        provider=provider,
        client=runtime.get('client', provider_client),
        catalog_file=source_file,
        metadata=metadata or None,
        inference_endpoint=inference_endpoint,
        provider_model_id=runtime.get('provider_model_id'),
        aliases=tuple(runtime.get('aliases', ())),
        context_window_tokens=runtime.get('context_window_tokens'),
        max_input_tokens=runtime.get('max_input_tokens'),
        max_output_tokens=runtime.get('max_output_tokens'),
        input_price_per_m=runtime.get('input_price_per_m'),
        cached_input_price_per_m=runtime.get('cached_input_price_per_m'),
        cached_write_price_per_m=runtime.get('cached_write_price_per_m'),
        output_price_per_m=runtime.get('output_price_per_m'),
        long_context_threshold_tokens=runtime.get('long_context_threshold_tokens'),
        long_input_price_per_m=runtime.get('long_input_price_per_m'),
        long_cached_input_price_per_m=runtime.get('long_cached_input_price_per_m'),
        long_cached_write_price_per_m=runtime.get('long_cached_write_price_per_m'),
        long_output_price_per_m=runtime.get('long_output_price_per_m'),
        verified=runtime.get('verified', False),
        featured=runtime.get('featured', False),
        supports_function_calling=runtime.get('supports_function_calling', False),
        supports_parallel_tool_calls=runtime.get('supports_parallel_tool_calls', False),
        supports_reasoning_effort=runtime.get('supports_reasoning_effort', False),
        supports_prompt_cache=runtime.get('supports_prompt_cache', False),
        supports_stop_words=runtime.get('supports_stop_words', True),
        supports_response_schema=runtime.get('supports_response_schema', False),
        supports_vision=runtime.get('supports_vision', False),
        strip_reasoning_effort=runtime.get('strip_reasoning_effort', False),
        thinking_mode=runtime.get('thinking_mode'),
        strip_temperature=runtime.get('strip_temperature', False),
        strip_top_p=runtime.get('strip_top_p', False),
        strip_penalties=runtime.get('strip_penalties', False),
        use_max_completion_tokens=runtime.get('use_max_completion_tokens', False),
        default_temperature=runtime.get('default_temperature'),
    )


@functools.lru_cache(maxsize=1)
def get_catalog() -> tuple[ModelEntry, ...]:
    """Return all model entries from provider catalog files."""
    data = _load_raw()
    entries: list[ModelEntry] = []
    for provider, provider_data in data.get('providers', {}).items():
        provider_client = provider_data.get('client')
        source_file = provider_data.get('source_file', '<catalog>')
        for name, info in provider_data.get('models', {}).items():
            runtime, metadata = _parse_model_catalog_info(
                info,
                source_file=source_file,
                model_name=name,
            )
            declared_provider = str(runtime.get('provider') or provider).strip().lower()
            if declared_provider != provider:
                raise ValueError(
                    f'Model {name!r} in {source_file} declares provider '
                    f'{declared_provider!r}, expected {provider!r}'
                )
            entries.append(
                _entry_from_catalog(
                    provider=provider,
                    provider_client=provider_client,
                    source_file=source_file,
                    name=name,
                    runtime=runtime,
                    metadata=metadata,
                )
            )
    return tuple(entries)


@functools.lru_cache(maxsize=1)
def _name_index() -> dict[str, ModelEntry]:
    """Build a lookup dict without crossing provider boundaries.

    Bare model names are indexed only when they are unique across all provider
    catalogs.  Provider-prefixed names and explicit aliases stay exact.
    """
    idx: dict[str, ModelEntry] = {}
    bare_candidates: dict[str, list[ModelEntry]] = {}

    def add_exact(key: str | None, entry: ModelEntry) -> None:
        if not key:
            return
        idx[key] = entry
        idx[key.lower()] = entry

    def add_bare_candidate(key: str | None, entry: ModelEntry) -> None:
        if not key:
            return
        if entry.provider in {'opencode', 'opencode-go'}:
            return
        bare_candidates.setdefault(key.lower(), []).append(entry)

    for entry in get_catalog():
        add_exact(f'{entry.provider}/{entry.name}', entry)
        add_exact(f'{entry.provider}/{runtime_model_id(entry)}', entry)
        for alias in entry.aliases:
            if '/' in alias:
                add_exact(alias, entry)
            else:
                add_bare_candidate(alias, entry)
        add_bare_candidate(entry.name, entry)
        add_bare_candidate(runtime_model_id(entry), entry)

    for _key, matches in bare_candidates.items():
        unique = {(entry.provider, entry.name) for entry in matches}
        if len(unique) != 1:
            continue
        entry = matches[0]
        idx[_key] = entry
        add_exact(entry.name, entry)
        add_exact(runtime_model_id(entry), entry)
    return idx


def runtime_model_id(entry: ModelEntry) -> str:
    """Return the exact model id that should be sent to the provider."""
    return entry.provider_model_id or entry.name


def runtime_parameter_mode(entry: ModelEntry) -> dict[str, Any]:
    """Return the executable runtime parameter mode for a catalog entry.

    Provider metadata can contain raw docs or upstream SDK config. This helper
    describes only what Grinta's Python transport will actually apply.
    """
    from backend.inference.reasoning import (
        reasoning_effort_options,
        resolve_reasoning_plan,
        supports_reasoning,
    )

    if entry.thinking_mode:
        reasoning = f'catalog_thinking_mode:{entry.thinking_mode}'
    elif supports_reasoning(entry):
        plan = resolve_reasoning_plan(entry, reasoning_effort='medium')
        reasoning = (
            f'family_wire:{plan.wire}'
            if plan.enabled
            else f'family_wire:{plan.wire}:disabled'
        )
    else:
        reasoning = 'not_configured'
    options = reasoning_effort_options(entry, include_disabled=True)
    return {
        'reasoning': reasoning,
        'reasoning_effort_options': list(options),
        'temperature': 'stripped' if entry.strip_temperature else 'standard',
        'top_p': 'stripped' if entry.strip_top_p else 'standard',
        'penalties': 'stripped' if entry.strip_penalties else 'standard',
        'token_param': (
            'max_completion_tokens' if entry.use_max_completion_tokens else 'max_tokens'
        ),
        'parallel_tool_calls': (
            'enabled' if entry.supports_parallel_tool_calls else 'not_configured'
        ),
        'inference_endpoint': entry.inference_endpoint,
    }


def compact_metadata_for_log(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return compact docs-only metadata safe for per-call logs."""
    if not isinstance(metadata, dict):
        return metadata
    keys = (
        'source',
        'provider_id',
        'display_name',
        'family',
        'status',
        'release_date',
        'inference_url',
    )
    compact = {key: metadata[key] for key in keys if metadata.get(key) is not None}
    api = metadata.get('api')
    if isinstance(api, dict):
        compact['api'] = {
            key: api[key] for key in ('id', 'url', 'npm') if api.get(key) is not None
        }
    options = metadata.get('options') or metadata.get('runtime_options')
    if isinstance(options, dict) and options:
        compact['options'] = options
    capabilities = metadata.get('capabilities')
    if isinstance(capabilities, dict):
        compact['capabilities'] = _compact_capabilities_for_log(capabilities)
    variants = metadata.get(
        'ai_sdk_variants_metadata_only',
        metadata.get('variants'),
    )
    if isinstance(variants, dict) and variants:
        compact['ai_sdk_variants_metadata_only'] = {
            'names': sorted(variants.keys()),
            'not_applied_as_python_kwargs': True,
        }
    runtime_reasoning = metadata.get('runtime_reasoning')
    if isinstance(runtime_reasoning, dict):
        compact['runtime_reasoning'] = runtime_reasoning
    return compact


def _compact_capabilities_for_log(capabilities: dict[str, Any]) -> dict[str, Any]:
    compact = {
        key: capabilities[key]
        for key in ('temperature', 'reasoning', 'attachment', 'toolcall', 'interleaved')
        if key in capabilities
    }
    for direction in ('input', 'output'):
        modalities = capabilities.get(direction)
        if isinstance(modalities, dict):
            compact[f'{direction}_modalities'] = sorted(
                key for key, enabled in modalities.items() if enabled
            )
    return compact


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
    key = model.strip()
    if not key:
        return None
    idx = _name_index()
    entry = idx.get(key) or idx.get(key.lower())
    if entry:
        return entry

    if '/' in key:
        provider, bare = key.split('/', 1)
        return lookup_provider_model(provider, bare, allow_aliases=True)
    return None


def _pricing_for_entry(
    entry: ModelEntry, *, prompt_tokens: int | None = None
) -> dict[str, float] | None:
    input_price = entry.input_price_per_m
    output_price = entry.output_price_per_m
    cached_input = entry.cached_input_price_per_m
    cached_write = entry.cached_write_price_per_m
    threshold = entry.long_context_threshold_tokens
    if (
        prompt_tokens is not None
        and threshold is not None
        and prompt_tokens > threshold
    ):
        input_price = (
            entry.long_input_price_per_m
            if entry.long_input_price_per_m is not None
            else input_price
        )
        output_price = (
            entry.long_output_price_per_m
            if entry.long_output_price_per_m is not None
            else output_price
        )
        cached_input = (
            entry.long_cached_input_price_per_m
            if entry.long_cached_input_price_per_m is not None
            else cached_input
        )
        cached_write = (
            entry.long_cached_write_price_per_m
            if entry.long_cached_write_price_per_m is not None
            else cached_write
        )
    if input_price is None:
        return None
    return {
        'input': input_price,
        'output': output_price if output_price is not None else 0.0,
        'cached_input': cached_input if cached_input is not None else input_price,
        'cached_write': cached_write if cached_write is not None else input_price,
    }


def get_pricing(
    model: str, *, prompt_tokens: int | None = None
) -> dict[str, float] | None:
    """Get pricing for an exact catalog-resolved model.

    Returns ``{"input": <per_1M>, "output": <per_1M>}`` or ``None``.
    """
    entry = lookup(model)
    if entry:
        prices = _pricing_for_entry(entry, prompt_tokens=prompt_tokens)
        if prices is not None:
            return prices
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


def get_models_for_provider(provider: str, *, featured_only: bool = True) -> list[str]:
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


def get_model_options_by_provider(
    *, featured_only: bool = True
) -> dict[str, list[str]]:
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
            'vercel',
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
        'vercel',
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

    if entry.thinking_mode:
        _apply_thinking_mode(call_kwargs, entry, reasoning_effort, is_stream)
    else:
        from backend.inference.reasoning import (
            apply_reasoning_plan,
            resolve_reasoning_plan,
        )

        plan = resolve_reasoning_plan(entry, reasoning_effort)
        apply_reasoning_plan(call_kwargs, plan)

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
