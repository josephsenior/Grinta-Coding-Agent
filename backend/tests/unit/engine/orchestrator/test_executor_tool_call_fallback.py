from __future__ import annotations

from collections import deque
from collections.abc import Callable
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import pytest

from backend.engine.executor import OrchestratorExecutor
from backend.engine.orchestrator import Orchestrator
from backend.ledger.action import Action, MessageAction
from backend.ledger.action.empty import NullAction, NullActionReason


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
    orch.config = SimpleNamespace(mode='agent')
    orch.llm = MagicMock()
    orch.planner = MagicMock()
    orch.executor = SimpleNamespace(_active_run_mode='agent')
    orch.tools = MagicMock()
    orch.memory_manager = MagicMock()
    orch.event_stream = MagicMock()
    orch.pending_actions = deque()
    orch.deferred_actions = deque()
    return orch


def _state_with_tasks(*statuses: str) -> SimpleNamespace:
    return SimpleNamespace(
        extra_data={'__agent_protocol_tracker_created': True},
        plan=SimpleNamespace(
            steps=[
                SimpleNamespace(
                    id=str(index),
                    description=f'Task {index}',
                    status=status,
                    subtasks=[],
                )
                for index, status in enumerate(statuses, 1)
            ]
        ),
    )


def _build_fallback_action(orch: Orchestrator, result: object) -> Action:
    method = cast(Callable[[object], Action], getattr(orch, '_build_fallback_action'))
    return method(result)


