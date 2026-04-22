"""Circuit breaker middleware for tool invocations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.orchestration.agent_circuit_breaker import (
    STR_REPLACE_EDITOR_TOOL_NAME,
    classify_str_replace_editor_error_bucket,
)
from backend.orchestration.tool_pipeline import ToolInvocationMiddleware

if TYPE_CHECKING:
    from backend.ledger.observation import Observation
    from backend.orchestration.session_orchestrator import SessionOrchestrator
    from backend.orchestration.tool_pipeline import ToolInvocationContext

# Observation types that represent genuine progress and should reduce
# stuck-detection pressure when observed successfully.
_PROGRESS_OBSERVATION_TYPES: tuple[str, ...] = (
    'FileEditObservation',
    'FileWriteObservation',
    'AgentDelegateObservation',
    'LspQueryObservation',
    # Updating the structured task plan counts as real progress; without
    # this, long multi-step tasks spent in task_tracker(update) would trip
    # stuck detection and force the model to call signal_progress defensively.
    'TaskTrackingObservation',
)

# Tool fallback map — when a tool fails, suggest the next alternative so the
# model can pivot in the same turn instead of stopping to explain.
_TOOL_FALLBACK_MAP: dict[str, list[str]] = {
    'ast_code_editor': [
        'str_replace_editor',
    ],
    'str_replace_editor': [],
    'search_code': ['lsp_query'],
    'lsp_query': ['search_code'],
}


class CircuitBreakerMiddleware(ToolInvocationMiddleware):
    """Records circuit breaker telemetry across execute/observe stages."""

    def __init__(self, controller: SessionOrchestrator) -> None:
        self.controller = controller

    async def execute(self, ctx: ToolInvocationContext) -> None:
        service = getattr(self.controller, 'circuit_breaker_service', None)
        if service:
            security_risk = getattr(ctx.action, 'security_risk', None)
            service.record_high_risk_action(security_risk)

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        service = getattr(self.controller, 'circuit_breaker_service', None)
        if not service or observation is None:
            return
        from backend.ledger.observation import ErrorObservation

        # Extract tool name from the action's metadata for per-tool tracking
        tool_name = ''
        tcm = getattr(ctx.action, 'tool_call_metadata', None)
        if tcm is not None:
            tool_name = getattr(tcm, 'function_name', '') or ''

        if isinstance(observation, ErrorObservation):
            base_content = observation.content or ''
            effective_tool = tool_name
            if tool_name == STR_REPLACE_EDITOR_TOOL_NAME:
                effective_tool = classify_str_replace_editor_error_bucket(base_content)
            # Inject fallback hint so the model knows which tool to try next
            if tool_name and tool_name in _TOOL_FALLBACK_MAP:
                fallbacks = _TOOL_FALLBACK_MAP[tool_name]
                hint = f'\n\n[TOOL_FALLBACK] `{tool_name}` failed. Try: {", ".join(f"`{t}`" for t in fallbacks)} instead — pivot immediately.'
                observation.content = base_content + hint
            service.record_error(
                RuntimeError(observation.content), tool_name=effective_tool
            )
        else:
            service.record_success(tool_name=tool_name)
            # Meaningful progress actions reduce stuck-detection pressure
            obs_type = type(observation).__name__
            if obs_type in _PROGRESS_OBSERVATION_TYPES:
                service.record_progress_signal(obs_type)
