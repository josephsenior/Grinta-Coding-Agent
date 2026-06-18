"""Split from ``llm.py`` — see ``backend.inference.llm`` facade."""

from __future__ import annotations

import copy
import time
from collections.abc import AsyncIterator, Callable
from typing import (
    TYPE_CHECKING,
    Any,
)

from backend.core import json_compat as json
from backend.core.errors import LLMNoResponseError
from backend.core.logger import app_logger as logger
from backend.core.message import Message
from backend.inference.debug_mixin import DebugMixin
from backend.inference.direct_clients import get_direct_client
from backend.inference.exceptions import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    BadRequestError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    InternalServerError,
    LLMError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
    format_html_api_error_response,
    is_context_window_error,
    is_html_api_body,
)
from backend.inference.llm.utils import create_pretrained_tokenizer, get_token_count
from backend.inference.metrics import Metrics
from backend.inference.capabilities.model_features import ModelFeatures, get_features
from backend.inference.retry_mixin import RetryMixin

if TYPE_CHECKING:
    from backend.core.config import LLMConfig

def _safe_exception_text(exc: Exception) -> str:
    """Return a robust exception message even if ``__str__`` is broken."""
    try:
        return str(exc)
    except Exception:
        return f'{type(exc).__name__} (unprintable exception)'


def _map_api_status_error(exc: Exception, model: str, provider: str) -> Exception:
    """Map APIStatusError by status code."""
    status = getattr(exc, 'status_code', None)
    if status in (401, 403):
        from backend.inference.providers.openai_ops import (
            simplify_openai_unauthorized_message,
        )

        msg = _safe_exception_text(exc)
        if provider == 'openai' and isinstance(status, int):
            msg = simplify_openai_unauthorized_message(exc, status)
        return AuthenticationError(
            msg,
            model=model,
            llm_provider=provider,
            status_code=status,
        )
    if status == 408:
        return Timeout(_safe_exception_text(exc), model=model, llm_provider=provider)
    if status == 503:
        return ServiceUnavailableError(
            _safe_exception_text(exc), model=model, llm_provider=provider
        )
    if isinstance(status, int) and 500 <= status <= 599:
        return InternalServerError(
            _safe_exception_text(exc),
            model=model,
            llm_provider=provider,
            status_code=status,
        )
    return APIError(
        _safe_exception_text(exc),
        model=model,
        llm_provider=provider,
        status_code=status,
    )


def _map_bad_request_with_context_check(
    exc: Exception, model: str, provider: str
) -> Exception:
    """Map BadRequestError, checking for context window overflow."""
    text = _safe_exception_text(exc)
    if is_context_window_error(text.lower(), exc):
        return ContextWindowExceededError(text, model=model, llm_provider=provider)
    return BadRequestError(text, model=model, llm_provider=provider)


def _map_openai_exception(exc: Exception, model: str) -> Exception | None:
    """Map OpenAI SDK exceptions."""
    try:
        import openai as _oai

        from backend.inference.providers.openai_ops import (
            extract_openai_http_status,
            simplify_openai_unauthorized_message,
        )
        from backend.inference.rate_limit_parser import enrich_rate_limit_exception

        status_early = extract_openai_http_status(exc)
        if status_early in (401, 403):
            return AuthenticationError(
                simplify_openai_unauthorized_message(exc, status_early),
                model=model,
                llm_provider='openai',
                status_code=status_early,
            )

        simple_map: list[tuple[type, type, str]] = [
            (_oai.AuthenticationError, AuthenticationError, 'openai'),
            (_oai.RateLimitError, RateLimitError, 'openai'),
            (_oai.APITimeoutError, Timeout, 'openai'),
            (_oai.APIConnectionError, APIConnectionError, 'openai'),
            (_oai.InternalServerError, InternalServerError, 'openai'),
        ]
        for sdk_cls, our_cls, prov in simple_map:
            if isinstance(exc, sdk_cls):
                mapped = our_cls(
                    _safe_exception_text(exc), model=model, llm_provider=prov
                )
                if isinstance(mapped, RateLimitError):
                    enrich_rate_limit_exception(exc, mapped)
                return mapped

        if isinstance(exc, _oai.BadRequestError):
            return _map_bad_request_with_context_check(exc, model, 'openai')
        if isinstance(exc, _oai.APIStatusError):
            return _map_api_status_error(exc, model, 'openai')
    except ImportError:
        pass
    return None


