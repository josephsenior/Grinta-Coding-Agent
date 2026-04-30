"""Retry utilities shared by App LLM clients for resilient completions."""

import contextlib
from collections.abc import Callable
from typing import Any

from tenacity import (
    retry,
    retry_if_exception_type,
    wait_exponential,
    wait_random_exponential,
)
from tenacity.stop import stop_base

from backend.core.errors import LLMNoResponseError
from backend.core.logger import app_logger as logger
from backend.inference.exceptions import RateLimitError, RateLimitKind
from backend.utils.tenacity_metrics import (
    tenacity_after_factory,
    tenacity_before_sleep_factory,
)
from backend.utils.tenacity_stop import stop_if_should_exit

try:
    from backend.core.constants import DEFAULT_LLM_NUM_RETRIES_BONUS_FOR_HINTED
except Exception:  # pragma: no cover - constants module is always importable
    DEFAULT_LLM_NUM_RETRIES_BONUS_FOR_HINTED = 5


# Per-kind backoff envelopes (seconds). TPM/RPD limits typically need longer
# waits than RPM/concurrency caps which clear within a single sliding window.
_KIND_WAIT_BOUNDS: dict[RateLimitKind, tuple[float, float]] = {
    RateLimitKind.TPM: (5.0, 90.0),
    RateLimitKind.RPM: (2.0, 30.0),
    RateLimitKind.RPD: (30.0, 300.0),
    RateLimitKind.CONCURRENCY: (1.0, 15.0),
    RateLimitKind.UNKNOWN: (3.0, 30.0),
}

# Cap on a server-supplied ``Retry-After`` we will actually honor verbatim.
# Anything larger gets clipped so a single bad header cannot stall the agent
# for an unreasonable amount of time. Larger waits still surface as the
# bounded exponential below.
_RETRY_AFTER_HARD_CAP_SECONDS = 600.0


class RetryMixin:
    """Mixin class for retry logic."""

    def retry_decorator(self, **kwargs: Any) -> Callable:
        """Create a LLM retry decorator with customizable parameters. This is used for 429 errors, and a few other exceptions in LLM classes.

        Args:
            **kwargs: Keyword arguments to override default retry behavior.
                      Keys: num_retries, retry_exceptions, retry_min_wait, retry_max_wait, retry_multiplier

        Returns:
            A retry decorator with the parameters customizable in configuration.

        """
        num_retries = kwargs.get('num_retries', 3)
        retry_exceptions: tuple = kwargs.get(
            'retry_exceptions',
            (RuntimeError, TimeoutError, ConnectionError),
        )
        retry_min_wait = kwargs.get('retry_min_wait', 1)
        retry_max_wait = kwargs.get('retry_max_wait', 10)
        retry_multiplier = kwargs.get('retry_multiplier', 1)
        retry_listener = kwargs.get('retry_listener')

        def before_sleep(retry_state: Any) -> None:
            """Handle retry sleep with logging and temperature adjustment.

            Args:
                retry_state: Tenacity retry state object

            """
            self.log_retry_attempt(retry_state)
            if retry_listener:
                retry_listener(retry_state.attempt_number, num_retries)
            exception = retry_state.outcome.exception()
            if isinstance(exception, LLMNoResponseError) and hasattr(
                retry_state, 'kwargs'
            ):
                current_temp = retry_state.kwargs.get('temperature', 0)
                if current_temp == 0:
                    retry_state.kwargs['temperature'] = 1.0
                    logger.warning(
                        'LLMNoResponseError detected with temperature=0, setting temperature to 1.0 for next attempt.',
                    )
                else:
                    logger.warning(
                        'LLMNoResponseError detected with temperature=%s, keeping original temperature',
                        current_temp,
                    )

        try:
            metrics_before = tenacity_before_sleep_factory('llm_completion')
            tenacity_after_factory('llm_completion')
        except Exception:
            metrics_before = None

        def _composed_before_sleep(state: Any) -> None:
            with contextlib.suppress(Exception):
                before_sleep(state)
            try:
                if metrics_before:
                    metrics_before(state)
            except Exception:
                pass

        base_wait = wait_exponential(
            multiplier=retry_multiplier, min=retry_min_wait, max=retry_max_wait
        )

        def _wait_strategy(state: Any) -> float:
            """Honor server-supplied retry hints when the failure is a 429.

            Order of precedence:
            1. ``RateLimitError.retry_after`` (parsed from ``Retry-After`` /
               provider reset headers) — clipped to a sane hard cap.
            2. Per-:class:`RateLimitKind` randomized exponential envelope.
            3. The original config-driven exponential backoff.
            """
            try:
                exc = state.outcome.exception() if state.outcome else None
            except Exception:
                exc = None
            if isinstance(exc, RateLimitError):
                if exc.retry_after is not None and exc.retry_after > 0:
                    return min(exc.retry_after, _RETRY_AFTER_HARD_CAP_SECONDS)
                low, high = _KIND_WAIT_BOUNDS.get(
                    exc.kind, _KIND_WAIT_BOUNDS[RateLimitKind.UNKNOWN]
                )
                kind_wait = wait_random_exponential(multiplier=1.0, max=high)
                value = float(kind_wait(state))
                return max(low, value)
            return float(base_wait(state))

        max_attempts_with_hint = num_retries + max(
            0, int(DEFAULT_LLM_NUM_RETRIES_BONUS_FOR_HINTED)
        )

        class _StopWhenBudgetExhausted(stop_base):
            """Stop after ``num_retries`` attempts unless the latest failure
            carries a server-supplied ``retry_after`` hint, in which case
            allow up to ``num_retries + bonus`` attempts before giving up.

            Rationale: when the provider tells us *exactly* how long to wait
            we should be patient (the wait is bounded). When the failure is
            unbounded we keep the original tight cap to avoid wasting the
            user's time on an indefinite back-off.
            """

            def __call__(self, state: Any) -> bool:
                attempts = int(getattr(state, 'attempt_number', 0) or 0)
                try:
                    exc = state.outcome.exception() if state.outcome else None
                except Exception:
                    exc = None
                has_hint = (
                    isinstance(exc, RateLimitError)
                    and exc.retry_after is not None
                    and exc.retry_after > 0
                )
                cap = max_attempts_with_hint if has_hint else num_retries
                return attempts >= cap

        retry_decorator: Callable = retry(
            before_sleep=_composed_before_sleep,
            stop=_StopWhenBudgetExhausted() | stop_if_should_exit(),
            reraise=True,
            retry=retry_if_exception_type(retry_exceptions),
            wait=_wait_strategy,
        )
        return retry_decorator

    def log_retry_attempt(self, retry_state: Any) -> None:
        """Log retry attempts."""
        exception = retry_state.outcome.exception()
        if hasattr(retry_state, 'retry_object') and hasattr(
            retry_state.retry_object, 'stop'
        ):
            stop_condition = retry_state.retry_object.stop
            stop_funcs = []
            if hasattr(stop_condition, 'stops'):
                stop_funcs = stop_condition.stops
            else:
                stop_funcs = [stop_condition]
            for stop_func in stop_funcs:
                if hasattr(stop_func, 'max_attempts'):
                    exception.retry_attempt = retry_state.attempt_number
                    exception.max_retries = stop_func.max_attempts
                    break
        logger.error(
            '%s. Attempt #%s | You can customize retry values in the configuration.',
            exception,
            retry_state.attempt_number,
        )
