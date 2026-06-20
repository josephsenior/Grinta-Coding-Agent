"""Response-handling and agent-mode methods for OrchestratorExecutor.

Pure code motion: extracted from backend/engine/executor.py. Methods defined
at module level for clean extraction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.core.interaction_modes import normalize_interaction_mode
from backend.core.logging.logger import app_logger as logger
from backend.engine.executor_mixins._executor_types import (
    ModelResponse,
    orchestrator_function_calling,
)
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
    """Mixin: response handling and action conversion."""

    _PLAIN_TEXT_GATE_MAX_RETRIES: int = 0

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
        """Plain text is a final response; no Agent/Plan prose enforcement."""
        return actions

    def _handle_agent_mixed_actions(
        self, actions: list[Action], state: object | None
    ) -> list[Action]:
        """Compatibility no-op for older tests/imports."""
        return actions

    def _handle_agent_plain_text_only(
        self,
        actions: list[Action],
        state: object | None,
        *,
        plain_text: str,
    ) -> list[Action]:
        """Compatibility no-op for older tests/imports."""
        _ = (state, plain_text)
        return actions

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
        """Compatibility no-op; plain text now ends the run."""
        _ = count

    @staticmethod
    def _without_blank_agent_messages(actions: list[Action]) -> list[Action]:
        return _without_blank_agent_messages_impl(actions)