def _map_anthropic_exception(exc: Exception, model: str) -> Exception | None:
    """Map Anthropic SDK exceptions."""
    try:
        import anthropic as _anth

        from backend.inference.rate_limit_parser import enrich_rate_limit_exception

        simple_map: list[tuple[type, type, str]] = [
            (_anth.AuthenticationError, AuthenticationError, 'anthropic'),
            (_anth.RateLimitError, RateLimitError, 'anthropic'),
            (_anth.APITimeoutError, Timeout, 'anthropic'),
            (_anth.APIConnectionError, APIConnectionError, 'anthropic'),
            (_anth.InternalServerError, InternalServerError, 'anthropic'),
        ]
        for sdk_cls, our_cls, prov in simple_map:
            if isinstance(exc, sdk_cls):
                mapped = our_cls(
                    _safe_exception_text(exc), model=model, llm_provider=prov
                )
                if isinstance(mapped, RateLimitError):
                    enrich_rate_limit_exception(exc, mapped)
                return mapped

        if isinstance(exc, _anth.BadRequestError):
            return _map_bad_request_with_context_check(exc, model, 'anthropic')
        if isinstance(exc, _anth.APIStatusError):
            return _map_api_status_error(exc, model, 'anthropic')
    except ImportError:
        pass
    return None


def _try_google_exception_mapping(
    exc: Exception, model: str, exc_name: str, exc_str: str
) -> Exception | None:
    """Map Google/Generative AI exceptions. Returns None if not applicable."""
    if 'google' not in exc_name and 'generativeai' not in exc_name:
        return None
    if is_context_window_error(exc_str, exc):
        return ContextWindowExceededError(
            _safe_exception_text(exc), model=model, llm_provider='google'
        )
    if 'quota' in exc_str or 'rate' in exc_str:
        from backend.inference.rate_limit_parser import enrich_rate_limit_exception

        mapped = RateLimitError(
            _safe_exception_text(exc), model=model, llm_provider='google'
        )
        enrich_rate_limit_exception(exc, mapped)
        return mapped
    return APIError(_safe_exception_text(exc), model=model, llm_provider='google')


def _try_heuristic_exception_mapping(
    exc: Exception, model: str, exc_str: str
) -> Exception | None:
    """Map by heuristic string checks. Returns None if no match."""
    if (
        'content_filter' in exc_str
        or 'content policy' in exc_str
        or 'safety' in exc_str
    ):
        return ContentPolicyViolationError(_safe_exception_text(exc), model=model)
    if is_context_window_error(exc_str, exc):
        return ContextWindowExceededError(_safe_exception_text(exc), model=model)
    return None


def _map_provider_exception(exc: Exception, model: str) -> Exception:
    """Map provider SDK exceptions to our :mod:`backend.inference.exceptions` hierarchy.

    If the exception is already one of ours, it passes through unchanged.
    Unknown exceptions are wrapped in :class:`APIError` for uniformity.
    """
    if isinstance(exc, LLMError):
        return exc

    for mapper in [_map_openai_exception, _map_anthropic_exception]:
        mapped = mapper(exc, model)
        if mapped:
            return mapped

    exc_name = type(exc).__name__.lower()
    exc_str = _safe_exception_text(exc).lower()

    google_mapped = _try_google_exception_mapping(exc, model, exc_name, exc_str)
    if google_mapped:
        return google_mapped

    heuristic_mapped = _try_heuristic_exception_mapping(exc, model, exc_str)
    if heuristic_mapped:
        return heuristic_mapped

    raw = _safe_exception_text(exc)
    if is_html_api_body(raw):
        return APIError(
            format_html_api_error_response(raw, base_url=None, model=model),
            model=model,
        )

    return APIError(_safe_exception_text(exc), model=model)
