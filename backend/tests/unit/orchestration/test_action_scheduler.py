"""Unit tests for backend.orchestration.action_scheduler."""

from __future__ import annotations

from dataclasses import dataclass

from backend.orchestration.action_scheduler import ActionScheduler


@dataclass
class _FakeAction:
    action: str
    name: str = ''


@dataclass
class _FakeMCPAction:
    action: str = 'call_tool_mcp'
    name: str = ''


def test_decide_parallel_batch_disabled() -> None:
    scheduler = ActionScheduler(enabled=False)
    decision = scheduler.decide_parallel_batch([_FakeAction('read')])
    assert decision.should_execute_parallel is False
    assert decision.reason == 'parallel_disabled'
    assert decision.actions == ()


def test_decide_parallel_batch_requires_multiple_actions() -> None:
    scheduler = ActionScheduler(enabled=True)
    decision = scheduler.decide_parallel_batch([_FakeAction('read')])
    assert decision.should_execute_parallel is False
    assert decision.reason == 'insufficient_actions'


def test_decide_parallel_batch_allows_parallel_safe_action_types() -> None:
    scheduler = ActionScheduler(enabled=True)
    actions = [_FakeAction('read'), _FakeAction('lsp_query')]
    decision = scheduler.decide_parallel_batch(actions)
    assert decision.should_execute_parallel is True
    assert decision.reason == 'parallel_safe_batch'
    assert list(decision.actions) == actions


def test_decide_parallel_batch_allows_parallel_safe_mcp_tools() -> None:
    scheduler = ActionScheduler(enabled=True)
    actions = [
        _FakeMCPAction(name='search_code'),
        _FakeMCPAction(name='get_entity'),
    ]
    decision = scheduler.decide_parallel_batch(actions)
    assert decision.should_execute_parallel is True
    assert decision.reason == 'parallel_safe_batch'


def test_decide_parallel_batch_degrades_mixed_batch_to_sequential() -> None:
    scheduler = ActionScheduler(enabled=True)
    actions = [_FakeAction('read'), _FakeAction('run')]
    decision = scheduler.decide_parallel_batch(actions)
    assert decision.should_execute_parallel is False
    assert decision.reason == 'mixed_batch_sequential'


def test_decide_parallel_batch_caps_large_batches() -> None:
    scheduler = ActionScheduler(enabled=True, max_parallel_batch_size=2)
    actions = [
        _FakeAction('read'),
        _FakeAction('read'),
        _FakeAction('read'),
    ]
    decision = scheduler.decide_parallel_batch(actions)
    assert decision.should_execute_parallel is True
    assert decision.reason == 'parallel_safe_batch_capped'
    assert len(decision.actions) == 2


def test_default_max_parallel_batch_size() -> None:
    scheduler = ActionScheduler(enabled=True)
    assert scheduler.max_parallel_batch_size == 10