class TestBuildFallbackAction:
    """Integration-level tests for _build_fallback_action."""

    def test_empty_content_returns_reasoning_only_null_action(self) -> None:
        """Empty LLM responses continue the run instead of pausing."""
        orch = _make_orchestrator()
        action = _build_fallback_action(orch, _make_result(''))
        assert isinstance(action, NullAction)
        assert action.reason == NullActionReason.REASONING_ONLY

    def test_whitespace_only_returns_reasoning_only_null_action(self) -> None:
        orch = _make_orchestrator()
        action = _build_fallback_action(orch, _make_result('   \n  '))
        assert isinstance(action, NullAction)
        assert action.reason == NullActionReason.REASONING_ONLY

    def test_no_response_returns_reasoning_only_null_action(self) -> None:
        orch = _make_orchestrator()
        result = SimpleNamespace(actions=[], response=None, execution_time=0.0)
        action = _build_fallback_action(orch, result)
        assert isinstance(action, NullAction)
        assert action.reason == NullActionReason.REASONING_ONLY

    def test_marker_only_content_returns_reasoning_only_null_action(self) -> None:
        orch = _make_orchestrator()
        action = _build_fallback_action(orch, _make_result('[END_TOOL_CALL]'))
        assert isinstance(action, NullAction)
        assert action.reason == NullActionReason.REASONING_ONLY

    @pytest.mark.parametrize(
        'text',
        [
            # JSON planning blob — the exact pattern from the reported bug
            '{ "analysis": "env check", "plan": "1. python --version", "commands": [] }',
            # Plain narration
            'We need to build an expense sharing service.',
            # Model pretending it executed something
            'I have created the FastAPI application and configured SQLite.',
            # Genuine question in plain text is still a final response; use ask_user to pause.
            'Which Python version should I target?',
        ],
    )
    def test_agent_mode_non_empty_text_yields_final_response(self, text: str) -> None:
        orch = _make_orchestrator()
        action = _build_fallback_action(orch, _make_result(text))

        assert isinstance(action, MessageAction)
        assert action.content == text
        assert action.wait_for_response is False
        assert action.final_response is True

    def test_agent_mode_fallback_with_active_tracker_is_final_response(self) -> None:
        orch = _make_orchestrator()
        orch.executor = SimpleNamespace(
            _active_run_mode='agent',
            _state=_state_with_tasks('in_progress'),
            _consecutive_plain_text_blocks=0,
        )

        action = _build_fallback_action(orch, _make_result('Still thinking aloud.'))

        assert isinstance(action, MessageAction)
        assert action.wait_for_response is False
        assert action.final_response is True

    def test_agent_mode_fallback_terminal_tracker_is_final_response(self) -> None:
        orch = _make_orchestrator()
        orch.executor = SimpleNamespace(
            _active_run_mode='agent',
            _state=_state_with_tasks('done'),
        )

        action = _build_fallback_action(orch, _make_result('Everything is complete.'))

        assert isinstance(action, MessageAction)
        assert action.content == 'Everything is complete.'
        assert action.final_response is True

    @pytest.mark.parametrize('mode', ['chat', 'plan'])
    def test_non_agent_modes_yield_final_response(self, mode: str) -> None:
        orch = _make_orchestrator()
        orch.config = SimpleNamespace(mode=mode)
        orch.executor = SimpleNamespace(_active_run_mode=mode)

        action = _build_fallback_action(orch, _make_result('plain answer'))

        assert isinstance(action, MessageAction)
        assert action.content == 'plain answer'
        assert action.wait_for_response is False
        assert action.final_response is True

    def test_plan_mode_fallback_with_active_tracker_is_final_response(self) -> None:
        orch = _make_orchestrator()
        orch.config = SimpleNamespace(mode='plan')
        orch.executor = SimpleNamespace(
            _active_run_mode='plan',
            _state=_state_with_tasks('in_progress'),
            _consecutive_plain_text_blocks=0,
        )

        action = _build_fallback_action(orch, _make_result('Drafting the plan.'))

        assert isinstance(action, MessageAction)
        assert action.wait_for_response is False
        assert action.final_response is True

    def test_plan_mode_fallback_terminal_tracker_is_final_response(self) -> None:
        orch = _make_orchestrator()
        orch.config = SimpleNamespace(mode='plan')
        orch.executor = SimpleNamespace(
            _active_run_mode='plan',
            _state=_state_with_tasks('done'),
        )

        action = _build_fallback_action(orch, _make_result('Plan is complete.'))

        assert isinstance(action, MessageAction)
        assert action.content == 'Plan is complete.'
        assert action.final_response is True


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

    def test_agent_mode_without_tracker_allows_plain_text(
        self,
    ):
        executor = self._make_executor('agent', active_tasks=False)
        action = MessageAction(content='plain answer')

        result = executor._gate_agent_mode_plain_text(
            [action], _make_result('plain').response
        )

        assert result == [action]
        assert executor._consecutive_plain_text_blocks == 0

    def test_agent_mode_with_active_tracker_keeps_plain_text_unchanged(self):
        executor = self._make_executor('agent', active_tasks=True)
        executor._state = _state_with_tasks('in_progress')
        action = MessageAction(content='plain answer')

        result = executor._gate_agent_mode_plain_text(
            [action], _make_result('plain').response
        )

        assert result == [action]
        assert action.protocol_status is False
        assert executor._consecutive_plain_text_blocks == 0

    def test_agent_mode_mixed_actions_keep_message_visible(self):
        executor = self._make_executor('agent', active_tasks=True)
        executor._state = _state_with_tasks('in_progress')
        text = MessageAction(content='I will run the check.', transcript_only=True)
        tool = MagicMock(spec=Action)

        result = executor._gate_agent_mode_plain_text(
            [text, tool], _make_result('mixed').response
        )

        assert result == [text, tool]
        assert text.wait_for_response is False
        assert text.suppress_cli is False

    def test_agent_mode_terminal_tracker_keeps_plain_text_unchanged(self):
        executor = self._make_executor('agent', active_tasks=True)
        executor._state = _state_with_tasks('done')
        action = MessageAction(content='plain answer')

        result = executor._gate_agent_mode_plain_text(
            [action], _make_result('plain').response
        )

        assert result == [action]

    def test_plan_mode_allows_plain_text_without_task_tracker_state(self):
        executor = self._make_executor('plan', active_tasks=False)
        action = MessageAction(content='here is a plan in prose')

        result = executor._gate_agent_mode_plain_text(
            [action], _make_result('plain').response
        )

        assert result == [action]

    def test_plan_mode_with_active_tracker_keeps_plain_text_unchanged(self):
        executor = self._make_executor('plan', active_tasks=True)
        executor._state = _state_with_tasks('in_progress')
        action = MessageAction(content='plan status')

        result = executor._gate_agent_mode_plain_text(
            [action], _make_result('plain').response
        )

        assert result == [action]
        assert action.protocol_status is False

    def test_plan_mode_terminal_tracker_keeps_plain_text_unchanged(self):
        executor = self._make_executor('plan', active_tasks=True)
        executor._state = _state_with_tasks('done')
        action = MessageAction(content='plan summary')

        result = executor._gate_agent_mode_plain_text(
            [action], _make_result('plain').response
        )

        assert result == [action]
