"""Helper to emit operation-labeled metrics from tenacity retry hooks.

Provides a small factory to create a `before_sleep` callable suitable for
passing into tenacity.retry(..., before_sleep=...). The callable records an
`attempt` metric and, on final success/failure, emits `retry_success` or
`retry_failure` events via the metrics facade.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable

from tenacity import RetryCallState

from backend.utils.metrics_labels import sanitize_operation_label

logger = logging.getLogger(__name__)


def call_tenacity_hooks(
    before: Callable[[RetryCallState], None] | None,
    after: Callable[[RetryCallState], None] | None,
    retry_state: RetryCallState,
) -> None:
    """Safely call provided tenacity hook callables.

    This is useful for sites that programmatically invoke the generated
    hook functions (rather than passing them to tenacity). Keeps a single
    safe pattern so instrumentation cannot raise.
    """
    if before:
        with contextlib.suppress(Exception):
            before(retry_state)
    if after:
        with contextlib.suppress(Exception):
            after(retry_state)


def _record_metrics_event_runtime(ev: dict) -> None:
    """Record a metrics event (currently a no-op)."""
    return


def tenacity_before_sleep_factory(operation: str) -> Callable[[RetryCallState], None]:
    """Return a before_sleep(retry_state, exception) function for tenacity.

    Args:
        operation: stable operation name used as the `operation` label in metrics.

    Returns:
        Callable suitable for tenacity `before_sleep` hook.

    """

    def _before_sleep(retry_state: RetryCallState) -> None:
        with contextlib.suppress(Exception):
            stop_state = getattr(retry_state, 'stop', None)
            max_attempts = None
            if stop_state is not None:
                max_attempts = getattr(stop_state, 'max_attempts', None)
            _record_metrics_event_runtime(
                {
                    'status': 'attempt',
                    'operation': sanitize_operation_label(operation),
                    'attempt_index': getattr(retry_state, 'attempt_number', None),
                    'max_attempts': max_attempts,
                },
            )

    return _before_sleep


def tenacity_after_factory(operation: str) -> Callable[[RetryCallState], None]:
    """Return an `after(retry_state)` hook for tenacity that records final.

    success or failure events when retries complete.

    The hook is safe to attach for all tenacity retries; it will record a
    `retry_success` when the retry outcome is successful and a `retry_failure`
    when retries are exhausted.
    """

    def _after(retry_state: RetryCallState) -> None:
        try:
            op = sanitize_operation_label(operation)
            outcome = getattr(retry_state, 'outcome', None)
            try:
                if (
                    outcome is not None
                    and hasattr(outcome, 'successful')
                    and outcome.successful()
                ):
                    _record_metrics_event_runtime(
                        {'status': 'retry_success', 'operation': op}
                    )
                    return
            except Exception as exc:
                logger.debug(
                    'tenacity after-hook: outcome.successful() raised: %s', exc
                )
            attempt_idx = getattr(retry_state, 'attempt_number', None)
            stop_state = getattr(retry_state, 'stop', None)
            max_attempts = (
                getattr(stop_state, 'max_attempts', None)
                if stop_state is not None
                else None
            )
            if (
                isinstance(attempt_idx, int)
                and isinstance(max_attempts, int)
                and (attempt_idx >= max_attempts)
            ):
                _record_metrics_event_runtime(
                    {
                        'status': 'retry_failure',
                        'operation': op,
                        'attempt_index': attempt_idx,
                        'max_attempts': max_attempts,
                        'error': str(
                            getattr(retry_state, 'outcome', None)
                            or getattr(retry_state, 'exception', None)
                            or '',
                        ),
                    },
                )
        except Exception as exc:
            logger.debug('tenacity after-hook failed for %s: %s', operation, exc)

    return _after
