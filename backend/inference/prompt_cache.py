"""Provider-agnostic prompt-cache backend interface.

Background: prompt caching is a per-provider feature. Gemini exposes
explicit ``client.caches.create()`` resources; Anthropic uses
``cache_control`` blocks on individual content parts; OpenAI handles caching
implicitly server-side. The original codebase had a Gemini-specific singleton
(``gemini_cache_manager``) that the ``GeminiClient`` reached into directly.
That coupled the client layer to one provider's caching mechanism.

This module exposes a small protocol so other providers can register their own
backend, and a no-op default for providers that don't expose explicit cache
handles. Consumers fetch a backend via :func:`get_prompt_cache` and call
:meth:`PromptCacheBackend.get_or_create_cache_handle`. The default no-op
returns ``None``, which all current call sites already treat as "caching
disabled".

The legacy ``backend.inference.gemini_cache.gemini_cache_manager`` remains as
the registered backend for ``provider == 'google'``.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from backend.core.logger import app_logger as logger


@runtime_checkable
class PromptCacheBackend(Protocol):
    """Provider-agnostic prompt cache contract.

    Implementations are expected to be safe to call from multiple threads
    and to handle their own TTL / cleanup policy.
    """

    def get_or_create_cache_handle(
        self,
        *,
        client: Any,
        model: str,
        system_instruction: str | None,
        messages: list[dict[str, Any]],
    ) -> str | None:
        """Return a backend-specific cache handle, or ``None`` if unavailable.

        ``client`` is the provider SDK client (e.g. ``genai.Client``) the
        backend uses to manage the remote cache resource. Implementations
        should never raise — failures must be logged and ``None`` returned
        so the calling client falls back to the uncached request.
        """


class _NoOpPromptCache:
    """Default backend used when a provider exposes no explicit cache API.

    OpenAI-style providers fall through to this — server-side caching (when
    available) is transparent, so there is nothing for the client to manage.
    """

    def get_or_create_cache_handle(
        self,
        *,
        client: Any,
        model: str,
        system_instruction: str | None,
        messages: list[dict[str, Any]],
    ) -> str | None:
        return None


_NO_OP_BACKEND: PromptCacheBackend = _NoOpPromptCache()
_REGISTRY: dict[str, PromptCacheBackend] = {}


def register_prompt_cache_backend(provider: str, backend: PromptCacheBackend) -> None:
    """Register a backend for a provider key (lowercased canonical name)."""
    _REGISTRY[provider.strip().lower()] = backend


def get_prompt_cache(provider: str | None) -> PromptCacheBackend:
    """Return the registered backend for ``provider`` or a no-op fallback."""
    if not provider:
        return _NO_OP_BACKEND
    key = provider.strip().lower()
    backend = _REGISTRY.get(key)
    if backend is None:
        return _NO_OP_BACKEND
    return backend


def _register_default_backends() -> None:
    """Wire the legacy Gemini cache manager into the new interface.

    Imported lazily so that environments without the Google SDK still load
    this module cleanly. The Gemini backend itself defers ``google.genai``
    imports to call time.
    """
    try:
        from backend.inference.gemini_cache import gemini_cache_manager
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug('Gemini prompt cache backend unavailable: %s', exc)
        return

    class _GeminiAdapter:
        def get_or_create_cache_handle(
            self,
            *,
            client: Any,
            model: str,
            system_instruction: str | None,
            messages: list[dict[str, Any]],
        ) -> str | None:
            return gemini_cache_manager.get_or_create_cache(
                client=client,
                model=model,
                system_instruction=system_instruction,
                messages=messages,
            )

    register_prompt_cache_backend('google', _GeminiAdapter())


_register_default_backends()


__all__ = [
    'PromptCacheBackend',
    'get_prompt_cache',
    'register_prompt_cache_backend',
]
