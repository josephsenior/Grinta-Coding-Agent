"""Response-handling and agent-mode methods for OrchestratorExecutor.

Pure code motion: extracted from backend/engine/executor.py. Methods defined
at module level for clean extraction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.core.agent_protocol import (
    ABANDONED_RETRY_PROMPT,
    CONTINUATION_NUDGE,
    increment_prose_attempts,
    increment_self_extension,
    is_protocol_mode,
    mark_abandoned,
    prose_attempts,
    reset_prose_attempts,
    reset_terminal_cycle,
    self_extension_count,
    set_pending_directive,
    terminal_nudge_sent,
    tracker_created,
    tracker_terminal,
    work_remains,
)
from backend.core.interaction_modes import (
    is_chat_mode,
    normalize_interaction_mode,
)
from backend.core.logger import app_logger as logger
from backend.engine.executor_mixins._executor_types import ModelResponse, orchestrator_function_calling
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
        """Apply Agent/Plan prose rules based on tracker commitment state.

        Agent/Plan mode is conversational until a task tracker exists. Once
        the tracker exists, plain prose cannot silently complete unfinished
        work.
        """
        from backend.ledger.action.agent import PlaybookFinishAction
        from backend.ledger.action.message import MessageAction as _MessageAction

        mode = self._get_agent_mode()
        normalized_mode = normalize_interaction_mode(mode)
        if is_chat_mode(normalized_mode) or not is_protocol_mode(normalized_mode):
            return actions

        if not actions:
            return actions

        state = getattr(self, '_state', None)
        if any(isinstance(action, PlaybookFinishAction) for action in actions):
            reset_prose_attempts(state)
            return actions

        message_actions = [
            action for action in actions if isinstance(action, _MessageAction)
        ]
        if len(message_actions) != len(actions):
            return self._handle_agent_mixed_actions(actions, state)

        plain_text = '\n\n'.join(
            str(getattr(action, 'content', '') or '').strip()
            for action in message_actions
            if str(getattr(action, 'content', '') or '').strip()
        )
        return self._handle_agent_plain_text_only(
            actions,
            state,
            plain_text=plain_text,
        )

    def _handle_agent_mixed_actions(
        self, actions: list[Action], state: object | None
    ) -> list[Action]:
        """Handle model responses that contain at least one real tool call."""
        from backend.ledger.action.message import MessageAction as _MessageAction

        if tracker_terminal(state) and terminal_nudge_sent(state):
            if self_extension_count(state) >= 1:
                logger.warning(
                    'Agent/Plan protocol forcing finish after repeated self-extension '
                    'from terminal tracker state.'
                )
                return [
                    self._synthesize_finish(
                        'All tracked tasks are terminal; finishing the run.',
                        forced=True,
                    )
                ]
            increment_self_extension(state)
            reset_terminal_cycle(state)

        reset_prose_attempts(state)
        for action in actions:
            if isinstance(action, _MessageAction):
                action.wait_for_response = False
        return actions

    def _handle_agent_plain_text_only(
        self,
        actions: list[Action],
        state: object | None,
        *,
        plain_text: str,
    ) -> list[Action]:
        from backend.ledger.action.message import MessageAction as _MessageAction

        if not tracker_created(state):
            reset_prose_attempts(state)
            return actions

        if tracker_terminal(state):
            reset_prose_attempts(state)
            return [self._synthesize_finish(plain_text)]

        if not work_remains(state):
            reset_prose_attempts(state)
            return actions

        current_attempts = prose_attempts(state)
        if current_attempts >= 3:
            mark_abandoned(state)
            logger.warning(
                'Agent/Plan protocol abandoned run after repeated prose while work remained '
                '(attempts=%d, text=%r).',
                current_attempts,
                plain_text[:500],
            )
            abandoned = _MessageAction(
                content=ABANDONED_RETRY_PROMPT,
                wait_for_response=True,
            )
            abandoned.protocol_abandoned = True
            return [abandoned]

        count = increment_prose_attempts(state)
        self._consecutive_plain_text_blocks = count
        set_pending_directive(
            state,
            CONTINUATION_NUDGE,
            source='OrchestratorExecutor._handle_agent_plain_text_only',
        )
        logger.info(
            'Agent/Plan prose converted to mid-task status card (attempt=%d).',
            count,
        )
        for action in actions:
            if isinstance(action, _MessageAction):
                action.wait_for_response = False
                action.protocol_status = True
        return actions

    def _synthesize_finish(
        self, summary: str, *, forced: bool = False, mode: str | None = None
    ) -> Action:
        """Build a finish action from terminal plain text."""
        from backend.ledger.action.agent import PlaybookFinishAction

        clean = (summary or '').strip() or 'All tracked tasks are complete.'
        finish_mode = normalize_interaction_mode(mode or self._get_agent_mode())
        outputs = {
            'mode': finish_mode,
            'status': 'completed',
            'response': clean,
            'summary': clean,
            'sections': [{'title': 'Summary', 'items': [clean]}],
            'evidence': {
                'status': 'not_applicable',
                'details': 'Synthesized from plain text after tracker completion.',
            },
            'open_items': [],
            'next_step': '',
            'actions_taken': [],
            'verification': {
                'status': 'not_run',
                'details': 'No separate verification was reported in the final text.',
            },
            'remaining_items': [],
        }
        return PlaybookFinishAction(
            final_thought=clean,
            outputs=outputs,
            force_finish=forced,
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
        text = (
            f'Your previous response was plain prose while work remained '
            f'(attempt {count}). {CONTINUATION_NUDGE}'
        )
        set_pending_directive(
            state,
            text,
            source='OrchestratorExecutor._set_plain_text_directive',
        )

    @staticmethod
    def _without_blank_agent_messages(actions: list[Action]) -> list[Action]:
        return _without_blank_agent_messages_impl(actions)
