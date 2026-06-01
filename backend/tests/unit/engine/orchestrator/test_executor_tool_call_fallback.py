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
from backend.ledger.action import Action, MessageAction


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
        executor._state = None
        executor._consecutive_plain_text_blocks = 0
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

    def test_agent_mode_with_active_tasks_emits_suppressed_sentinel(self):
        """Gate must return a sentinel (not an empty list) carrying the
        suppressed text so the orchestrator can later surface it on a
        threshold breach.
        """
        executor = self._make_executor('agent', active_tasks=True)
        action = MessageAction(content='plain answer')

        result = executor._gate_agent_mode_plain_text(
            [action], _make_result('plain').response
        )

        assert len(result) == 1
        sentinel = result[0]
        assert isinstance(sentinel, MessageAction)
        assert sentinel.content == ''
        assert sentinel.wait_for_response is False
        assert sentinel.suppress_cli is True
        assert sentinel._gate_suppressed_text == 'plain answer'
        assert sentinel._gate_suppressed_actions == [action]
        assert sentinel._gate_threshold_breach is False
        # First gate firing must increment the counter but stay
        # under-threshold.
        assert executor._consecutive_plain_text_blocks == 1

    def test_threshold_breach_marks_sentinel(self):
        """After _PLAIN_TEXT_GATE_MAX_RETRIES + 1 consecutive gate fires, the
        sentinel is marked as a threshold breach so the orchestrator promotes
        the suppressed text and yields to the user.
        """
        executor = self._make_executor('agent', active_tasks=True)
        action = MessageAction(content='plain answer')
        max_retries = executor._PLAIN_TEXT_GATE_MAX_RETRIES

        # Fire the gate enough times to trigger the breach.
        last_result = None
        for _ in range(max_retries + 1):
            last_result = executor._gate_agent_mode_plain_text(
                [action], _make_result('plain').response
            )

        assert last_result is not None
        assert len(last_result) == 1
        sentinel = last_result[0]
        assert sentinel._gate_threshold_breach is True
        assert executor._consecutive_plain_text_blocks == max_retries + 1

    def test_set_planning_directive_called_when_state_attached(self):
        """When the executor has a state ref, the gate must set a planning
        directive so the LLM gets corrective feedback on its next turn.
        """
        from backend.orchestration.state.state import State

        executor = self._make_executor('agent', active_tasks=True)
        state = MagicMock(spec=State)
        executor._state = state
        action = MessageAction(content='plain answer')

        executor._gate_agent_mode_plain_text(
            [action], _make_result('plain').response
        )

        state.set_planning_directive.assert_called_once()
        args, _ = state.set_planning_directive.call_args
        assert 'attempt 1' in args[0]

    def test_set_planning_directive_breach_message(self):
        from backend.orchestration.state.state import State

        executor = self._make_executor('agent', active_tasks=True)
        state = MagicMock(spec=State)
        executor._state = state
        action = MessageAction(content='plain answer')

        for _ in range(executor._PLAIN_TEXT_GATE_MAX_RETRIES + 1):
            executor._gate_agent_mode_plain_text(
                [action], _make_result('plain').response
            )

        # The most recent directive should mention the breach.
        args, _ = state.set_planning_directive.call_args
        assert 'surface' in args[0].lower()

    def test_plan_mode_allows_plain_text_without_task_tracker_state(self):
        executor = self._make_executor('plan', active_tasks=False)
        action = MessageAction(content='here is a plan in prose')

        result = executor._gate_agent_mode_plain_text(
            [action], _make_result('plain').response
        )

        assert result == [action]
