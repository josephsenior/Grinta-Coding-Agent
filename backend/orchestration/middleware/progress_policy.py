"""Generic progress-aware fingerprint gate for tool invocations."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from backend.ledger.action.terminal import TerminalReadAction
from backend.ledger.observation import ErrorObservation
from backend.orchestration.tool_pipeline import ToolInvocationMiddleware

if TYPE_CHECKING:
    from backend.ledger.observation import Observation
    from backend.orchestration.tool_pipeline import ToolInvocationContext

_POLICY_STATE_KEY = '__progress_policy_state'
_REPEAT_LIMIT = 4
# PTY reads with no new bytes are a common stall pattern; allow one retry, then gate.
_REPEAT_LIMIT_TERMINAL_READ = 3


class ProgressPolicyMiddleware(ToolInvocationMiddleware):
    """Blocks repeated identical actions when there is no measurable progress."""

    def _state_dict(self, ctx: ToolInvocationContext) -> dict[str, Any]:
        state = getattr(ctx, 'state', None)
        if state is None:
            return {}
        extra = getattr(state, 'extra_data', None)
        if not isinstance(extra, dict):
            extra = {}
            state.extra_data = extra
        gate = extra.get(_POLICY_STATE_KEY)
        if not isinstance(gate, dict):
            gate = {
                'last_fingerprint': None,
                'repeat_count': 0,
                'progress_epoch': 0,
                'repeat_epoch': 0,
            }
            extra[_POLICY_STATE_KEY] = gate
        return gate

    @staticmethod
    def _fingerprint_action(action: Any) -> str:
        tool_name = ''
        tcm = getattr(action, 'tool_call_metadata', None)
        if tcm is not None:
            tool_name = str(getattr(tcm, 'function_name', '') or '')
        base = [
            str(type(action).__name__),
            str(getattr(action, 'action', '')),
            tool_name,
            str(getattr(action, 'session_id', '')),
            str(getattr(action, 'command', '')),
            str(getattr(action, 'input', '')),
            str(getattr(action, 'path', '')),
            str(getattr(action, 'mode', '')),
            str(getattr(action, 'offset', '')),
            str(getattr(action, 'control', '')),
            str(getattr(action, 'submit', '')),
        ]
        return hashlib.sha256('|'.join(base).encode('utf-8')).hexdigest()

    async def execute(self, ctx: ToolInvocationContext) -> None:
        gate = self._state_dict(ctx)
        if not gate:
            return
        fp = self._fingerprint_action(ctx.action)
        last_fp = gate.get('last_fingerprint')
        progress_epoch = int(gate.get('progress_epoch', 0))
        repeat_epoch = int(gate.get('repeat_epoch', 0))
        repeat_count = int(gate.get('repeat_count', 0))
        if fp == last_fp and progress_epoch == repeat_epoch:
            repeat_count += 1
        else:
            repeat_count = 1
            repeat_epoch = progress_epoch
        gate['last_fingerprint'] = fp
        gate['repeat_count'] = repeat_count
        gate['repeat_epoch'] = repeat_epoch
        limit = (
            _REPEAT_LIMIT_TERMINAL_READ
            if isinstance(ctx.action, TerminalReadAction)
            else _REPEAT_LIMIT
        )
        if repeat_count >= limit:
            ctx.block(
                reason=(
                    'POLICY_GATE_REPLAN_REQUIRED: repeated identical action signature '
                    'without measurable progress. Change strategy before retrying.'
                )
            )

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        if observation is None:
            return
        gate = self._state_dict(ctx)
        if not gate:
            return
        if self._is_progress(observation):
            gate['progress_epoch'] = int(gate.get('progress_epoch', 0)) + 1
            gate['repeat_count'] = 0

    @staticmethod
    def _is_progress(observation: Observation) -> bool:
        if isinstance(observation, ErrorObservation):
            return False
        tool_result = getattr(observation, 'tool_result', None)
        if isinstance(tool_result, dict):
            if bool(tool_result.get('progress')):
                return True
            state = str(tool_result.get('state', '')).upper()
            # Terminal states are not automatic progress: ``tool_result['progress']``
            # reflects real output deltas. Otherwise empty ``terminal_input`` reads
            # would reset repeat counters forever.
            if state in {'FILE_CHANGED', 'CHECKPOINT_SAVED'}:
                return True
        content = getattr(observation, 'content', None)
        return isinstance(content, str) and bool(content.strip())
