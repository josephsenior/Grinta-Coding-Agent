"""Parse provider 429 responses into ``RateLimitKind`` + ``retry_after`` hints.

This module is provider-agnostic at the surface: it accepts an SDK exception
from any of the supported providers and inspects the attached HTTP response
(when present) plus the error string to classify the limit type and extract
the server-supplied wait hint in seconds.

The module never raises on malformed input; it falls back to
``RateLimitKind.UNKNOWN`` and ``retry_after=None``.
"""

from __future__ import annotations

from typing import Any

from backend.inference.exceptions import RateLimitKind

_TPM_HINTS = (
    'tokens per min',
    'tokens per minute',
    'tpm',
    'token rate limit',
    'token quota',
)
_RPM_HINTS = (
    'requests per min',
    'requests per minute',
    'rpm',
    'request rate limit',
)
_RPD_HINTS = (
    'requests per day',
    'rpd',
    'daily quota',
    'daily limit',
)
_CONCURRENCY_HINTS = (
    'concurrent',
    'concurrency',
    'parallel requests',
    'too many concurrent',
)


def _response_headers(exc: Exception) -> dict[str, str]:
    """Return a case-insensitive dict of response headers, or empty."""
    response = getattr(exc, 'response', None)
    headers = getattr(response, 'headers', None)
    if headers is None:
        return {}
    try:
        return {str(k).lower(): str(v) for k, v in dict(headers).items()}
    except Exception:
        return {}


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a ``Retry-After`` header value. Returns seconds or ``None``.

    Per RFC 7231 the value may be either an integer number of seconds or
    an HTTP-date. We support seconds and ms-suffixed strings; HTTP-dates
    are skipped (rare in LLM provider responses).
    """
    if not value:
        return None
    s = value.strip().lower()
    if not s:
        return None
    try:
        if s.endswith('ms'):
            return float(s[:-2]) / 1000.0
        if s.endswith('s'):
            return float(s[:-1])
        return float(s)
    except ValueError:
        return None


_DURATION_UNIT_MULTIPLIERS = {'h': 3600.0, 'm': 60.0, 's': 1.0}


def _apply_duration_unit(total: float, unit: str, value: float) -> float | None:
    multiplier = _DURATION_UNIT_MULTIPLIERS.get(unit)
    if multiplier is None:
        return None
    return total + value * multiplier


def _parse_duration_string(s: str) -> float | None:
    total = 0.0
    cur = ''
    matched = False
    for ch in s:
        if ch.isdigit() or ch == '.':
            cur += ch
            continue
        if not cur:
            continue
        try:
            n = float(cur)
        except ValueError:
            return None
        cur = ''
        result = _apply_duration_unit(total, ch, n)
        if result is None:
            return None
        total = result
        matched = True
    return total if matched else None


def _parse_reset_seconds(value: str | None) -> float | None:
    """Parse OpenAI/Anthropic ``*-reset-*`` headers like ``"6.5s"`` or ``"1m30s"``."""
    if not value:
        return None
    s = value.strip().lower()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    return _parse_duration_string(s)


def _classify_message(text: str) -> RateLimitKind:
    lowered = text.lower()
    for hint in _TPM_HINTS:
        if hint in lowered:
            return RateLimitKind.TPM
    for hint in _RPD_HINTS:
        if hint in lowered:
            return RateLimitKind.RPD
    for hint in _CONCURRENCY_HINTS:
        if hint in lowered:
            return RateLimitKind.CONCURRENCY
    for hint in _RPM_HINTS:
        if hint in lowered:
            return RateLimitKind.RPM
    return RateLimitKind.UNKNOWN


def _get_remaining_from_headers(headers: dict[str, str]) -> tuple[str | None, str | None]:
    rem_tokens = headers.get('x-ratelimit-remaining-tokens') or headers.get(
        'anthropic-ratelimit-tokens-remaining'
    )
    rem_requests = headers.get('x-ratelimit-remaining-requests') or headers.get(
        'anthropic-ratelimit-requests-remaining'
    )
    return rem_tokens, rem_requests


def _get_reset_from_headers(
    headers: dict[str, str],
) -> tuple[float | None, float | None]:
    reset_tokens = _parse_reset_seconds(
        headers.get('x-ratelimit-reset-tokens')
        or headers.get('anthropic-ratelimit-tokens-reset')
    )
    reset_requests = _parse_reset_seconds(
        headers.get('x-ratelimit-reset-requests')
        or headers.get('anthropic-ratelimit-requests-reset')
    )
    return reset_tokens, reset_requests


def _is_zero_remaining(v: str | None) -> bool:
    if v is None:
        return False
    try:
        return float(v) <= 0
    except ValueError:
        return False


def _pick_reset_hint(
    reset_tokens: float | None, reset_requests: float | None
) -> float | None:
    if reset_tokens is not None and reset_requests is not None:
        return max(reset_tokens, reset_requests)
    return reset_tokens if reset_tokens is not None else reset_requests


def _classify_from_headers(
    headers: dict[str, str], message: str
) -> tuple[RateLimitKind, float | None]:
    """Classify using OpenAI/Anthropic ``x-ratelimit-*`` headers when present.

    Returns the classified kind and the most relevant reset hint (seconds).
    """
    if not headers:
        return RateLimitKind.UNKNOWN, None

    rem_tokens, rem_requests = _get_remaining_from_headers(headers)
    reset_tokens, reset_requests = _get_reset_from_headers(headers)

    msg_kind = _classify_message(message)
    if _is_zero_remaining(rem_tokens) and not _is_zero_remaining(rem_requests):
        return RateLimitKind.TPM, reset_tokens
    if _is_zero_remaining(rem_requests) and not _is_zero_remaining(rem_tokens):
        return RateLimitKind.RPM, reset_requests
    return msg_kind, _pick_reset_hint(reset_tokens, reset_requests)


def classify_rate_limit(
    exc: Exception, *, fallback_message: str | None = None
) -> tuple[RateLimitKind, float | None]:
    """Inspect *exc* and return ``(kind, retry_after_seconds_or_None)``.

    The function is total: any failure to parse degrades to
    ``(RateLimitKind.UNKNOWN, None)``.
    """
    try:
        message = fallback_message if fallback_message is not None else str(exc)
    except Exception:
        message = ''

    headers = _response_headers(exc)
    retry_after = _parse_retry_after(headers.get('retry-after'))

    kind, header_reset = _classify_from_headers(headers, message)
    if kind is RateLimitKind.UNKNOWN:
        kind = _classify_message(message)

    # Pick the longest credible wait we have evidence for; the server-supplied
    # ``Retry-After`` is authoritative, otherwise use the header reset hint.
    if retry_after is None:
        retry_after = header_reset

    return kind, retry_after


def enrich_rate_limit_exception(exc: Any, mapped: Any) -> Any:
    """Populate ``kind`` and ``retry_after`` on a freshly mapped ``RateLimitError``.

    ``exc`` is the original SDK exception (it carries the HTTP response);
    ``mapped`` is our :class:`RateLimitError` instance. The function returns
    *mapped* unchanged for ergonomic chaining.
    """
    from backend.inference.exceptions import RateLimitError

    if not isinstance(mapped, RateLimitError):
        return mapped
    try:
        kind, retry_after = classify_rate_limit(
            exc, fallback_message=getattr(mapped, 'message', None)
        )
        # Only overwrite when we have a non-default classification, so callers
        # that already populated these fields are not clobbered.
        if mapped.kind is RateLimitKind.UNKNOWN:
            mapped.kind = kind
        if mapped.retry_after is None:
            mapped.retry_after = retry_after
    except Exception:
        # Classification is best-effort; never break error mapping.
        pass
    return mapped


__all__ = [
    'classify_rate_limit',
    'enrich_rate_limit_exception',
]
