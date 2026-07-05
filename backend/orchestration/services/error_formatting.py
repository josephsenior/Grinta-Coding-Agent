"""Error formatting helpers for recovery service."""

from __future__ import annotations

from backend.core.errors import (
    AgentRuntimeDisconnectedError,
    AgentRuntimeError,
    LLMContextWindowExceedError,
    LLMNoResponseError,
)
from backend.inference.exceptions import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    ContextWindowExceededError,
    InternalServerError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)

# Re-use the same exception tuples from recovery_service
_RATE_LIMITED_EXCEPTIONS = (RateLimitError, ServiceUnavailableError)
_HARD_STOP_EXCEPTIONS = (
    AuthenticationError,
    BadRequestError,
    ContextWindowExceededError,
    LLMContextWindowExceedError,
    AgentRuntimeDisconnectedError,
)
_TRANSIENT_LLM_INFRA_EXCEPTIONS = (
    APIConnectionError,
    InternalServerError,
    LLMNoResponseError,
    Timeout,
)


def resolve_error_id(exc: Exception) -> str:
    if isinstance(exc, Timeout):
        return 'LLM_TIMEOUT'
    if isinstance(exc, BadRequestError):
        return 'LLM_BAD_REQUEST'
    if isinstance(exc, LLMContextWindowExceedError | ContextWindowExceededError):
        return 'LLM_CONTEXT_WINDOW_EXCEEDED'
    if isinstance(exc, AgentRuntimeDisconnectedError):
        return 'AGENT_RUNTIME_DISCONNECTED'
    if isinstance(exc, AgentRuntimeError):
        return 'AGENT_RUNTIME_ERROR'
    return 'AGENT_STEP_EXCEPTION'


def format_error_text(exc: Exception) -> str:
    if isinstance(exc, Timeout):
        return 'LLM provider timed out.'
    if isinstance(exc, AuthenticationError):
        model = getattr(exc, 'model', None) or '?'
        provider = getattr(exc, 'llm_provider', None) or '?'
        return (
            f'{exc}\n'
            f'The LLM provider ({provider}) rejected access to model "{model}".\n'
            f'Run /settings to update your model or API key.'
        )
    if isinstance(exc, BadRequestError):
        model = getattr(exc, 'model', None) or '?'
        provider = getattr(exc, 'llm_provider', None) or '?'
        return (
            f'{exc}\n'
            f'The LLM provider ({provider}) rejected the request for model "{model}".\n'
            f'Run /settings to review model parameters (temperature, max tokens, etc.).'
        )
    if isinstance(exc, _RATE_LIMITED_EXCEPTIONS):
        return _format_rate_limit_text(
            exc, getattr(exc, 'kind', None), getattr(exc, 'retry_after', None)
        )
    return f'{type(exc).__name__}: {exc}'


def format_error_guidance(exc: Exception) -> str:
    if isinstance(exc, AgentRuntimeDisconnectedError):
        return (
            'The agent runtime has disconnected or failed to initialize. '
            'This is a persistent state that requires a session reset or '
            'infrastructure check. CONTROL IS RETURNED TO USER.'
        )
    if isinstance(exc, AuthenticationError):
        return ''
    if isinstance(exc, BadRequestError):
        return (
            'This error requires user intervention (check model settings and '
            'provider-supported parameters). Wait for the user to fix the configuration.'
        )
    if isinstance(exc, _HARD_STOP_EXCEPTIONS):
        return (
            'This error requires user intervention (check credentials, model name, '
            'or context window). Wait for the user to fix the configuration.'
        )
    if isinstance(exc, _RATE_LIMITED_EXCEPTIONS):
        return _format_rate_limit_guidance(
            getattr(exc, 'kind', None), getattr(exc, 'retry_after', None)
        )
    if isinstance(exc, Timeout):
        return ''
    if isinstance(exc, _TRANSIENT_LLM_INFRA_EXCEPTIONS):
        return (
            'Transient provider or network issue. Automatic backoff and retry '
            'will run if the retry queue is available; otherwise the agent will '
            'return to the prompt.'
        )
    return ''


