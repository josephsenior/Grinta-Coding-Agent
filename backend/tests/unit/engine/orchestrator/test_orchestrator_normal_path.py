from __future__ import annotations

from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.engine.orchestrator import Orchestrator
from backend.ledger.action import AgentThinkAction
from backend.ledger.action.agent import CondensationAction
from backend.ledger.observation import StatusObservation


def _make_orchestrator_with_executor() -> tuple[Orchestrator, SimpleNamespace]:
    """Build a minimal Orchestrator with a stub executor we can drive."""
    orch = object.__new__(Orchestrator)
    orch.llm = SimpleNamespace()
    orch.planner = SimpleNamespace()
    orch.executor = SimpleNamespace(
        _has_active_tasks=False,
        _active_run_mode='agent',
        _consecutive_plain_text_blocks=0,
        _state=None,
    )
    orch.tools = {}
    orch.memory_manager = SimpleNamespace()
    orch.event_stream = SimpleNamespace()
    orch.pending_actions = deque()
    orch.deferred_actions = deque()
    orch._consecutive_invalid_protocol_outputs = 0
    orch._consecutive_context_errors = 0
    orch._recoverable_tool_error_signature = ''
    orch._recoverable_tool_error_count = 0
    return orch, orch.executor  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_normal_step_resets_plain_text_counter_after_valid_action() -> None:
    orch, executor = _make_orchestrator_with_executor()
    executor._consecutive_plain_text_blocks = 2  # type: ignore[attr-defined]
    action = AgentThinkAction(thought='Continuing with a real action.')
    orch._check_exit_command = lambda _state: None  # type: ignore[method-assign]
    orch._execute_llm_step_async = AsyncMock(return_value=action)  # type: ignore[method-assign]
    orch.memory_manager = SimpleNamespace(
        condense_history=AsyncMock(
            return_value=SimpleNamespace(pending_action=None, events=[])
        )
    )

    result = await orch._astep_normal_path(SimpleNamespace())

    assert result is action
    assert executor._consecutive_plain_text_blocks == 0  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_normal_step_emits_compaction_status_before_condense() -> None:
    orch, _executor = _make_orchestrator_with_executor()
    orch.event_stream = MagicMock()
    orch._check_exit_command = lambda _state: None  # type: ignore[method-assign]
    orch._reset_step_recovery_counters = MagicMock()  # type: ignore[method-assign]
    action = CondensationAction(pruned_event_ids=[1])

    async def _condense(_state):
        orch.event_stream.add_event.assert_called_once()
        emitted = orch.event_stream.add_event.call_args.args[0]
        assert isinstance(emitted, StatusObservation)
        assert emitted.status_type == 'compaction'
        return SimpleNamespace(pending_action=action, events=[])

    orch.memory_manager = SimpleNamespace(
        should_emit_compaction_status=lambda _state: True,
        condense_history=AsyncMock(side_effect=_condense),
    )

    result = await orch._astep_normal_path(SimpleNamespace())

    assert result is action
    orch.event_stream.add_event.assert_called_once()


@pytest.mark.asyncio
async def test_normal_step_falls_back_to_post_condense_compaction_status() -> None:
    orch, _executor = _make_orchestrator_with_executor()
    orch.event_stream = MagicMock()
    orch._check_exit_command = lambda _state: None  # type: ignore[method-assign]
    orch._reset_step_recovery_counters = MagicMock()  # type: ignore[method-assign]
    action = CondensationAction(pruned_event_ids=[1])

    async def _condense(_state):
        orch.event_stream.add_event.assert_not_called()
        return SimpleNamespace(pending_action=action, events=[])

    orch.memory_manager = SimpleNamespace(
        should_emit_compaction_status=lambda _state: False,
        condense_history=AsyncMock(side_effect=_condense),
    )

    result = await orch._astep_normal_path(SimpleNamespace())

    assert result is action
    orch.event_stream.add_event.assert_called_once()
