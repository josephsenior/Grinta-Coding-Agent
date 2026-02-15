from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from backend.core.logger import FORGE_logger as logger
from backend.core.retry_queue import RetryQueue, RetryTask, get_retry_queue

if TYPE_CHECKING:
    from backend.controller.agent_controller import AgentController
    from backend.controller.services.controller_context import ControllerContext


class RetryService:
    """Owns retry queue orchestration for AgentController."""

    def __init__(self, context: ControllerContext) -> None:
        self._context = context
        self._retry_queue: RetryQueue | None = None
        self._retry_worker_task: asyncio.Task | None = None
        self._retry_pending = False
        self._retry_count = 0
        self._task_loop: asyncio.AbstractEventLoop | None = None

    @property
    def controller(self) -> AgentController:
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
                "Retry queue enabled but no running event loop; worker for %s not started",
                self.controller.id,
            )
            return

        async def _worker_wrapper() -> None:
            try:
                await self._retry_worker()
            except (
                asyncio.CancelledError
            ):  # pragma: no cover - expected cancellation path
                raise
            except Exception as exc:  # pragma: no cover - logged for diagnostics
                logger.exception(
                    "Retry worker crashed for controller %s: %s",
                    self.controller.id,
                    exc,
                )

        self._retry_worker_task = loop.create_task(
            _worker_wrapper(), name=f"forge-retry-worker-{self.controller.id}"
        )
        self._task_loop = loop
        logger.debug("Retry worker started for controller %s", self.controller.id)

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

    async def schedule_retry_after_failure(self, exc: Exception) -> bool:
        """Schedule an automatic retry for transient failures."""
        from backend.controller.tool_telemetry import ToolTelemetry
        from backend.events import EventSource
        from backend.events.observation import AgentThinkObservation
        from backend.llm.exceptions import (
            APIConnectionError,
            APIError,
            InternalServerError,
            RateLimitError,
            ServiceUnavailableError,
            Timeout,
        )

        queue = self._retry_queue or get_retry_queue()
        if not queue:
            return False

        controller = self.controller

        retryable_types = (
            APIConnectionError,
            APIError,
            RateLimitError,
            ServiceUnavailableError,
            Timeout,
            InternalServerError,
        )
        if not isinstance(exc, retryable_types):
            return False

        if self._retry_pending:
            logger.debug("Retry already pending for controller %s", controller.id)
            return True

        if not self._retry_worker_task or self._retry_worker_task.done():
            self._retry_queue = queue
            self.initialize()

        metadata: dict[str, Any] = {"error": str(exc)}
        pending_action = controller._pending_action
        if pending_action is not None:
            metadata["pending_action"] = ToolTelemetry.action_to_dict(pending_action)

        initial_delay = queue.base_delay
        if isinstance(exc, RateLimitError):
            initial_delay = max(initial_delay, queue.base_delay * 2)
        circuit_breaker = getattr(
            controller.circuit_breaker_service, "circuit_breaker", None
        )
        if circuit_breaker:
            consecutive = max(1, getattr(circuit_breaker, "consecutive_errors", 1))
            initial_delay = min(queue.max_delay, initial_delay * consecutive)

        task = await queue.schedule(
            controller_id=controller.id or "",
            payload={"operation": "agent_step"},
            reason=type(exc).__name__,
            metadata=metadata,
            initial_delay=initial_delay,
        )
        self._retry_queue = queue
        self._retry_pending = True

        human_message = (
            f"⚠️ Encountered {type(exc).__name__}. Automatic retry scheduled in "
            f"{int(initial_delay)}s (max {task.max_attempts} attempts)."
        )
        controller.state.set_last_error(
            f"{type(exc).__name__}: retry scheduled", source="RetryService"
        )
        controller.event_stream.add_event(
            AgentThinkObservation(content=human_message),
            EventSource.ENVIRONMENT,
        )
        logger.warning(
            "Scheduled retry task %s for controller %s due to %s (delay=%.1fs)",
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
                    "Retry worker for controller %s cancelled without await due to loop mismatch",
                    self.controller.id,
                )
        except asyncio.CancelledError:  # pragma: no cover - expected cancellation path
            logger.debug(
                "Retry worker cancellation acknowledged for controller %s",
                self.controller.id,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug(
                "Retry worker shutdown ignored error for controller %s: %s",
                self.controller.id,
                exc,
            )
        finally:
            self._retry_worker_task = None
            self._task_loop = None

    # ------------------------------------------------------------------ #
    # Internal helpers (mirrors former AgentController implementations)
    # ------------------------------------------------------------------ #
    async def _retry_worker(self) -> None:
        """Background worker that processes retry queue tasks."""
        if not self._retry_queue:
            return
        poll_interval = max(0.5, float(self._retry_queue.poll_interval))
        controller = self.controller

        try:
            while not controller._closed:
                tasks = await self._fetch_ready_tasks(controller, poll_interval)
                if not tasks:
                    continue
                await self._process_tasks(tasks)
        except asyncio.CancelledError:  # pragma: no cover - cooperative cancellation
            logger.debug("Retry worker cancelled for controller %s", controller.id)
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
                    "Retry queue backend connection lost for controller %s; worker exiting: %s",
                    controller.id,
                    exc,
                )
                raise asyncio.CancelledError
            raise

        if not tasks:
            await asyncio.sleep(poll_interval)
        return tasks

    def _is_retry_backend_failure(self, exc: Exception) -> bool:
        try:
            import redis.exceptions

            return isinstance(
                exc, (redis.exceptions.ConnectionError, ConnectionError, OSError)
            )
        except ImportError:
            return isinstance(exc, (ConnectionError, OSError))

    async def _process_tasks(self, tasks: list[RetryTask]) -> None:
        queue = self._retry_queue
        if queue is None:
            logger.debug("Retry queue no longer available; stopping task processing.")
            return

        for task in tasks:
            try:
                await self._process_retry_task(task)
                await queue.mark_success(task)
                self._retry_pending = False
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception(
                    "Retry task %s failed for controller %s: %s",
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
                "Retry queue missing; cannot handle failure for task %s", task.id
            )
            self._retry_pending = False
            return
        try:
            rescheduled = await queue.mark_failure(task, error_message=str(exc))
            if rescheduled is None:
                await queue.dead_letter(task)
                self._retry_pending = False
        except Exception as backend_exc:
            logger.warning("Retry queue backend error during cleanup: %s", backend_exc)
            self._retry_pending = False

    async def _process_retry_task(self, task: RetryTask) -> None:
        """Process an individual retry queue task."""
        controller = self.controller
        if controller._closed:
            logger.debug(
                "Controller %s closed; ignoring retry task %s", controller.id, task.id
            )
            return

        operation = task.payload.get("operation", "agent_step")
        if operation == "agent_step":
            await self._resume_agent_after_retry(task)
            return

        if operation == "action":
            action_dict = task.payload.get("action")
            if not action_dict:
                logger.warning(
                    "Retry task %s missing action payload; skipping", task.id
                )
                return
            from backend.events.serialization.action import action_from_dict

            action = action_from_dict(action_dict)
            controller.log(
                "info",
                f"Replaying action from retry queue: {type(action).__name__}",
                extra={"msg_type": "RETRY_EXECUTE"},
            )
            process_action = getattr(controller, "_process_action", None)
            if callable(process_action):
                await process_action(action)
            else:
                logger.warning(
                    "Controller %s lacks _process_action; unable to replay action task %s",
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
        from backend.controller.state.state import AgentState
        from backend.events import EventSource
        from backend.events.observation import AgentThinkObservation

        controller = self.controller
        message = f"🔁 Retrying after {task.reason}. Attempt {task.attempts}/{task.max_attempts}."
        controller.event_stream.add_event(
            AgentThinkObservation(content=message),
            EventSource.ENVIRONMENT,
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
