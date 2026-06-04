"""Response-handling and agent-mode methods for OrchestratorExecutor.

Pure code motion: extracted from backend/engine/executor.py. Methods defined
at module level for clean extraction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.core.errors import LLMNoActionError
from backend.core.interaction_modes import (
    AGENT_MODE,
    is_chat_mode,
    normalize_interaction_mode,
)
from backend.core.logger import app_logger as logger
from backend.engine._executor_types import ModelResponse, orchestrator_function_calling
from backend.engine.executor_response_helpers import (
    build_recoverable_tool_call_error_action as _build_recoverable_tool_call_error_action_impl,
)
from backend.engine.executor_response_helpers import (
    content_to_str as _content_to_str_impl,
)
from backend.engine.executor_response_helpers import (
    extract_last_user_text as _extract_last_user_text_impl,
)
from backend.engine.executor_response_helpers import (
    extract_recent_user_text as _extract_recent_user_text_impl,
)
from backend.engine.executor_response_helpers import (
    extract_response_text as _extract_response_text_impl,
)
from backend.engine.executor_response_helpers import (
    is_recoverable_tool_call_error as _is_recoverable_tool_call_error_impl,
)
from backend.engine.executor_response_helpers import (
    without_blank_agent_messages as _without_blank_agent_messages_impl,
)

if TYPE_CHECKING:
    from backend.ledger.action import Action


class _ExecutorResponseMixin:
    """Mixin: response handling and agent-mode gating. All 11 methods defined below."""

    _PLAIN_TEXT_GATE_MAX_RETRIES: int = 2

    @staticmethod
    def _build_recoverable_tool_call_error_action(exc: Exception) -> Action:
        return _build_recoverable_tool_call_error_action_impl(exc)

    def _content_to_str(self, content: Any) -> str:
        return _content_to_str_impl(content)

    def _extract_last_user_text(self, messages: list[dict[str, Any]]) -> str:
        return _extract_last_user_text_impl(messages)

    def _extract_recent_user_text(self, messages: list[dict[str, Any]]) -> str:
        return _extract_recent_user_text_impl(messages)

    def _extract_response_text(self, response: ModelResponse) -> str:
        return _extract_response_text_impl(response)

    def _gate_agent_mode_plain_text(
        self, actions: list[Action], _response: ModelResponse
    ) -> list[Action]:
        """Reject plain-text responses in Agent mode.

        Chat and Plan modes are not gated here. Agent mode has a stricter
        protocol: every model turn must resolve to a tool action, a
        ``communicate_with_user`` handoff, or ``finish``.

        When the parser returns only ``MessageAction`` objects in Agent mode,
        raise ``LLMNoActionError``. ``ActionExecutionService`` owns the retry
        policy for repairable model-output errors, so prose never becomes a
        user-facing action and the event router cannot race against it.
        """
        from backend.ledger.action.message import MessageAction as _MessageAction

        mode = self._get_agent_mode()
        if is_chat_mode(mode) or normalize_interaction_mode(mode) != AGENT_MODE:
            return actions

        if not actions or not all(isinstance(a, _MessageAction) for a in actions):
            return actions

        self._consecutive_plain_text_blocks += 1

        self._set_plain_text_directive(self._consecutive_plain_text_blocks)

        logger.warning(
            'Agent-mode LLM response contained plain text with no tool call '
            '(count=%d); raising repairable no-action error.',
            self._consecutive_plain_text_blocks,
        )
        raise LLMNoActionError(
            'Agent mode requires a tool action, but the model returned plain text '
            'with no tool call.'
        )

    def _get_agent_mode(self) -> str:
        """Return the active mode string from run state or planner config."""
        active_mode = normalize_interaction_mode(
            getattr(self, '_active_run_mode', None),
            default='',
        )
        if active_mode:
            return active_mode
        config = getattr(self._planner, '_config', None)
        return normalize_interaction_mode(getattr(config, 'mode', 'agent'))

    @staticmethod
    def _is_recoverable_tool_call_error(exc: Exception) -> bool:
        return _is_recoverable_tool_call_error_impl(exc)

    def _response_to_actions(self, response: ModelResponse) -> list[Action]:
        mcp_tools = self._mcp_tools_provider()
        try:
            actions = list(
                orchestrator_function_calling.response_to_actions(
                    response,
                    mcp_tool_names=list(mcp_tools.keys()),
                    mcp_tools=mcp_tools,
                    mode=self._get_agent_mode(),
                )
            )
        except Exception as exc:
            if not self._is_recoverable_tool_call_error(exc):
                raise
            logger.warning(
                'Recoverable tool-call error from LLM output: %s',
                exc,
            )
            actions = [self._build_recoverable_tool_call_error_action(exc)]

        # AGENT MODE GATE: raw/editor-block file transports are disabled; file
        # edits must be native tool calls.
        actions = self._gate_agent_mode_plain_text(actions, response)

        _, validated_actions = self._safety.apply(
            self._extract_response_text(response), actions
        )
        return validated_actions

    def _set_plain_text_directive(self, count: int) -> None:
        """Set a terse planning directive so the LLM gets corrective feedback."""
        state = getattr(self, '_state', None)
        if state is None or not hasattr(state, 'set_planning_directive'):
            return
        text = (
            f'Protocol error: your previous response was plain prose '
            f'(attempt {count}). In Agent mode you must emit exactly one '
            f'tool action every turn: finish to answer, communicate_with_user '
            f'to ask, or a work tool to continue.'
        )
        try:
            state.set_planning_directive(
                text,
                source='OrchestratorExecutor._gate_agent_mode_plain_text',
            )
        except Exception:
            logger.debug('Failed to set plain-text planning directive', exc_info=True)

    @staticmethod
    def _without_blank_agent_messages(actions: list[Action]) -> list[Action]:
        return _without_blank_agent_messages_impl(actions)
