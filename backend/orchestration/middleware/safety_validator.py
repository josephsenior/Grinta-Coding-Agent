"""Safety validator middleware for tool invocations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.orchestration.tool_pipeline import ToolInvocationMiddleware

if TYPE_CHECKING:
    from backend.orchestration.session_orchestrator import SessionOrchestrator
    from backend.orchestration.tool_pipeline import ToolInvocationContext


class SafetyValidatorMiddleware(ToolInvocationMiddleware):
    """Runs the optional safety validator during the verify stage."""

    def __init__(self, controller: SessionOrchestrator) -> None:
        self.controller = controller

    async def execute(self, ctx: ToolInvocationContext) -> None:
        if not ctx.action.runnable:
            return
        validator = getattr(self.controller, 'safety_validator', None)
        if not validator:
            return

        from backend.ledger.event import EventSource
        from backend.ledger.observation import ErrorObservation
        from backend.ledger.observation_cause import attach_observation_cause
        from backend.orchestration.safety_validator import ExecutionContext

        context = ExecutionContext(
            session_id=self.controller.id or '',
            iteration=self.controller.state.iteration_flag.current_value,
            agent_state=self.controller.state.agent_state.value,
            recent_errors=[self.controller.state.last_error]
            if self.controller.state.last_error
            else [],
            is_autonomous=bool(
                getattr(self.controller.autonomy_controller, 'autonomy_level', '')
                == 'full'
            ),
        )

        validation = await validator.validate(ctx.action, context)
        # Store audit_id so downstream middleware can update the entry
        if validation.audit_id:
            ctx.metadata['audit_id'] = validation.audit_id
        if validation.allowed:
            return

        # Block execution and notify stream.
        ctx.block('safety_validator_blocked')
        ctx.metadata['handled'] = True
        error_obs = ErrorObservation(
            content=f'ACTION BLOCKED FOR SAFETY:\n{validation.blocked_reason}',
            error_id='SAFETY_VALIDATOR_BLOCKED',
        )
        attach_observation_cause(
            error_obs, ctx.action, context='safety_validator.blocked'
        )
        self.controller.event_stream.add_event(error_obs, EventSource.ENVIRONMENT)
        self.controller._pending_action = None
