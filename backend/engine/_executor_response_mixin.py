"""Response-handling and agent-mode methods for OrchestratorExecutor.

Pure code motion: extracted from backend/engine/executor.py. Methods defined
at module level for clean extraction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.core.interaction_modes import (
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
        self, actions: list[Action], response: ModelResponse
    ) -> list[Action]:
        """Block plain-text responses in AGENT mode when active tasks exist.

        Plan mode is not gated here — the prompt guidance and tool filtering
        handle the preference for structured finish() calls.

        Behaviour:
            * Each gate firing increments
              ``self._consecutive_plain_text_blocks``. The original
              ``actions`` list is replaced with a single ``MessageAction``
              sentinel (``suppress_cli=True``, ``wait_for_response=False``).
              The LLM's prose is stashed on
              ``sentinel._gate_suppressed_text`` and the original ``actions``
              list on ``sentinel._gate_suppressed_actions`` so the
              orchestrator can later choose to surface them.
            * A terse ``planning_directive`` is set on the executor's
              ``_state.turn_signals`` so the LLM gets corrective feedback on
              its next turn.
            * Once the counter exceeds ``_PLAIN_TEXT_GATE_MAX_RETRIES`` the
              sentinel is marked ``_gate_threshold_breach=True`` so the
              orchestrator promotes the suppressed text to
              ``wait_for_response=True`` and surfaces it to the user.

        A single ``logger.debug`` line replaces the previous two ``WARNING``
        lines so the log stays quiet while remaining observable in debug
        builds.
        """
        from backend.ledger.action.message import MessageAction as _MessageAction
        from backend.ledger.event import EventSource

        mode = self._get_agent_mode()
        if is_chat_mode(mode):
            return actions

        if not actions or not all(isinstance(a, _MessageAction) for a in actions):
            return actions

        if not self._has_active_tasks:
            return actions

        self._consecutive_plain_text_blocks += 1
        breach = self._consecutive_plain_text_blocks > self._PLAIN_TEXT_GATE_MAX_RETRIES

        self._set_plain_text_directive(self._consecutive_plain_text_blocks, breach)

        suppressed_text = ''
        for a in actions:
            suppressed_text = getattr(a, 'content', '') or suppressed_text

        logger.debug(
            'Plain-text gate fired (count=%d, breach=%s): suppressed %d message '
            'action(s); directive set for next turn.',
            self._consecutive_plain_text_blocks,
            breach,
            len(actions),
        )

        sentinel = _MessageAction(
            content='',
            wait_for_response=False,
            suppress_cli=True,
        )
        sentinel.source = EventSource.AGENT
        sentinel._gate_suppressed_text = suppressed_text  # type: ignore[attr-defined]
        sentinel._gate_suppressed_actions = actions  # type: ignore[attr-defined]
        sentinel._gate_threshold_breach = breach  # type: ignore[attr-defined]
        return [sentinel]

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

    def _set_plain_text_directive(self, count: int, breach: bool) -> None:
        """Set a terse planning directive so the LLM gets corrective feedback."""
        state = getattr(self, '_state', None)
        if state is None or not hasattr(state, 'set_planning_directive'):
            return
        if breach:
            text = (
                'Protocol error: you have produced plain prose three times in a '
                'row. The system will now surface your most recent reply to the '
                'user and end this turn. Next turn, emit exactly one tool call '
                '(communicate_with_user, task_tracker, or a work tool) before '
                'any further narration.'
            )
        else:
            text = (
                f'Protocol error: your previous response was plain prose '
                f'(attempt {count}). In agent mode while tasks are open you '
                f'must emit exactly one tool call every turn — for example '
                f'communicate_with_user to pause for the user, task_tracker to '
                f'update progress, or a work tool. After '
                f'{self._PLAIN_TEXT_GATE_MAX_RETRIES} consecutive prose-only '
                f'turns the system will surface your reply and end the turn.'
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
