"""Provider-level capability registry.

Centralizes per-provider behavioural quirks (native tool calling,
prompt-cache support, tool-replay correctness, etc.) so transport / mapper
layers can ask *what a provider supports* instead of pattern-matching on
provider names. Adding a new provider means adding one entry here, not
hunting for ``model_family == 'google'`` checks across the codebase.

Capabilities cover *provider-level* truths (does this LLM family support
prompt caching at all? does it require thought-signature replay?). They
intentionally do **not** describe per-model deltas (context window, token
limits) — see ``backend.inference.capabilities.ModelCapabilities`` for
those.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class ProviderCapabilities:
    """Behavioural flags describing what a provider family supports.

    Defaults match an OpenAI-compatible REST endpoint with no special
    requirements. Override individual fields for providers that diverge
    (e.g. Google's thought-signature requirement, Anthropic's prompt
    caching, etc.).
    """

    name: str
    supports_native_tools: bool = True
    """True when the provider exposes a function-calling API the client
    can populate directly (assistants with ``tool_calls`` arrays, etc.).

    False forces the engine to flatten tool history into plain text before
    sending it.
    """

    supports_prompt_cache: bool = False
    """True when the provider exposes a server-side prompt cache backend
    that :mod:`backend.inference.prompt_cache` can target."""

    supports_tool_replay: bool = True
    """True when prior tool-call messages can be replayed verbatim across
    turns. False when the provider requires proprietary metadata (e.g.
    Google's ``thought_signature``) that gets lost on cross-protocol
    routes — those messages must be flattened before resend."""

    requires_thought_signature: bool = False
    """True when assistant messages must carry a backend-provided opaque
    signature for the next turn to be valid. Currently Google-family."""

    flatten_tool_history: bool = False
    """True when the engine should pre-flatten tool history into text on
    every request (independent of replay correctness — e.g. providers
    that simply don't model tool roles)."""

    # ── Capability adaptation (model-class fingerprints) ────────────
    # These are *capability* fingerprints, not provider tuning: any model
    # that natively reasons (CoT in weights) gets the ``inherent_reasoning``
    # treatment; small models get the trimmed prompt. Listing patterns here
    # in one registry keeps prompt_builder.py free of scattered
    # ``startswith`` checks and makes adding a new model a one-line entry.
    inherent_reasoning_models: tuple[str, ...] = ()
    """Model-id substrings whose weights perform CoT natively, so the
    explicit ``think`` scaffold should be stripped from prompts."""

    small_model_patterns: tuple[str, ...] = ()
    """Model-id substrings that overflow on full prompts + 45 tools and
    should receive the ``short_mode`` rendering."""

    token_correction_factor: float = 1.0
    """Multiplier applied to o200k_base token estimates for budgeting on
    this provider's models (Anthropic tokenizes ~5% more on average)."""


_DEFAULT_PROVIDER = ProviderCapabilities(name='__default__')


# Registry keyed by canonical provider family name. Use lowercase identifiers
# matching ``backend.inference.provider_resolver``'s output.
_PROVIDER_REGISTRY: dict[str, ProviderCapabilities] = {
    'openai': ProviderCapabilities(
        name='openai',
        supports_native_tools=True,
        supports_prompt_cache=False,
        supports_tool_replay=True,
        inherent_reasoning_models=('o1', 'o3', 'o4'),
        small_model_patterns=('gpt-4o-mini',),
    ),
    'anthropic': ProviderCapabilities(
        name='anthropic',
        supports_native_tools=True,
        supports_prompt_cache=True,
        supports_tool_replay=True,
        # Claude tokenizer encodes ~5% more tokens than GPT-4o on typical
        # code/text — budget accordingly when using o200k_base estimator.
        token_correction_factor=1.05,
        small_model_patterns=('haiku',),
    ),
    'google': ProviderCapabilities(
        name='google',
        supports_native_tools=True,
        supports_prompt_cache=True,
        supports_tool_replay=False,
        requires_thought_signature=True,
        flatten_tool_history=True,
        inherent_reasoning_models=(
            'gemini-2.0-flash-thinking',
            'gemini-2.5-pro',
        ),
        small_model_patterns=('gemini-2.5-flash-lite',),
    ),
    'deepseek': ProviderCapabilities(
        name='deepseek',
        inherent_reasoning_models=('deepseek-reasoner', 'deepseek-r1'),
    ),
    'xai': ProviderCapabilities(
        name='xai',
        inherent_reasoning_models=('grok-4',),
    ),
    'ollama': ProviderCapabilities(
        name='ollama',
        small_model_patterns=(
            'llama3.2',
            'llama-3.2',
            'llama3-8b',
            'llama-3-8b',
            'mistral-7b',
            'qwen2.5-7b',
            'qwen-7b',
            'phi-3',
            'phi3',
            'gemma-7b',
            'gemma2-9b',
            'codellama-7b',
        ),
    ),
}


def get_provider_capabilities(provider: str | None) -> ProviderCapabilities:
    """Return capabilities for ``provider`` or a safe OpenAI-compatible default."""
    if not provider:
        return _DEFAULT_PROVIDER
    key = provider.strip().lower()
    return _PROVIDER_REGISTRY.get(key, _DEFAULT_PROVIDER)


def register_provider_capabilities(caps: ProviderCapabilities) -> None:
    """Register or replace capabilities for a provider.

    Intended for plugin-style provider extensions. Existing entries are
    overwritten — callers wanting to extend a known provider should fetch
    the existing record, ``dataclasses.replace`` it, then re-register.
    """
    _PROVIDER_REGISTRY[caps.name.strip().lower()] = caps


def known_provider_names() -> list[str]:
    """Return the sorted list of registered provider keys."""
    return sorted(_PROVIDER_REGISTRY.keys())


def _bare_model_id(model_id: str | None) -> str:
    """Return the lowercase model id with provider prefix stripped."""
    mid = (model_id or '').strip().lower()
    if not mid:
        return ''
    return mid.split('/', 1)[-1]


def _extract_provider_from_model(model_id: str | None) -> str | None:
    """Best-effort provider extraction from a model id.

    Recognises ``provider/model`` prefixes; falls back to a small heuristic
    so prompt-builder logic doesn't need a full resolver round-trip.
    """
    mid = (model_id or '').strip().lower()
    if not mid:
        return None
    if '/' in mid:
        return mid.split('/', 1)[0] or None
    if mid.startswith('claude-'):
        return 'anthropic'
    if mid.startswith('gemini-'):
        return 'google'
    if mid.startswith('deepseek-'):
        return 'deepseek'
    if mid.startswith('grok-'):
        return 'xai'
    if mid.startswith('llama') or mid.startswith('phi') or mid.startswith('qwen'):
        return 'ollama'
    if mid.startswith(('gpt-', 'o1', 'o3', 'o4')):
        return 'openai'
    return None


def model_has_inherent_reasoning(model_id: str | None) -> bool:
    """Return True when ``model_id`` matches a known inherent-reasoning pattern.

    Consults the ``ProviderCapabilities.inherent_reasoning_models`` registry
    rather than scattered ``startswith`` checks.
    """
    bare = _bare_model_id(model_id)
    if not bare:
        return False
    provider = _extract_provider_from_model(model_id)
    caps = get_provider_capabilities(provider)
    if any(bare.startswith(p) or p in bare for p in caps.inherent_reasoning_models):
        return True
    # Belt-and-suspenders: when the provider couldn't be resolved, scan all
    # known providers so a bare ``o1`` (no openai/ prefix) still matches.
    if provider is None:
        for caps in _PROVIDER_REGISTRY.values():
            if any(
                bare.startswith(p) or p in bare
                for p in caps.inherent_reasoning_models
            ):
                return True
    return False


def model_is_small(model_id: str | None) -> bool:
    """Return True when ``model_id`` matches a known small/weak model pattern."""
    bare = _bare_model_id(model_id)
    if not bare:
        return False
    provider = _extract_provider_from_model(model_id)
    caps = get_provider_capabilities(provider)
    if any(p in bare for p in caps.small_model_patterns):
        return True
    if provider is None:
        for caps in _PROVIDER_REGISTRY.values():
            if any(p in bare for p in caps.small_model_patterns):
                return True
    return False


def model_token_correction(model_id: str | None) -> tuple[float, str]:
    """Return ``(multiplier, label)`` for tokenizer-budget correction."""
    provider = _extract_provider_from_model(model_id)
    if provider is None:
        return 1.0, 'o200k_base_default'
    caps = get_provider_capabilities(provider)
    if caps.token_correction_factor != 1.0:
        return caps.token_correction_factor, f'o200k_base+{caps.name}_correction'
    return 1.0, 'o200k_base'


__all__ = [
    'ProviderCapabilities',
    'get_provider_capabilities',
    'known_provider_names',
    'model_has_inherent_reasoning',
    'model_is_small',
    'model_token_correction',
    'register_provider_capabilities',
    # Re-export for callers that want to clone-and-extend.
    'replace',
    'field',
]
