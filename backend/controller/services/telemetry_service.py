from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.logger import FORGE_logger as logger

if TYPE_CHECKING:
    from backend.controller.services.controller_context import ControllerContext
    from backend.controller.tool_pipeline import ToolInvocationContext
    from backend.events.action import Action


class TelemetryService:
    """Owns telemetry pipeline setup and helper utilities."""

    def __init__(self, context: ControllerContext) -> None:
        self._context = context

    def initialize_tool_pipeline(self) -> None:
        """Create the default tool invocation pipeline for the controller."""
        from backend.controller.file_state_tracker import FileStateMiddleware
        from backend.controller.idempotency import IdempotencyMiddleware
        from backend.controller.pre_exec_diff import PreExecDiffMiddleware
        from backend.controller.rollback_middleware import RollbackMiddleware
        from backend.controller.tool_pipeline import (
            CircuitBreakerMiddleware,
            ConflictDetectionMiddleware,
            CostQuotaMiddleware,
            EditVerifyMiddleware,
            ErrorPatternMiddleware,
            LoggingMiddleware,
            PlanningMiddleware,
            ReflectionMiddleware,
            SafetyValidatorMiddleware,
            TelemetryMiddleware,
        )
        from backend.controller.tool_result_validator import ToolResultValidator

        context = self._context
        controller = context.get_controller()
        config = context.agent_config
        middlewares = [
            SafetyValidatorMiddleware(controller),
            IdempotencyMiddleware(),
            CircuitBreakerMiddleware(controller),
            CostQuotaMiddleware(controller),
        ]
        if config and getattr(config, "enable_planning_middleware", False):
            middlewares.append(PlanningMiddleware(controller))
        if config and getattr(config, "enable_reflection_middleware", False):
            middlewares.append(ReflectionMiddleware(controller))
        # Rollback checkpoint before risky actions
        middlewares.append(RollbackMiddleware())
        # Pre-execution diff preview (before logging/telemetry)
        middlewares.append(PreExecDiffMiddleware())
        # Auto-verify hint after file edits
        middlewares.append(EditVerifyMiddleware())
        # Warn when re-editing a file without verifying in between
        middlewares.append(ConflictDetectionMiddleware())
        # Auto-query error_patterns DB when errors arrive
        middlewares.append(ErrorPatternMiddleware())
        # File state tracking (records files read/modified/created)
        file_state_mw = FileStateMiddleware()
        middlewares.append(file_state_mw)
        # Store tracker on controller for context injection by planner
        controller._file_state_tracker = file_state_mw.tracker
        middlewares.extend(
            [LoggingMiddleware(controller), TelemetryMiddleware(controller)]
        )
        # Result validation runs in the observe stage (after execution)
        middlewares.append(ToolResultValidator())
        context.initialize_tool_pipeline(middlewares)

    def handle_blocked_invocation(
        self,
        action: Action,
        ctx: ToolInvocationContext,
    ) -> None:
        """Emit telemetry + user-facing events when middleware blocks an action."""
        from backend.controller.tool_telemetry import ToolTelemetry
        from backend.events import EventSource
        from backend.events.observation import ErrorObservation

        context = self._context
        context.get_controller()
        context.cleanup_action_context(ctx, action=action)

        try:
            ToolTelemetry.get_instance().on_blocked(ctx, reason=ctx.block_reason)
        except Exception:  # pragma: no cover - telemetry must never break execution
            logger.debug("Failed to record telemetry for blocked action", exc_info=True)

        if not ctx.metadata.get("handled"):
            error_content = ctx.block_reason or "Action blocked by middleware pipeline."
            error_obs = ErrorObservation(
                content=error_content,
                error_id="TOOL_PIPELINE_BLOCKED",
            )
            error_obs.cause = getattr(action, "id", None)
            context.emit_event(error_obs, EventSource.ENVIRONMENT)

        context.clear_pending_action()
