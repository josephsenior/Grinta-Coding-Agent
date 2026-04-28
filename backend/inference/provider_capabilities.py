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


_DEFAULT_PROVIDER = ProviderCapabilities(name='__default__')


# Registry keyed by canonical provider family name. Use lowercase identifiers
# matching ``backend.inference.provider_resolver``'s output.
_PROVIDER_REGISTRY: dict[str, ProviderCapabilities] = {
    'openai': ProviderCapabilities(
        name='openai',
        supports_native_tools=True,
        supports_prompt_cache=False,
        supports_tool_replay=True,
    ),
    'anthropic': ProviderCapabilities(
        name='anthropic',
        supports_native_tools=True,
        supports_prompt_cache=True,
        supports_tool_replay=True,
    ),
    'google': ProviderCapabilities(
        name='google',
        supports_native_tools=True,
        supports_prompt_cache=True,
        supports_tool_replay=False,
        requires_thought_signature=True,
        flatten_tool_history=True,
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


__all__ = [
    'ProviderCapabilities',
    'get_provider_capabilities',
    'known_provider_names',
    'register_provider_capabilities',
    # Re-export for callers that want to clone-and-extend.
    'replace',
    'field',
]
