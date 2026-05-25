from __future__ import annotations

from collections import deque
from collections.abc import Callable
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import pytest

from backend.core.errors import LLMNoActionError
from backend.engine.executor import OrchestratorExecutor
from backend.engine.orchestrator import Orchestrator
from backend.ledger.action import Action, AgentThinkAction, MessageAction


def _make_result(content: str) -> SimpleNamespace:
    """Build a minimal LLM-result stub with no actions."""
    return SimpleNamespace(
        actions=[],
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        ),
        execution_time=0.0,
    )


def _make_orchestrator() -> Orchestrator:
    """Construct an Orchestrator with all heavy dependencies mocked out."""
    orch = object.__new__(Orchestrator)
    orch.llm = MagicMock()
    orch.planner = MagicMock()
    orch.executor = MagicMock()
    orch.tools = MagicMock()
    orch.memory_manager = MagicMock()
    orch.event_stream = MagicMock()
    orch.pending_actions = deque()
    orch.deferred_actions = deque()
    return orch


def _build_fallback_action(orch: Orchestrator, result: object) -> Action:
    method = cast(Callable[[object], Action], getattr(orch, '_build_fallback_action'))
    return method(result)


class TestBuildFallbackAction:
    """Integration-level tests for _build_fallback_action."""

    def test_empty_content_raises_llm_no_action_error(self) -> None:
        """Empty LLM response must raise LLMNoActionError, not silently produce NullAction."""
        orch = _make_orchestrator()
        with pytest.raises(LLMNoActionError):
            _build_fallback_action(orch, _make_result(''))

    def test_whitespace_only_raises_llm_no_action_error(self) -> None:
        """Whitespace-only LLM response must raise LLMNoActionError."""
        orch = _make_orchestrator()
        with pytest.raises(LLMNoActionError):
            _build_fallback_action(orch, _make_result('   \n  '))

    def test_no_response_raises_llm_no_action_error(self) -> None:
        """No response object at all must raise LLMNoActionError."""
        orch = _make_orchestrator()
        result = SimpleNamespace(actions=[], response=None, execution_time=0.0)
        with pytest.raises(LLMNoActionError):
            _build_fallback_action(orch, result)

    @pytest.mark.parametrize(
        'text',
        [
            # JSON planning blob — the exact pattern from the reported bug
            '{ "analysis": "env check", "plan": "1. python --version", "commands": [] }',
            # Plain narration
            'We need to build an expense sharing service.',
            # Model pretending it executed something
            'I have created the FastAPI application and configured SQLite.',
            # Genuine question — must still be non-blocking; model must use communicate_with_user
            'Which Python version should I target?',
        ],
    )
    def test_any_non_empty_text_does_not_pause_loop(self, text: str) -> None:
        orch = _make_orchestrator()
        action = _build_fallback_action(orch, _make_result(text))
        assert isinstance(action, MessageAction)
        assert action.wait_for_response is False, (
            'Any text-only LLM response must continue the loop; '
            'use communicate_with_user to pause for real user input'
        )


class TestPlainTextProtocolGate:
    def _make_executor(self, mode: str, *, active_tasks: bool = False):
        executor = object.__new__(OrchestratorExecutor)
        executor._planner = SimpleNamespace(_config=SimpleNamespace(mode=mode))
        executor._has_active_tasks = active_tasks
        executor._active_run_mode = mode
        return executor

    def test_chat_mode_allows_plain_text(self):
        executor = self._make_executor('chat')
        action = MessageAction(content='plain answer')

        result = executor._gate_agent_mode_plain_text(
            [action], _make_result('plain').response
        )

        assert result == [action]

    def test_agent_mode_without_active_tasks_preserves_existing_plain_text_behavior(
        self,
    ):
        executor = self._make_executor('agent', active_tasks=False)
        action = MessageAction(content='plain answer')

        result = executor._gate_agent_mode_plain_text(
            [action], _make_result('plain').response
        )

        assert result == [action]

    def test_agent_mode_with_active_tasks_still_blocks_plain_text(self):
        executor = self._make_executor('agent', active_tasks=True)
        action = MessageAction(content='plain answer')

        result = executor._gate_agent_mode_plain_text(
            [action], _make_result('plain').response
        )

        assert result == []

    def test_plan_mode_blocks_plain_text_without_task_tracker_state(self):
        executor = self._make_executor('plan', active_tasks=False)
        action = MessageAction(content='here is a plan in prose')

        result = executor._gate_agent_mode_plain_text(
            [action], _make_result('plain').response
        )

        assert len(result) == 1
        assert isinstance(result[0], AgentThinkAction)
        assert 'PLAN_MODE_PROTOCOL_ERROR' in result[0].thought