def _format_rate_limit_text(exc: Exception, rate_kind, retry_after) -> str:
    import re

    from backend.inference.exceptions import RateLimitKind

    kind_value = getattr(rate_kind, 'value', str(rate_kind)) if rate_kind else None
    base_text = str(exc) if exc.args else 'Rate limit exceeded'
    base_text = re.sub(r'https?://\S+', '[link]', base_text)

    if kind_value == RateLimitKind.RPD.value:
        return (
            '⚠️ Daily quota exhausted. Your free-tier limit has been reached for today.'
        )
    elif kind_value == RateLimitKind.RPM.value:
        return '⚠️ Too many requests per minute (RPM limit).'
    elif kind_value == RateLimitKind.TPM.value:
        return '⚠️ Too many tokens used per minute (TPM limit).'
    else:
        return f'⚠️ Rate limit ({base_text})'


def _format_rate_limit_guidance(rate_kind, retry_after) -> str:
    from backend.inference.exceptions import RateLimitKind

    kind_value = getattr(rate_kind, 'value', str(rate_kind)) if rate_kind else None

    if kind_value == RateLimitKind.RPD.value:
        return (
            '🎯 Next steps: '
            '1) Wait until midnight UTC for quota to reset, OR '
            '2) Add credits at https://openrouter.ai/credits to unlock 1000 requests/day, OR '
            '3) Switch to a different model in /settings.'
        )
    elif kind_value == RateLimitKind.RPM.value:
        if retry_after:
            return f'Waiting {retry_after:.0f}s before automatic retry...'
        return 'Waiting ~1 minute before retrying (per-minute limit).'
    elif kind_value == RateLimitKind.TPM.value:
        if retry_after:
            return f'Waiting {retry_after:.0f}s for token quota to refresh...'
        return 'Waiting for token quota to refresh...'
    else:
        return (
            'Will retry automatically. If this persists, check your provider dashboard.'
        )


def is_transient_llm_infra(exc: Exception) -> bool:
    """True for provider/network failures retried by the outer queue."""
    return isinstance(exc, _TRANSIENT_LLM_INFRA_EXCEPTIONS)


def exception_is_notify_ui_only(
    exc: Exception,
    hard_stop_exceptions: tuple[type[Exception], ...],
    rate_limited_exceptions: tuple[type[Exception], ...],
    transient_exceptions: tuple[type[Exception], ...],
) -> bool:
    """Return True when an exception is HUD/toast-only (not agent-actionable)."""
    from backend.core.errors import AgentRuntimeError
    from backend.inference.exceptions import APIError

    return (
        isinstance(exc, hard_stop_exceptions)
        or isinstance(exc, rate_limited_exceptions)
        or isinstance(exc, transient_exceptions)
        or isinstance(exc, (APIError, AgentRuntimeError))
        or isinstance(exc, (ImportError, ModuleNotFoundError))
    )


# Guard observations are for the model; they must not advance tool-error counters.
GUARD_CIRCUIT_BREAKER_ERROR_IDS: frozenset[str] = frozenset(
    {
        'CIRCUIT_BREAKER_WARNING',
        'CIRCUIT_BREAKER_FORCED_SWITCH',
        'CIRCUIT_BREAKER_TRIPPED',
    }
)


def observation_skips_circuit_breaker(obs: object) -> bool:
    """Return True when an ErrorObservation must not count as a tool failure."""
    if getattr(obs, 'notify_ui_only', False) or getattr(obs, 'agent_only', False):
        return True
    error_id = str(getattr(obs, 'error_id', '') or '')
    return error_id in GUARD_CIRCUIT_BREAKER_ERROR_IDS


def format_exception(
    exc, hard_stop_exceptions, rate_limited_exceptions, transient_exceptions
):
    """Format an exception into (text, error_id, notify_ui_only)."""
    notify_ui_only = exception_is_notify_ui_only(
        exc, hard_stop_exceptions, rate_limited_exceptions, transient_exceptions
    )
    err_id = resolve_error_id(exc)
    text = format_error_text(exc)
    guidance = format_error_guidance(exc)
    if guidance:
        text = f'{text}\n\n{guidance}'
    return text, err_id, notify_ui_only
