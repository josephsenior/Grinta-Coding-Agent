"""_SessionOrchestratorLifecycleMixin mixin for SessionOrchestrator.

Pure code motion: extracted from
``backend/orchestration/session_orchestrator.py`` to break the file past the
40 KB cap. Methods here are bound to ``_SessionOrchestratorLifecycleMixin`` and mixed into
``SessionOrchestrator`` via its MRO.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from backend.core.logging.logger import app_logger as logger
from backend.core.schemas import AgentState
from backend.ledger import EventSource
from backend.ledger.action import (
    Action,
)
from backend.ledger.observation import (
    ErrorObservation,
)
from backend.ledger.observation_cause import attach_observation_cause
from backend.orchestration.tool_pipeline import ToolInvocationContext

TRAFFIC_CONTROL_REMINDER = (
    "Please click on resume button if you'd like to continue, or start a new task."
)
ERROR_ACTION_NOT_EXECUTED_STOPPED_ID = 'AGENT_ERROR$ERROR_ACTION_NOT_EXECUTED_STOPPED'
ERROR_ACTION_NOT_EXECUTED_ERROR_ID = 'AGENT_ERROR$ERROR_ACTION_NOT_EXECUTED_ERROR'
ERROR_ACTION_NOT_EXECUTED_STOPPED = 'Run cancelled (Stop or Ctrl+C) before this tool finished — the action was not executed.'
ERROR_ACTION_NOT_EXECUTED_ERROR = (
    'Runtime error or restart prevented this action from completing (unlike cancelling with '
    'Stop or Ctrl+C). The execution environment may have crashed or been recycled. '
    'Any previously established system state, dependencies, or environment variables '
    'may have been lost. Consider using /resume to restore a crashed session.'
)

PARALLEL_TOOL_BATCH_RETRIES = 1
PARALLEL_TOOL_BATCH_BACKOFF_SECONDS = 0.25


def _mark_retry_serial_after_parallel_failure(action: Action) -> None:
    cast(Any, action)._retry_serial_after_parallel_failure = True


def _invoke_zero_arg_callback(callback: Callable[[], object]) -> object:
    return callback()


if TYPE_CHECKING:
    from backend.core.enums import AgentState
    from backend.ledger.action import Action
    from backend.ledger.event import EventSource
    from backend.ledger.observation import ErrorObservation
    from backend.orchestration.tool_pipeline import ToolInvocationContext


if TYPE_CHECKING:
    from backend.orchestration.session_orchestrator_accessors import (
        SessionOrchestratorAccessorsMixin,
    )
else:

    class SessionOrchestratorAccessorsMixin:
        pass


class _SessionOrchestratorLifecycleMixin(SessionOrchestratorAccessorsMixin):
    """Mixin: pipeline init, phase boundary checkpoint, blocked invocation, stop."""

    def _initialize_operation_pipeline(self) -> None:
        """Build the default tool pipeline directly on the controller.

        Middleware are ordered by responsibility. Pipeline runs execute() then observe():

        1. SafetyValidatorMiddleware - blocks dangerous actions (file deletions outside workspace, etc.)

        2. BlackboardMiddleware - shares state between concurrent tool invocations

        3. CircuitBreakerMiddleware - prevents repeated tool failures from blocking progress

        4. ProgressPolicyMiddleware - enforces progress checks (e.g., max iterations)

        5. CostQuotaMiddleware - tracks and limits LLM spend

        6. ContextWindowMiddleware - prevents context window overflow

        7. RollbackMiddleware - creates checkpoints before risky operations for recovery

        8. DestructiveCommandMiddleware - high-priority checkpoints before shell destructive ops

        9. PreExecDiffMiddleware - computes diff before action executes for user preview

        10. AutoCheckMiddleware - runs syntax auto-checks after tool execution

        11. PostEditDiagnosticsMiddleware - runs bounded LSP diagnostics after edits

        12. FileStateMiddleware - tracks file modifications for state management

        13. LoggingMiddleware, TelemetryMiddleware - observability (always last in execute)

        14. ToolResultValidator - validates results after all observe() hooks complete

        """
        from backend.orchestration.file_edits.file_state_tracker import (
            FileStateMiddleware,
        )
        from backend.orchestration.file_edits.pre_exec_diff import PreExecDiffMiddleware
        from backend.orchestration.middleware.destructive_command import (
            DestructiveCommandMiddleware,
        )
        from backend.orchestration.middleware.rollback_middleware import (
            RollbackMiddleware,
        )
        from backend.orchestration.middleware.symbol_index_invalidation import (
            SymbolIndexInvalidationMiddleware,
        )
        from backend.orchestration.middleware.tool_result_validator import (
            ToolResultValidator,
        )
        from backend.orchestration.tool_pipeline import (
            AutoCheckMiddleware,
            BlackboardMiddleware,
            CircuitBreakerMiddleware,
            ContextWindowMiddleware,
            CostQuotaMiddleware,
            LoggingMiddleware,
            PostEditDiagnosticsMiddleware,
            ProgressPolicyMiddleware,
            SafetyValidatorMiddleware,
            TelemetryMiddleware,
        )

        middlewares = [
            SafetyValidatorMiddleware(self),
            BlackboardMiddleware(self),
            CircuitBreakerMiddleware(self),
            ProgressPolicyMiddleware(),
            CostQuotaMiddleware(self),
            ContextWindowMiddleware(self),
            RollbackMiddleware(),
            DestructiveCommandMiddleware(),
            PreExecDiffMiddleware(),
            AutoCheckMiddleware(),
            PostEditDiagnosticsMiddleware(),
            SymbolIndexInvalidationMiddleware(),
        ]

        file_state_mw = FileStateMiddleware()

        middlewares.append(file_state_mw)

        self._file_state_tracker = file_state_mw.tracker

        middlewares.extend([LoggingMiddleware(self), TelemetryMiddleware(self)])

        middlewares.append(ToolResultValidator())

        self.services.context.initialize_operation_pipeline(middlewares)

        # Stash the rollback middleware reference for phase-boundary checkpoints.

        self._rollback_middleware = next(
            (m for m in middlewares if isinstance(m, RollbackMiddleware)),
            None,
        )

    def _create_phase_boundary_checkpoint(self, label: str) -> None:
        """Create a ``phase_boundary`` checkpoint at lifecycle transitions.

        Reuses the existing ``RollbackMiddleware``'s ``RollbackManager`` so we

        don't snapshot through a second instance (which would race on the

        on-disk ``checkpoints.json`` file).  Failures are non-fatal — a missed

        phase-boundary checkpoint must never block a lifecycle transition —

        but they are surfaced at WARNING level because rollback consumers

        depend on these checkpoints existing for recovery.

        """
        mw = getattr(self, '_rollback_middleware', None)

        if mw is None:
            logger.info(
                'Phase-boundary checkpoint at %s skipped: no RollbackMiddleware '
                'is registered. Rollback to this transition will not be possible.',
                label,
            )

            return

        try:
            from backend.orchestration.tool_pipeline import ToolInvocationContext

            ctx = ToolInvocationContext(controller=self, action=None, state=None)  # type: ignore[arg-type]

            manager = mw._get_manager(ctx)  # type: ignore[attr-defined]

            if manager is None:
                logger.info(
                    'Phase-boundary checkpoint at %s skipped: RollbackManager '
                    'unavailable. Rollback to this transition will not be possible.',
                    label,
                )

                return

            cid = manager.create_checkpoint(
                description=f'phase boundary: {label}',
                checkpoint_type='phase_boundary',
                metadata={
                    'phase_label': label,
                    'session_id': getattr(self, 'id', 'unknown'),
                },
                use_git=False,
            )

            logger.debug('Phase-boundary checkpoint %s created at %s', cid, label)

        except Exception:
            logger.warning(
                'Phase-boundary checkpoint creation failed at %s — rollback to '
                'this transition will not be possible.',
                label,
                exc_info=True,
            )

    def handle_blocked_invocation(
        self,
        action: Action,
        ctx: ToolInvocationContext,
    ) -> None:
        """Clean up and emit an error observation when middleware blocks a tool.

        Agent-guidance blocks (``block(..., agent_only=True)``) still reach the

        model but are not rendered in the CLI transcript.

        """
        from backend.orchestration.telemetry.tool_telemetry import ToolTelemetry

        self._cleanup_action_context(ctx, action=action)

        try:
            ToolTelemetry.get_instance().on_blocked(ctx, reason=ctx.block_reason)

        except Exception:
            logger.debug('Failed to record telemetry for blocked action', exc_info=True)

        if not ctx.metadata.get('handled'):
            error_content = ctx.block_reason or 'Action blocked by middleware pipeline.'

            error_obs = ErrorObservation(
                content=error_content,
                error_id='TOOL_PIPELINE_BLOCKED',
                agent_only=bool(ctx.metadata.get('block_agent_only')),
            )

            attach_observation_cause(
                error_obs,
                action,
                context='session_orchestrator.handle_blocked_invocation',
            )

            self.event_stream.add_event(error_obs, EventSource.ENVIRONMENT)

        self.services.pending_action.clear_for_action(action)

    async def stop(self) -> None:
        """Stop the agent, best-effort kill runtime processes, and clear pending actions."""
        logger.info('Stopping agent...')

        self._step_request_count = 0

        # Signal the executor to stop streaming immediately.

        agent = getattr(self, 'agent', None)

        if agent is not None:
            executor = getattr(agent, 'executor', None)

            if executor is not None:
                cancel_fn = getattr(executor, 'cancel_step', None)

                if cancel_fn is not None:
                    cancel_fn()

        current_task = asyncio.current_task()

        if (
            self._step_task is not None
            and not self._step_task.done()
            and self._step_task is not current_task
        ):
            self._step_task.cancel()

            with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                await asyncio.wait_for(self._step_task, timeout=5.0)

        runtime = getattr(self, 'runtime', None)

        hard_kill = getattr(runtime, 'hard_kill', None)

        if callable(hard_kill):
            try:
                hard_kill_result = _invoke_zero_arg_callback(
                    cast(Callable[[], object], hard_kill)
                )

                if inspect.isawaitable(hard_kill_result):
                    await hard_kill_result

            except Exception:
                logger.warning('Runtime hard_kill failed during stop()', exc_info=True)

        # 2. Update state to STOPPED

        await self.set_agent_state_to(AgentState.STOPPED)

        # 3. Ensure any pending actions are cleared or marked as cancelled?

        pending_service = getattr(
            getattr(self, 'services', None), 'pending_action', None
        )
        if pending_service is not None:
            pending_service.clear_all()

    async def _ensure_runtime_connected(self) -> None:
        """Restore execution backend if disconnected (e.g. after hard_kill/interrupt)."""
        runtime = getattr(self, 'runtime', None)

        if runtime is None:
            return

        # Check if already initialized to avoid redundant connect calls.

        if hasattr(runtime, 'runtime_initialized'):
            try:
                if runtime.runtime_initialized:
                    return

            except Exception:
                logger.debug('runtime_initialized check failed', exc_info=True)

        connect_fn = getattr(runtime, 'connect', None)

        if callable(connect_fn):
            logger.info('Restoring runtime connection...')

            await connect_fn()
