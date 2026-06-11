"""Blackboard middleware for tool invocations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.orchestration.tool_pipeline import ToolInvocationMiddleware

if TYPE_CHECKING:
    from backend.orchestration.session_orchestrator import SessionOrchestrator
    from backend.orchestration.tool_pipeline import ToolInvocationContext


class BlackboardMiddleware(ToolInvocationMiddleware):
    """Handle BlackboardAction in-process when controller has a shared blackboard (delegate workers)."""

    def __init__(self, controller: SessionOrchestrator) -> None:
        self.controller = controller

    async def execute(self, ctx: ToolInvocationContext) -> None:
        from backend.ledger.action.agent import BlackboardAction
        from backend.ledger.event import EventSource
        from backend.ledger.observation import AgentThinkObservation, ErrorObservation

        if not isinstance(ctx.action, BlackboardAction):
            return

        blackboard = self._resolve_blackboard()
        if blackboard is None:
            self._emit_unavailable(ctx, EventSource)
            return

        cmd = (getattr(ctx.action, 'command', 'get') or 'get').lower()
        key = (getattr(ctx.action, 'key', '') or '').strip()
        value = (getattr(ctx.action, 'value', '') or '').strip()

        try:
            content = await self._execute_blackboard_cmd(blackboard, cmd, key, value)
            self._emit_result(ctx, content, EventSource, AgentThinkObservation)
        except Exception as e:
            self._emit_error(
                ctx, f'[BLACKBOARD] Error: {e}', EventSource, ErrorObservation
            )

    def _resolve_blackboard(self):
        blackboard = getattr(self.controller.config, 'blackboard', None)
        if blackboard is None:
            from backend.orchestration.blackboard import Blackboard

            blackboard = Blackboard()
        return blackboard

    def _emit_unavailable(self, ctx, EventSource):
        from backend.ledger.observation import ErrorObservation
        from backend.ledger.observation_cause import attach_observation_cause

        ctx.block('blackboard_not_available')
        ctx.metadata['handled'] = True
        err = ErrorObservation(
            content='[BLACKBOARD] No shared blackboard in this session.',
            error_id='BLACKBOARD_UNAVAILABLE',
        )
        attach_observation_cause(err, ctx.action, context='blackboard.unavailable')
        err.tool_call_metadata = getattr(ctx.action, 'tool_call_metadata', None)
        self.controller.event_stream.add_event(err, EventSource.ENVIRONMENT)

    async def _execute_blackboard_cmd(self, blackboard, cmd, key, value):
        if cmd == 'get':
            result = await blackboard.get(key or None)
            if isinstance(result, dict):
                text = '\n'.join(f'  {k}: {v}' for k, v in result.items()) or '(empty)'
            else:
                text = str(result)
            return f'[BLACKBOARD] get {key or "all"}:\n{text}'
        if cmd == 'set':
            if not key:
                return '[BLACKBOARD] set requires a non-empty key.'
            await blackboard.set(key, value)
            return f'[BLACKBOARD] set {key!r} = {value!r}'
        if cmd == 'keys':
            keys = await blackboard.keys()
            return f'[BLACKBOARD] keys: {keys}'
        return f'[BLACKBOARD] unknown command: {cmd}'

    def _emit_result(self, ctx, content, EventSource, ObservationClass):
        from backend.ledger.observation_cause import attach_observation_cause

        obs = ObservationClass(content=content)
        attach_observation_cause(obs, ctx.action, context='blackboard.result')
        obs.tool_call_metadata = getattr(ctx.action, 'tool_call_metadata', None)
        self.controller.event_stream.add_event(obs, EventSource.ENVIRONMENT)
        ctx.block('blackboard_handled')
        ctx.metadata['handled'] = True

    def _emit_error(self, ctx, content, EventSource, ErrorClass):
        from backend.ledger.observation_cause import attach_observation_cause

        ctx.block('blackboard_error')
        ctx.metadata['handled'] = True
        err = ErrorClass(content=content, error_id='BLACKBOARD_ERROR')
        attach_observation_cause(err, ctx.action, context='blackboard.exception')
        err.tool_call_metadata = getattr(ctx.action, 'tool_call_metadata', None)
        self.controller.event_stream.add_event(err, EventSource.ENVIRONMENT)
