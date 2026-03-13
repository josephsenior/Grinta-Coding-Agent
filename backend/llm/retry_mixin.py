"""Retry utilities shared by Forge LLM clients for resilient completions."""

import contextlib
from collections.abc import Callable
from typing import Any

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from backend.core.errors import LLMNoResponseError
from backend.core.logger import forge_logger as logger
from backend.utils.tenacity_metrics import (
    tenacity_after_factory,
    tenacity_before_sleep_factory,
)
from backend.utils.tenacity_stop import stop_if_should_exit


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
        num_retries = kwargs.get("num_retries", 3)
        retry_exceptions: tuple = kwargs.get(
            "retry_exceptions",
            (RuntimeError, TimeoutError, ConnectionError),
        )
        retry_min_wait = kwargs.get("retry_min_wait", 1)
        retry_max_wait = kwargs.get("retry_max_wait", 10)
        retry_multiplier = kwargs.get("retry_multiplier", 1)
        retry_listener = kwargs.get("retry_listener")

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
                retry_state, "kwargs"
            ):
                current_temp = retry_state.kwargs.get("temperature", 0)
                if current_temp == 0:
                    retry_state.kwargs["temperature"] = 1.0
                    logger.warning(
                        "LLMNoResponseError detected with temperature=0, setting temperature to 1.0 for next attempt.",
                    )
                else:
                    logger.warning(
                        "LLMNoResponseError detected with temperature=%s, keeping original temperature",
                        current_temp,
                    )

        try:
            metrics_before = tenacity_before_sleep_factory("llm_completion")
            tenacity_after_factory("llm_completion")
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

        retry_decorator: Callable = retry(
            before_sleep=_composed_before_sleep,
            stop=stop_after_attempt(num_retries) | stop_if_should_exit(),
            reraise=True,
            retry=retry_if_exception_type(retry_exceptions),
            wait=wait_exponential(
                multiplier=retry_multiplier, min=retry_min_wait, max=retry_max_wait
            ),
        )
        return retry_decorator

    def log_retry_attempt(self, retry_state: Any) -> None:
        """Log retry attempts."""
        exception = retry_state.outcome.exception()
        if hasattr(retry_state, "retry_object") and hasattr(
            retry_state.retry_object, "stop"
        ):
            stop_condition = retry_state.retry_object.stop
            stop_funcs = []
            if hasattr(stop_condition, "stops"):
                stop_funcs = stop_condition.stops
            else:
                stop_funcs = [stop_condition]
            for stop_func in stop_funcs:
                if hasattr(stop_func, "max_attempts"):
                    exception.retry_attempt = retry_state.attempt_number
                    exception.max_retries = stop_func.max_attempts
                    break
        logger.error(
            "%s. Attempt #%s | You can customize retry values in the configuration.",
            exception,
            retry_state.attempt_number,
        )
