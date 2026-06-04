"""Tests for the orchestrator's plain-text-gate sentinel handling.

The executor's ``_gate_agent_mode_plain_text`` replaces an LLM's plain-text
actions with a single ``MessageAction`` sentinel carrying
``_gate_suppressed_text``/``_gate_suppressed_actions``/``_gate_threshold_breach``
attributes. The orchestrator detects that sentinel via
``_promote_gate_sentinel`` and rewrites it to a protocol message on a threshold
breach.
"""

from __future__ import annotations

from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.engine.orchestrator import Orchestrator
from backend.ledger.action import MessageAction
from backend.ledger.action.agent import CondensationAction
from backend.ledger.event import EventSource
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
    callbacks: list[tuple[str, int]] = []
    orch._on_plain_text_gate = lambda kind, count: callbacks.append((kind, count))  # type: ignore[assignment]
    orch._gate_callbacks = callbacks
    return orch, orch.executor  # type: ignore[return-value]


def _make_under_threshold_sentinel(content: str) -> MessageAction:
    sentinel = MessageAction(
        content='',
        wait_for_response=False,
        suppress_cli=True,
    )
    sentinel.source = EventSource.AGENT
    sentinel._gate_suppressed_text = content  # type: ignore[attr-defined]
    sentinel._gate_suppressed_actions = [MessageAction(content=content)]  # type: ignore[attr-defined]
    sentinel._gate_threshold_breach = False  # type: ignore[attr-defined]
    return sentinel


def _make_breach_sentinel(content: str) -> MessageAction:
    sentinel = _make_under_threshold_sentinel(content)
    sentinel._gate_threshold_breach = True  # type: ignore[attr-defined]
    return sentinel


class TestPromoteGateSentinel:
    def test_under_threshold_returns_sentinel_unchanged(self) -> None:
        orch, _ = _make_orchestrator_with_executor()
        sentinel = _make_under_threshold_sentinel('thinking out loud')

        promoted = orch._promote_gate_sentinel(sentinel, breached=False)

        assert promoted is sentinel
        assert promoted.wait_for_response is False
        assert promoted.suppress_cli is True
        assert promoted.content == ''

    def test_breach_promotes_to_protocol_message(self) -> None:
        orch, _ = _make_orchestrator_with_executor()
        sentinel = _make_breach_sentinel('thinking out loud')

        promoted = orch._promote_gate_sentinel(sentinel, breached=True)

        assert isinstance(promoted, MessageAction)
        assert 'Protocol error' in promoted.content
        assert 'thinking out loud' not in promoted.content
        assert promoted.wait_for_response is True
        assert promoted.suppress_cli is False
        assert promoted.source == EventSource.AGENT

    def test_breach_does_not_surface_suppressed_thought(self) -> None:
        orch, _ = _make_orchestrator_with_executor()
        sentinel = _make_breach_sentinel('user-facing text')
        sentinel._gate_suppressed_actions = [  # type: ignore[attr-defined]
            MessageAction(content='user-facing text', thought='my reasoning')
        ]

        promoted = orch._promote_gate_sentinel(sentinel, breached=True)

        assert promoted.thought == ''
        assert 'user-facing text' not in promoted.content


class TestGateSentinelDetection:
    """The orchestrator's gate-handling block in ``_execute_llm_step`` is
    inline (not factored out), so we test it via a small helper that mimics
    the same detection logic. This keeps the test isolated from the
    orchestrator's heavy LLM plumbing.
    """

    @staticmethod
    def _detect_and_handle(orch: Orchestrator, actions: list[object]) -> object:
        """Mirror the gate-detection block from ``_execute_llm_step``."""
        first = actions[0]
        if getattr(first, '_gate_threshold_breach', False) is True:
            # Read pre-reset count for the callback; see orchestrator code.
            count = getattr(orch.executor, '_consecutive_plain_text_blocks', 0)
            orch._reset_step_recovery_counters()  # type: ignore[attr-defined]
            orch._on_plain_text_gate('threshold_breached', count)  # type: ignore[attr-defined]
            return orch._promote_gate_sentinel(first, breached=True)  # type: ignore[attr-defined]
        if getattr(first, '_gate_suppressed_text', None) is not None:
            count = getattr(orch.executor, '_consecutive_plain_text_blocks', 0)
            orch._on_plain_text_gate('under_threshold', count)  # type: ignore[attr-defined]
            return orch._promote_gate_sentinel(first, breached=False)  # type: ignore[attr-defined]
        if getattr(orch.executor, '_consecutive_plain_text_blocks', 0) > 0:
            orch.executor._consecutive_plain_text_blocks = 0  # type: ignore[attr-defined]
        return first

    def test_under_threshold_dispatches_callback(self) -> None:
        orch, executor = _make_orchestrator_with_executor()
        executor._consecutive_plain_text_blocks = 1  # type: ignore[attr-defined]
        sentinel = _make_under_threshold_sentinel('hi')

        result = self._detect_and_handle(orch, [sentinel])

        assert result is sentinel
        assert orch._gate_callbacks == [('under_threshold', 1)]  # type: ignore[attr-defined]

    def test_breach_dispatches_callback_and_resets_counter(self) -> None:
        orch, executor = _make_orchestrator_with_executor()
        executor._consecutive_plain_text_blocks = 3  # type: ignore[attr-defined]
        sentinel = _make_breach_sentinel('hi')

        result = self._detect_and_handle(orch, [sentinel])

        assert isinstance(result, MessageAction)
        assert result.wait_for_response is True
        assert 'Protocol error' in result.content
        assert 'hi' not in result.content
        assert orch._gate_callbacks == [('threshold_breached', 3)]  # type: ignore[attr-defined]
        assert executor._consecutive_plain_text_blocks == 0  # type: ignore[attr-defined]

    def test_real_tool_call_resets_counter(self) -> None:
        orch, executor = _make_orchestrator_with_executor()
        executor._consecutive_plain_text_blocks = 2  # type: ignore[attr-defined]
        real = MessageAction(content='tool call result')

        result = self._detect_and_handle(orch, [real])

        assert result is real
        assert executor._consecutive_plain_text_blocks == 0  # type: ignore[attr-defined]
        assert orch._gate_callbacks == []  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_normal_step_keeps_under_threshold_gate_counter() -> None:
    orch, _executor = _make_orchestrator_with_executor()
    sentinel = _make_under_threshold_sentinel('plain answer')
    orch._check_exit_command = lambda _state: None  # type: ignore[method-assign]
    orch._execute_llm_step_async = AsyncMock(return_value=sentinel)  # type: ignore[method-assign]
    orch._reset_step_recovery_counters = MagicMock()  # type: ignore[method-assign]
    orch.memory_manager = SimpleNamespace(
        condense_history=AsyncMock(
            return_value=SimpleNamespace(pending_action=None, events=[])
        )
    )

    result = await orch._astep_normal_path(SimpleNamespace())

    assert result is sentinel
    orch._reset_step_recovery_counters.assert_not_called()  # type: ignore[attr-defined]


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
