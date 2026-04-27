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
        self._task_loop: asyncio.AbstractEventLoop | None = None

    @property
    def controller(self) -> SessionOrchestrator:
        return self._context.get_controller()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def initialize(self) -> None:
        """Start background retry worker if retry queue is enabled."""
        self._retry_queue = get_retry_queue()
        if not self._retry_queue:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                'Retry queue enabled but no running event loop; worker for %s not started',
                self.controller.id,
            )
            return

        async def _worker_wrapper() -> None:
            try:
                await self._retry_worker()
            except Exception as exc:  # pragma: no cover - logged for diagnostics
                # CancelledError propagates; only log/handle Exception
                logger.exception(
                    'Retry worker crashed for controller %s: %s',
                    self.controller.id,
                    exc,
                )

        self._retry_worker_task = loop.create_task(
            _worker_wrapper(), name=f'app-retry-worker-{self.controller.id}'
        )
        self._task_loop = loop
        logger.debug('Retry worker started for controller %s', self.controller.id)

    def reset_retry_metrics(self) -> None:
        """Reset retry tracking state after successful execution or initialization."""
        self._retry_count = 0
        self._retry_pending = False

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
            ),
        )

    def _compute_initial_delay(self, exc: Exception, queue: RetryQueue) -> float:
        """Compute initial retry delay, accounting for RateLimitError and circuit breaker."""
        from backend.inference.exceptions import RateLimitError

        delay = queue.base_delay
        if isinstance(exc, RateLimitError):
            delay = max(delay, queue.base_delay * 2)
        circuit_breaker = getattr(
            self.controller.circuit_breaker_service, 'circuit_breaker', None
        )
        if circuit_breaker:
            consecutive = max(1, getattr(circuit_breaker, 'consecutive_errors', 1))
            delay = min(queue.max_delay, delay * consecutive)
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
        from backend.ledger import EventSource
        from backend.ledger.observation import StatusObservation

        self.controller.event_stream.add_event(
            StatusObservation(content=content, status_type=status_type, extras=extras),
            EventSource.ENVIRONMENT,
        )

    async def schedule_retry_after_failure(self, exc: Exception) -> bool:
        """Schedule an automatic retry for transient failures."""
        from backend.orchestration.tool_telemetry import ToolTelemetry

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

        metadata: dict[str, Any] = {
            'error': str(exc),
            'retry_reason': type(exc).__name__,
        }
        if controller._pending_action is not None:
            metadata['pending_action'] = ToolTelemetry.action_to_dict(
                controller._pending_action
            )
        initial_delay = self._compute_initial_delay(exc, queue)

        task = await queue.schedule(
            controller_id=controller.id or '',
            payload={'operation': 'agent_step'},
            reason=type(exc).__name__,
            metadata=metadata,
            initial_delay=initial_delay,
        )
        self._retry_queue = queue
        self._retry_pending = True

        # Connection errors are out of the agent's control; compensate the iteration
        # budget so recovery overhead doesn't burn into the task runway.
        self._compensate_iterations_for_connection_error(exc)

        next_attempt = max(1, int(getattr(task, 'attempts', 0) or 0) + 1)
        human_message = (
            'Waiting on autonomous recovery: retry '
            f'{next_attempt}/{task.max_attempts} in '
            f'{self._format_retry_delay(initial_delay)} after {type(exc).__name__}.'
        )
        controller.state.set_last_error(
            f'{type(exc).__name__}: retry scheduled', source='RetryService'
        )
        self._emit_retry_status(
            status_type='retry_pending',
            content=human_message,
            extras={
                'attempt': next_attempt,
                'max_attempts': task.max_attempts,
                'delay_seconds': initial_delay,
                'reason': type(exc).__name__,
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
            # If we're on the same loop the task was created on, await it
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = None

            if self._task_loop is not None and current_loop is self._task_loop:
                await task
            else:
                # Different or no running loop; rely on cancellation without awaiting
                logger.debug(
                    'Retry worker for controller %s cancelled without await due to loop mismatch',
                    self.controller.id,
                )
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
                    await self._process_tasks(tasks)
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
                    'Retry queue backend connection lost for controller %s; worker exiting: %s',
                    controller.id,
                    exc,
                )
                raise asyncio.CancelledError from exc
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

    async def _process_tasks(self, tasks: list[RetryTask]) -> None:
        queue = self._retry_queue
        if queue is None:
            logger.debug('Retry queue no longer available; stopping task processing.')
            return

        for task in tasks:
            try:
                await self._process_retry_task(task)
                await queue.mark_success(task)
                self._retry_pending = False
            except Exception as exc:
                # CancelledError propagates; only handle Exception
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
        metadata = getattr(task, 'metadata', None)
        retry_reason = ''
        if isinstance(metadata, dict):
            retry_reason = str(metadata.get('retry_reason') or '').strip()
        if not retry_reason:
            retry_reason = str(getattr(task, 'reason', '') or 'transient failure')
        attempt = max(1, int(getattr(task, 'attempts', 0) or 0))

        # Guard: if budget or iteration limit is already exceeded, resuming the
        # agent would immediately raise the same RuntimeError in _run_control_flags
        # and loop forever.  Abort the retry and return control to the user.
        state = getattr(controller, 'state', None)
        if state is not None:
            budget_flag = getattr(state, 'budget_flag', None)
            iteration_flag = getattr(state, 'iteration_flag', None)
            limit_exceeded = (
                budget_flag is not None and budget_flag.reached_limit()
            ) or (
                iteration_flag is not None and iteration_flag.reached_limit()
            )
            if limit_exceeded:
                logger.warning(
                    'Budget/iteration limit already reached on controller %s; '
                    'aborting retry task %s and returning to AWAITING_USER_INPUT.',
                    controller.id,
                    task.id,
                )
                self._retry_pending = False
                self._retry_count = 0
                await self._transition_to_awaiting_user()
                return

        message = (
            f'Autonomous recovery attempt {attempt}/{task.max_attempts} '
            f'starting after {retry_reason}.'
        )
        self._emit_retry_status(
            status_type='retry_resuming',
            content=message,
            extras={
                'attempt': attempt,
                'max_attempts': task.max_attempts,
                'reason': retry_reason,
            },
        )

        controller.circuit_breaker_service.record_success()

        if controller.state.agent_state != AgentState.RUNNING:
            await controller.set_agent_state_to(AgentState.RUNNING)
        self._retry_pending = False
        self._retry_count = 0
        controller.step()

    async def stop_if_idle(self) -> None:
        """Helper allowing controller to stop worker when shutting down."""
        await self.shutdown()
