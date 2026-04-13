"""Tests for backend.engine.planner — message and tool-description helpers."""

from __future__ import annotations

import asyncio
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

from backend.core.enums import ActionSecurityRisk
from backend.engine.orchestrator import Orchestrator
from backend.engine.planner import OrchestratorPlanner, _maybe_log_prompt_metrics
from backend.ledger.action.agent import AgentThinkAction, CondensationAction
from backend.ledger.action.files import FileEditAction, FileWriteAction
from backend.ledger.observation import ErrorObservation


# We test the static/pure methods by creating a planner with minimal mocks.
def _make_planner():
    """Create a planner with None dependencies for testing pure methods."""
    return object.__new__(OrchestratorPlanner)


class TestPromptMetricsLogging:
    def test_logs_when_app_debug_prompt_metrics_enabled(self):
        with (
            patch.dict(
                'os.environ',
                {'APP_DEBUG_PROMPT_METRICS': '1'},
                clear=False,
            ),
            patch('backend.engine.planner.logger') as mock_logger,
        ):
            _maybe_log_prompt_metrics(
                [
                    {'role': 'system', 'content': 'hello'},
                    {'role': 'user', 'content': 'world'},
                ]
            )

        mock_logger.info.assert_called_once_with(
            'APP_DEBUG_PROMPT_METRICS: system_messages=%s chars_each=%s chars_total=%s',
            1,
            [5],
            5,
        )


class TestGetLastUserMessage:
    def test_finds_last_user_message(self):
        p = _make_planner()
        messages = [
            {'role': 'user', 'content': 'First'},
            {'role': 'assistant', 'content': 'Response'},
            {'role': 'user', 'content': 'Second'},
        ]
        assert p._get_last_user_message(messages) == 'Second'

    def test_no_user_message(self):
        p = _make_planner()
        messages = [{'role': 'assistant', 'content': 'Hi'}]
        assert p._get_last_user_message(messages) is None

    def test_empty_messages(self):
        p = _make_planner()
        assert p._get_last_user_message([]) is None

    def test_user_with_empty_content(self):
        p = _make_planner()
        messages = [{'role': 'user'}]
        assert p._get_last_user_message(messages) == ''


class TestOrchestratorPromptTierFromHistory:
    def test_debug_when_error_observation_in_window(self):
        orch = Orchestrator.__new__(Orchestrator)
        mock_pm = MagicMock()
        object.__setattr__(orch, '_prompt_manager', mock_pm)
        state = MagicMock()
        state.history = [
            FileEditAction(path='a.py', security_risk=ActionSecurityRisk.LOW),
            ErrorObservation(content='tool blew up'),
        ]
        orch._set_prompt_tier_from_recent_history(state)
        mock_pm.set_prompt_tier.assert_called_with('debug')


class TestCondensationRecoveryHandling:
    def test_noop_condensation_does_not_queue_recovery(self):
        orch = Orchestrator.__new__(Orchestrator)
        orch.pending_actions = deque()
        state = MagicMock()
        state.history = []
        condensed = MagicMock()
        condensed.pending_action = CondensationAction(pruned_event_ids=[])

        result = orch._handle_pending_action_from_condensation(state, condensed)

        assert result is condensed.pending_action
        assert not orch.pending_actions

    def test_real_condensation_queues_recovery(self):
        orch = Orchestrator.__new__(Orchestrator)
        orch.pending_actions = deque()
        orch.memory_manager = MagicMock()
        orch.memory_manager.get_initial_user_message.return_value = MagicMock(
            content='finish the task'
        )
        state = MagicMock()
        state.history = []
        action = CondensationAction(pruned_event_ids=[3, 4])
        condensed = MagicMock()
        condensed.pending_action = action

        result = orch._handle_pending_action_from_condensation(state, condensed)

        assert result is action
        assert len(orch.pending_actions) == 1

    def test_base_when_only_low_risk_file_edit(self):
        orch = Orchestrator.__new__(Orchestrator)
        mock_pm = MagicMock()
        object.__setattr__(orch, '_prompt_manager', mock_pm)
        state = MagicMock()
        state.history = [
            FileEditAction(path='a.py', security_risk=ActionSecurityRisk.LOW)
        ]
        orch._set_prompt_tier_from_recent_history(state)
        mock_pm.set_prompt_tier.assert_called_with('base')

    def test_debug_when_file_write_high_security_risk(self):
        orch = Orchestrator.__new__(Orchestrator)
        mock_pm = MagicMock()
        object.__setattr__(orch, '_prompt_manager', mock_pm)
        state = MagicMock()
        state.history = [
            FileWriteAction(
                path='x.sh', content='', security_risk=ActionSecurityRisk.HIGH
            ),
        ]
        orch._set_prompt_tier_from_recent_history(state)
        mock_pm.set_prompt_tier.assert_called_with('debug')


