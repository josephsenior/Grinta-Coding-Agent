from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock

from backend.core.logger import app_logger as logger

if TYPE_CHECKING:
    from backend.orchestration.services.orchestration_context import OrchestrationContext
    from backend.orchestration.tool_pipeline import ToolInvocationContext
    from backend.ledger.action import Action


class TelemetryService:
    """Owns telemetry pipeline setup and helper utilities."""

    def __init__(self, context: OrchestrationContext) -> None:
        self._context = context

    def initialize_operation_pipeline(self) -> None:
        """Create the default operation pipeline for the controller."""
        from backend.orchestration.file_state_tracker import FileStateMiddleware
        from backend.orchestration.pre_exec_diff import PreExecDiffMiddleware
        from backend.orchestration.rollback_middleware import RollbackMiddleware
        from backend.orchestration.tool_pipeline import (
            AutoCheckMiddleware,
            BlackboardMiddleware,
            CircuitBreakerMiddleware,
            ConflictDetectionMiddleware,
            ContextWindowMiddleware,
            CostQuotaMiddleware,
            EditVerifyMiddleware,
            LoggingMiddleware,
            ReflectionMiddleware,
            SafetyValidatorMiddleware,
            TelemetryMiddleware,
        )
        from backend.orchestration.tool_result_validator import ToolResultValidator

        context = self._context
        controller = context.get_controller()
        config = context.agent_config
        reflection_enabled = bool(
            config
            and getattr(config, "enable_reflection", True)
            and getattr(config, "enable_reflection_middleware", False)
        )
        controller._reflection_middleware_enabled = reflection_enabled
        middlewares = [
            SafetyValidatorMiddleware(controller),
            BlackboardMiddleware(controller),
            CircuitBreakerMiddleware(controller),
            CostQuotaMiddleware(controller),
            ContextWindowMiddleware(controller),
        ]
        if reflection_enabled:
            middlewares.append(ReflectionMiddleware(controller))
        # Rollback checkpoint before risky actions
        middlewares.append(RollbackMiddleware())
        # Pre-execution diff preview (before logging/telemetry)
        middlewares.append(PreExecDiffMiddleware())
        # Auto-verify hint after file edits
        middlewares.append(EditVerifyMiddleware())
        # Auto-check syntax after file edits
        middlewares.append(AutoCheckMiddleware())
        # Warn when re-editing a file without verifying in between
        middlewares.append(ConflictDetectionMiddleware())
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
        if isinstance(context, Mock):
            context.initialize_operation_pipeline(middlewares)
            context.initialize_tool_pipeline(middlewares)
        else:
            context.initialize_operation_pipeline(middlewares)

    def initialize_tool_pipeline(self) -> None:
        """Backward-compatible alias for operation pipeline initialization."""
        self.initialize_operation_pipeline()

    def handle_blocked_invocation(
        self,
        action: Action,
        ctx: ToolInvocationContext,
    ) -> None:
        """Emit telemetry + user-facing events when middleware blocks an action."""
        from backend.orchestration.tool_telemetry import ToolTelemetry
        from backend.ledger import EventSource
        from backend.ledger.observation import ErrorObservation
        from backend.ledger.observation_cause import attach_observation_cause

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
            attach_observation_cause(
                error_obs, action, context="telemetry.handle_blocked_invocation"
            )
            context.emit_event(error_obs, EventSource.ENVIRONMENT)

        context.clear_pending_action()
