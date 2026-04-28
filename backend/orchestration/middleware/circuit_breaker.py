"""Circuit breaker middleware for tool invocations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.orchestration.agent_circuit_breaker import (
    TEXT_EDITOR_TOOL_NAME,
    classify_text_editor_error_bucket,
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
    # Updating the structured task plan counts as real progress so long
    # multi-step tasks do not trip stuck detection while they are still
    # advancing through tracked work.
    'TaskTrackingObservation',
)

# Tool fallback map — when a tool fails, suggest the next alternative so the
# model can pivot in the same turn instead of stopping to explain.
_TOOL_FALLBACK_MAP: dict[str, list[str]] = {
    'symbol_editor': [
        'text_editor',
    ],
    'text_editor': [],
    'search_code': ['lsp_query'],
    'lsp_query': ['search_code'],
}


def _tool_name_for_action(action: object) -> str:
    tcm = getattr(action, 'tool_call_metadata', None)
    if tcm is None:
        return ''
    return getattr(tcm, 'function_name', '') or ''


def _effective_error_tool_name(tool_name: str, content: str) -> str:
    if tool_name != TEXT_EDITOR_TOOL_NAME:
        return tool_name
    return classify_text_editor_error_bucket(content)


def _fallback_hint(tool_name: str) -> str | None:
    if tool_name not in _TOOL_FALLBACK_MAP:
        return None
    fallbacks = _TOOL_FALLBACK_MAP[tool_name]
    return (
        f'\n\n[TOOL_FALLBACK] `{tool_name}` failed. Try: '
        f'{", ".join(f"`{tool}`" for tool in fallbacks)} instead — pivot immediately.'
    )


def _append_tool_fallback_hint(observation: Observation, tool_name: str) -> None:
    hint = _fallback_hint(tool_name)
    if hint is None:
        return
    base_content = observation.content or ''
    observation.content = base_content + hint


def _record_success_progress(service: object, tool_name: str, observation: Observation) -> None:
    record_success = getattr(service, 'record_success')
    record_success(tool_name=tool_name)
    obs_type = type(observation).__name__
    if obs_type in _PROGRESS_OBSERVATION_TYPES:
        service.record_progress_signal(obs_type)


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

        tool_name = _tool_name_for_action(ctx.action)

        if isinstance(observation, ErrorObservation):
            base_content = observation.content or ''
            effective_tool = _effective_error_tool_name(tool_name, base_content)
            _append_tool_fallback_hint(observation, tool_name)
            service.record_error(
                RuntimeError(observation.content), tool_name=effective_tool
            )
            return

        _record_success_progress(service, tool_name, observation)
