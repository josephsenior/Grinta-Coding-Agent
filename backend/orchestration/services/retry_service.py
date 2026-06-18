from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from backend.core.logger import app_logger as logger
from backend.core.retry_queue import RetryQueue, RetryTask, get_retry_queue

if TYPE_CHECKING:
    from backend.orchestration.services.orchestration_context import (
        OrchestrationContext,
    )
    from backend.orchestration.session_orchestrator import SessionOrchestrator


class RetryService:
    """Owns retry queue orchestration for SessionOrchestrator."""

    def __init__(self, context: OrchestrationContext) -> None:
        self._context = context
        self._retry_queue: RetryQueue | None = None
        self._retry_worker_task: asyncio.Task | None = None
        self._retry_pending = False
        self._retry_count = 0
        self._last_retry_status_signature: tuple[str, int, int, str] | None = None
        self._task_loop: asyncio.AbstractEventLoop | None = None

    @property
    def controller(self) -> SessionOrchestrator:
        return self._context.get_controller()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def initialize(self) -> None:
        """Recover persisted retries; defer worker start until the main loop runs."""
        self._retry_queue = get_retry_queue()
        if not self._retry_queue:
            return
        self._recover_crashed_retries()
        self.ensure_worker_started()

    def ensure_worker_started(self) -> None:
        """Start the retry worker on the main event loop when available."""
        if self._retry_queue is None:
            self._retry_queue = get_retry_queue()
        if not self._retry_queue:
            return
        if self._retry_worker_task is not None and not self._retry_worker_task.done():
            return

        loop: asyncio.AbstractEventLoop | None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            from backend.utils.async_helpers.async_utils import get_main_event_loop

            loop = get_main_event_loop()

        if loop is None or not loop.is_running():
            logger.debug(
                'Retry queue enabled but no running event loop; worker for %s deferred',
                self.controller.id,
            )
            return

        async def _worker_wrapper() -> None:
            try:
                await self._retry_worker()
            except Exception as exc:  # pragma: no cover - logged for diagnostics
                logger.exception(
                    'Retry worker crashed for controller %s: %s',
                    self.controller.id,
                    exc,
                )

        from backend.utils.async_helpers.async_utils import create_tracked_task

        self._retry_worker_task = create_tracked_task(
            _worker_wrapper(),
            name=f'app-retry-worker-{self.controller.id}',
        )
        self._task_loop = loop
        logger.debug('Retry worker started for controller %s', self.controller.id)

    def reset_retry_metrics(self) -> None:
        """Reset retry tracking state after successful execution or initialization."""
        self._retry_count = 0
        self._retry_pending = False
        self._last_retry_status_signature = None

    def _recover_crashed_retries(self) -> None:
        """Restore retry tasks persisted to sidecar files from a previous crash.

        Without this call, tasks that were in-flight at crash time are
        silently lost and never re-scheduled.
        """
        if self._retry_queue is None:
            return
        try:
            recovered = self._retry_queue.recover_pending()
            if recovered:
                logger.info(
                    'Recovered %d retry task(s) from crash-sidecar persistence for controller %s',
                    len(recovered),
                    self.controller.id,
                )
                self._retry_pending = True
        except Exception:
            logger.debug(
                'Retry sidecar recovery scan failed for controller %s (non-fatal)',
                self.controller.id,
                exc_info=True,
            )

    def increment_retry_count(self) -> int:
        """Increment retry counter, returning the updated value."""
        self._retry_count += 1
        return self._retry_count

    @property
    def retry_count(self) -> int:
        return self._retry_count

    @property
    def retry_pending(self) -> bool:
        return self._retry_pending

    def _is_retryable_exception(self, exc: Exception) -> bool:
        """Return True if the exception is retryable."""
        from backend.core.errors import LLMNoResponseError
        from backend.inference.exceptions import (
            APIConnectionError,
            APIError,
            InternalServerError,
            RateLimitError,
            ServiceUnavailableError,
            Timeout,
        )

        return isinstance(
            exc,
            (
                APIConnectionError,
                APIError,
                RateLimitError,
                ServiceUnavailableError,
                Timeout,
                InternalServerError,
                # Empty/no-response blips (common with some Gemini configs).
                # The inner Tenacity loop retries immediately + bumps temperature;
                # a backed-off outer retry is a genuinely different attempt and is
                # bounded by the retry queue's max_retries before giving up.
                LLMNoResponseError,
            ),
        )

    def _compute_initial_delay(
        self, exc: Exception, queue: RetryQueue, attempt: int = 0
    ) -> float:
        """Compute initial retry delay with exponential backoff + jitter.

        When the provider supplied a ``Retry-After`` (or equivalent reset
        header) we honor that hint verbatim — clipped by the queue's
        ``max_delay`` so a single bad header cannot stall the worker.
        """
        import random as _random

        from backend.inference.exceptions import RateLimitError, ServiceUnavailableError

        delay = queue.base_delay
        if isinstance(exc, RateLimitError):
            retry_after = getattr(exc, 'retry_after', None)
            if retry_after and retry_after > 0:
                return min(float(retry_after), queue.max_delay)
            # Exponential backoff for rate limits: base * 2^attempt
            delay = queue.base_delay * (2**attempt)
        elif isinstance(exc, ServiceUnavailableError):
            delay = queue.base_delay * (2**attempt)
        else:
            delay = queue.base_delay * (2**attempt)

        # Scale delay by circuit breaker consecutive errors so that
        # repeated failures back off more aggressively.
        cb_service = getattr(self.controller, 'circuit_breaker_service', None)
        cb = getattr(cb_service, 'circuit_breaker', None) if cb_service else None
        if cb is not None and cb.consecutive_errors > 0:
            delay *= 1.0 + min(cb.consecutive_errors, 10) * 0.5

        # Add jitter (50% to 150% of calculated delay)
        jitter = _random.uniform(0.5, 1.5)  # nosec
        delay = delay * jitter

        # Apply max delay cap
        delay = min(delay, queue.max_delay)
        return delay

    @staticmethod
    def _format_retry_delay(delay_seconds: float) -> str:
        rounded = round(float(delay_seconds), 1)
        if rounded.is_integer():
            return f'{int(rounded)}s'
        return f'{rounded:.1f}s'

    def _emit_retry_status(
        self,
        *,
        status_type: str,
        content: str,
        extras: dict[str, Any],
    ) -> None:
        attempt = int(extras.get('attempt') or 0)
        max_attempts = int(extras.get('max_attempts') or 0)
        reason = str(extras.get('reason') or '')
        signature = (status_type, attempt, max_attempts, reason)
        if signature == self._last_retry_status_signature:
            return
        self._last_retry_status_signature = signature

        from backend.ledger import EventSource
        from backend.ledger.observation import StatusObservation

        self.controller.event_stream.add_event(
            StatusObservation(content=content, status_type=status_type, extras=extras),
            EventSource.ENVIRONMENT,
        )

    async def schedule_retry_after_failure(self, exc: Exception) -> bool:
        """Schedule an automatic retry for transient failures."""
        from backend.orchestration.telemetry.tool_telemetry import ToolTelemetry

        queue = self._retry_queue or get_retry_queue()
        if not queue or not self._is_retryable_exception(exc):
            return False

        controller = self.controller
        if self._retry_pending:
            logger.debug('Retry already pending for controller %s', controller.id)
            return True

        if not self._retry_worker_task or self._retry_worker_task.done():
            self._retry_queue = queue
            self.initialize()

        max_retries = max(1, int(getattr(queue, 'max_retries', 3)))
        # Keep retry attempts monotonic across queue-task IDs for the same
        # recovery episode. This prevents repeated "retry 1/N" loops when each
        # resumed step fails quickly and schedules a fresh queue task.
        next_attempt = self.increment_retry_count()
        if next_attempt > max_retries:
            logger.warning(
                'Autonomous recovery exhausted for controller %s (%d/%d)',
                controller.id,
                next_attempt - 1,
                max_retries,
            )
            return False

        metadata: dict[str, Any] = {
            'error': str(exc),
            'retry_reason': type(exc).__name__,
        }
        pending_svc = getattr(
            getattr(controller, 'services', None), 'pending_action', None
        )
        pending = pending_svc.get_primary() if pending_svc is not None else None
        if pending is None:
            pending = getattr(controller, '_pending_action', None)
        if pending is not None:
            metadata['pending_action'] = ToolTelemetry.action_to_dict(pending)
        initial_delay = self._compute_initial_delay(
            exc, queue, attempt=next_attempt - 1
        )

        task = await queue.schedule(
            controller_id=controller.id or '',
            payload={'operation': 'agent_step'},
            reason=type(exc).__name__,
            metadata=metadata,
            initial_delay=initial_delay,
            max_attempts=max_retries,
        )
        self._retry_queue = queue
        self._retry_pending = True

        # Connection errors are out of the agent's control; compensate the iteration
        # budget so recovery overhead doesn't burn into the task runway.
        self._compensate_iterations_for_connection_error(exc)

        controller.state.set_last_error(
            f'{type(exc).__name__}: retry scheduled', source='RetryService'
        )
        self._emit_retry_status(
            status_type='retry_pending',
            content='',
            extras={
                'attempt': next_attempt,
                'max_attempts': task.max_attempts,
                'delay_seconds': initial_delay,
                'reason': type(exc).__name__,
                'rate_limit_kind': getattr(getattr(exc, 'kind', None), 'value', None),
                'retry_after': getattr(exc, 'retry_after', None),
                'provider': getattr(exc, 'llm_provider', None),
            },
        )
        logger.warning(
            'Scheduled retry task %s for controller %s due to %s (delay=%.1fs)',
            task.id,
            controller.id,
            type(exc).__name__,
            initial_delay,
        )
        return True

    async def shutdown(self) -> None:
        """Ensure retry worker stops gracefully."""
        task = self._retry_worker_task
        if not task:
            return

        task.cancel()
        try:
            # Always await the task.  If we're on a different loop, bridge
            # back to the task's loop so it actually unwinds rather than
            # leaking as a cancelled-but-not-awaited zombie.
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = None

            if self._task_loop is not None and current_loop is self._task_loop:
                await task
            elif self._task_loop is not None:
                future = asyncio.run_coroutine_threadsafe(
                    self._await_task(task), self._task_loop
                )
                future.result(timeout=5.0)
            else:
                # No loop to bridge to; best-effort wait
                await task
        except asyncio.CancelledError:  # pragma: no cover - expected cancellation path
            logger.debug(
                'Retry worker cancellation acknowledged for controller %s',
                self.controller.id,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug(
                'Retry worker shutdown ignored error for controller %s: %s',
                self.controller.id,
                exc,
            )
        finally:
            self._retry_worker_task = None
            self._task_loop = None

    @staticmethod
    async def _await_task(task: asyncio.Task[Any]) -> None:
        """Helper to await a task inside run_coroutine_threadsafe."""
        await task

    # ------------------------------------------------------------------ #
    # Internal helpers (mirrors former SessionOrchestrator implementations)
    # ------------------------------------------------------------------ #
    async def _retry_worker(self) -> None:
        """Background worker that processes retry queue tasks."""
        if not self._retry_queue:
            return
        poll_interval = max(0.5, float(self._retry_queue.poll_interval))
        controller = self.controller

        try:
            while not controller._closed:
                try:
                    tasks = await self._fetch_ready_tasks(controller, poll_interval)
                    if not tasks:
                        continue
                    await self._process_tasks(tasks, poll_interval)
                except asyncio.CancelledError:
                    raise
                except Exception as loop_exc:
                    logger.error('Error inside retry worker loop: %s', loop_exc)
                    await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:  # pragma: no cover - cooperative cancellation
            logger.debug('Retry worker cancelled for controller %s', controller.id)
            raise

    async def _fetch_ready_tasks(
        self, controller, poll_interval: float
    ) -> list[RetryTask]:
        queue = self._retry_queue
        if queue is None:
            await asyncio.sleep(poll_interval)
            return []
        try:
            tasks = await queue.fetch_ready(controller.id, limit=1)
        except Exception as exc:
            if self._is_retry_backend_failure(exc):
                logger.warning(
                    'Retry queue backend connection lost for controller %s; will retry: %s',
                    controller.id,
                    exc,
                )
                self._retry_pending = False
                await asyncio.sleep(poll_interval)
                return []
            raise

        if not tasks:
            await asyncio.sleep(poll_interval)
        return tasks

    def _is_retry_backend_failure(self, exc: Exception) -> bool:
        return isinstance(exc, ConnectionError | OSError)

    def _compensate_iterations_for_connection_error(self, exc: Exception) -> None:
        """Add iteration headroom when a network outage triggers a retry.

        Connection errors (APIConnectionError, Timeout) are out of the agent's
        control. Each such event grants 8 extra iterations so recovery tool calls
        don't drain the task budget.  Rate-limit and server errors are intentionally
        excluded — those are provider-side throttling and should not inflate the budget.
        """
        from backend.inference.exceptions import APIConnectionError, Timeout

        if not isinstance(exc, (APIConnectionError, Timeout)):
            return
        try:
            iteration_flag = getattr(self.controller.state, 'iteration_flag', None)
            if iteration_flag is None:
                return
            current_max = getattr(iteration_flag, 'max_value', None)
            if current_max is not None:
                iteration_flag.max_value = current_max + 8
                logger.info(
                    'Connection error (%s): granted 8 extra iterations to controller %s '
                    '(budget now %d)',
                    type(exc).__name__,
                    self.controller.id,
                    iteration_flag.max_value,
                )
        except Exception as budget_exc:  # pragma: no cover - defensive
            logger.debug('Could not compensate iteration budget: %s', budget_exc)

    async def _process_tasks(
        self, tasks: list[RetryTask], poll_interval: float
    ) -> None:
        queue = self._retry_queue
        if queue is None:
            logger.debug('Retry queue no longer available; stopping task processing.')
            return

        for task in tasks:
            try:
                await self._process_retry_task(task)
                await queue.mark_success(task)
                self._retry_pending = False
                self.reset_retry_metrics()
            except Exception as exc:
                if self._is_retry_backend_failure(exc):
                    logger.warning(
                        'Retry queue backend error for task %s on controller %s; will retry: %s',
                        task.id,
                        self.controller.id,
                        exc,
                    )
                    self._retry_pending = False
                    await asyncio.sleep(poll_interval)
                    return
                logger.exception(
                    'Retry task %s failed for controller %s: %s',
                    task.id,
                    self.controller.id,
                    exc,
                )
                await self._handle_task_failure(task, exc)
        await asyncio.sleep(0)

    async def _handle_task_failure(self, task: RetryTask, exc: Exception) -> None:
        queue = self._retry_queue
        if queue is None:
            logger.debug(
                'Retry queue missing; cannot handle failure for task %s', task.id
            )
            self._retry_pending = False
            await self._transition_to_awaiting_user()
            return
        try:
            rescheduled = await queue.mark_failure(task, error_message=str(exc))
            if rescheduled is None:
                self._retry_pending = False
                # All retries exhausted — show the prompt so user can act.
                await self._transition_to_awaiting_user()
        except Exception as backend_exc:
            logger.warning('Retry queue backend error during cleanup: %s', backend_exc)
            self._retry_pending = False
            await self._transition_to_awaiting_user()

    async def _transition_to_awaiting_user(self) -> None:
        """Transition to AWAITING_USER_INPUT after retries are exhausted."""
        from backend.core.schemas import AgentState
        from backend.ledger import EventSource
        from backend.ledger.observation import AgentThinkObservation

        controller = self.controller
        self.reset_retry_metrics()
        controller.event_stream.add_event(
            AgentThinkObservation(
                content='All automatic retries exhausted. Returning to prompt.'
            ),
            EventSource.ENVIRONMENT,
        )
        try:
            await controller.set_agent_state_to(AgentState.AWAITING_USER_INPUT)
        except Exception:
            logger.debug('Failed to transition to AWAITING_USER_INPUT', exc_info=True)

    @staticmethod
    def _retry_resume_reason(task: RetryTask) -> str:
        metadata = getattr(task, 'metadata', None)
        if isinstance(metadata, dict):
            retry_reason = str(metadata.get('retry_reason') or '').strip()
            if retry_reason:
                return retry_reason
        return str(getattr(task, 'reason', '') or 'transient failure')

    @staticmethod
    def _retry_resume_attempt(task: RetryTask) -> int:
        return max(1, int(getattr(task, 'attempts', 0) or 0))

    @staticmethod
    def _retry_resume_limit_exceeded(controller) -> bool:
        state = getattr(controller, 'state', None)
        if state is None:
            return False
        budget_flag = getattr(state, 'budget_flag', None)
        iteration_flag = getattr(state, 'iteration_flag', None)
        return (budget_flag is not None and budget_flag.reached_limit()) or (
            iteration_flag is not None and iteration_flag.reached_limit()
        )

    async def _abort_retry_resume_for_limits(self, controller, task: RetryTask) -> bool:
        if not self._retry_resume_limit_exceeded(controller):
            return False

        logger.warning(
            'Budget/iteration limit already reached on controller %s; '
            'aborting retry task %s and returning to AWAITING_USER_INPUT.',
            controller.id,
            task.id,
        )
        self.reset_retry_metrics()
        await self._transition_to_awaiting_user()
        return True

    def _emit_retry_resume_status(
        self, task: RetryTask, *, retry_reason: str, attempt: int
    ) -> None:
        self._emit_retry_status(
            status_type='retry_resuming',
            content='',
            extras={
                'attempt': attempt,
                'max_attempts': task.max_attempts,
                'reason': retry_reason,
            },
        )

    async def _process_retry_task(self, task: RetryTask) -> None:
        """Process an individual retry queue task."""
        controller = self.controller
        if controller._closed:
            logger.debug(
                'Controller %s closed; ignoring retry task %s', controller.id, task.id
            )
            return

        operation = task.payload.get('operation', 'agent_step')
        if operation == 'agent_step':
            await self._resume_agent_after_retry(task)
            return

        if operation == 'action':
            action_dict = task.payload.get('action')
            if not action_dict:
                logger.warning(
                    'Retry task %s missing action payload; skipping', task.id
                )
                return
            from backend.ledger.serialization.action import action_from_dict

            action = action_from_dict(action_dict)
            controller.log(
                'info',
                f'Replaying action from retry queue: {type(action).__name__}',
                extra={'msg_type': 'RETRY_EXECUTE'},
            )
            process_action = getattr(controller, '_process_action', None)
            if callable(process_action):
                await process_action(action)
            else:
                logger.warning(
                    'Controller %s lacks _process_action; unable to replay action task %s',
                    controller.id,
                    task.id,
                )
            return

        logger.warning(
            "Unknown retry operation '%s' for task %s on controller %s",
            operation,
            task.id,
            controller.id,
        )

    async def _resume_agent_after_retry(self, task: RetryTask) -> None:
        """Resume the agent after a retry task completes."""
        from backend.orchestration.state.state import AgentState

        controller = self.controller
        retry_reason = self._retry_resume_reason(task)
        attempt = max(self._retry_resume_attempt(task), self._retry_count)

        # Guard: if budget or iteration limit is already exceeded, resuming the
        # agent would immediately raise the same RuntimeError in _run_control_flags
        # and loop forever.  Abort the retry and return control to the user.
        if await self._abort_retry_resume_for_limits(controller, task):
            return

        self._emit_retry_resume_status(task, retry_reason=retry_reason, attempt=attempt)

        controller.circuit_breaker_service.record_success()

        if controller.state.agent_state != AgentState.RUNNING:
            await controller.set_agent_state_to(AgentState.RUNNING)
        controller.step()

    async def stop_if_idle(self) -> None:
        """Helper allowing controller to stop worker when shutting down."""
        await self.shutdown()
