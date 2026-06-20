"""Direct LLM clients for OpenAI, Anthropic, Google Gemini, and xAI Grok.

This module provides direct SDK integrations with major LLM providers,
offering a lightweight and stable alternative to multi-provider abstraction libraries.

Re-exports from submodules for backward compatibility.
"""

from backend.inference.clients.anthropic_client import AnthropicClient  # noqa: F401
from backend.inference.clients.base import (  # noqa: F401
    DirectLLMClient,
    LLMResponse,
    TransportProfile,
    aclose_shared_http_clients,
    bounded_llm_http_timeout,
    close_shared_http_clients,
    get_shared_async_http_client,
    get_shared_http_client,
)
from backend.inference.clients.factory import get_direct_client  # noqa: F401
from backend.inference.clients.openai_client import (  # noqa: F401
    OpenAIClient,
    OpenCodeResponsesClient,
)


def __getattr__(name: str):
    """Lazy module-level attribute access (PEP 562).

    Used to expose GeminiClient without creating an import cycle with
    backend.inference.providers.gemini_ops (which imports
    DirectLLMClient from us).
    """
    if name == 'GeminiClient':
        from backend.inference.providers.gemini_ops import GeminiClient

        return GeminiClient
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


__all__ = [
    'AnthropicClient',
    'DirectLLMClient',
    'GeminiClient',
    'LLMResponse',
    'OpenAIClient',
    'OpenCodeResponsesClient',
    'TransportProfile',
    'aclose_shared_http_clients',
    'bounded_llm_http_timeout',
    'close_shared_http_clients',
    'get_direct_client',
    'get_shared_async_http_client',
    'get_shared_http_client',
]