class TestQueuedActionThrottling:
    def test_queue_additional_actions_queues_all(self):
        orch = Orchestrator.__new__(Orchestrator)
        orch.pending_actions = deque()
        orch.deferred_actions = deque()

        actions = [AgentThinkAction(thought=f'a{i}') for i in range(5)]
        orch._queue_additional_actions(actions)  # type: ignore

        assert len(orch.pending_actions) == 5
        assert len(orch.deferred_actions) == 0

    def test_promote_deferred_actions_processes_all(self):
        orch = Orchestrator.__new__(Orchestrator)
        orch.pending_actions = deque()
        orch.deferred_actions = deque(
            [AgentThinkAction(thought='a'), AgentThinkAction(thought='b')]
        )
        orch._deferred_actions_require_replan = False  # type: ignore

        orch._promote_deferred_actions()

        assert len(orch.pending_actions) == 2
        assert len(orch.deferred_actions) == 0

    def test_clear_queued_actions_clears_pending_and_deferred(self):
        orch = Orchestrator.__new__(Orchestrator)
        orch.pending_actions = deque([AgentThinkAction(thought='a')])
        orch.deferred_actions = deque([AgentThinkAction(thought='b')])

        removed = orch.clear_queued_actions(reason='test')

        assert removed == 2
        assert len(orch.pending_actions) == 0
        assert len(orch.deferred_actions) == 0


def test_execute_llm_step_async_offloads_message_preparation_to_thread():
    orch = Orchestrator.__new__(Orchestrator)
    orch.pending_actions = deque()
    orch.deferred_actions = deque()
    orch._deferred_actions_require_replan = False  # type: ignore
    orch.memory_manager = MagicMock()
    orch.memory_manager.get_initial_user_message.return_value = MagicMock()
    orch.memory_manager.build_messages.return_value = []
    orch.planner = MagicMock()
    orch.planner.build_llm_params.return_value = {'messages': []}
    orch.executor = MagicMock()
    orch._sync_executor_llm = MagicMock()  # type: ignore
    orch._set_prompt_tier_from_recent_history = MagicMock()  # type: ignore
    orch.llm = MagicMock()
    orch.llm.config = MagicMock()
    orch.tools = []
    orch.event_stream = MagicMock()

    result_payload = MagicMock()
    result_payload.execution_time = 0.2
    first = AgentThinkAction(thought='first')
    second = AgentThinkAction(thought='second')
    result_payload.actions = [first, second]
    orch.executor.async_execute = AsyncMock(return_value=result_payload)

    state = MagicMock()
    state.history = []
    state.extra_data = {}
    condensed = MagicMock()
    condensed.pending_action = None
    condensed.events = []

    async def _fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with patch('backend.engine.orchestrator.asyncio.to_thread', new=AsyncMock(side_effect=_fake_to_thread)) as mock_to_thread:
        action = asyncio.run(orch._execute_llm_step_async(state, condensed))

    assert action is first
    mock_to_thread.assert_awaited_once()
    assert len(orch.pending_actions) == 1
    assert orch.pending_actions[0] is second
