"""Unit tests for backend.orchestration.action_scheduler."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.orchestration.action_scheduler import ActionScheduler


@dataclass
class _FakeAction:
    action: str
    name: str = ''
    path: str | None = None
    session_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class _FakeMCPAction:
    action: str = 'call_tool_mcp'
    name: str = ''

    @property
    def path(self) -> str | None:
        return None

    @property
    def session_id(self) -> str | None:
        return None


# ── Edge cases ───────────────────────────────────────────────────────────────


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


# ── Read-only batches ──────────────────────────────────────────────────────────


def test_read_only_batch_parallel() -> None:
    scheduler = ActionScheduler(enabled=True)
    actions = [_FakeAction('read'), _FakeAction('lsp_query')]
    decision = scheduler.decide_parallel_batch(actions)
    assert decision.should_execute_parallel is True
    assert decision.reason == 'parallel_safe_batch'
    assert list(decision.actions) == actions


def test_read_only_mcp_tools_parallel() -> None:
    scheduler = ActionScheduler(enabled=True)
    actions = [
        _FakeMCPAction(name='grep'),
        _FakeMCPAction(name='glob'),
        _FakeMCPAction(name='get_entity'),
    ]
    decision = scheduler.decide_parallel_batch(actions)
    assert decision.should_execute_parallel is True
    assert decision.reason == 'parallel_safe_batch'


# ── Same-type side-effect batches (new logic) ─────────────────────────────────


def test_same_type_file_write_different_paths_parallel() -> None:
    scheduler = ActionScheduler(enabled=True)
    actions = [
        _FakeAction('edit', path='/a.txt'),
        _FakeAction('edit', path='/b.txt'),
    ]
    decision = scheduler.decide_parallel_batch(actions)
    assert decision.should_execute_parallel is True
    assert decision.reason == 'parallel_safe_batch'


def test_same_type_file_write_same_path_sequential() -> None:
    scheduler = ActionScheduler(enabled=True)
    actions = [
        _FakeAction('edit', path='/same.txt'),
        _FakeAction('edit', path='/same.txt'),
    ]
    decision = scheduler.decide_parallel_batch(actions)
    assert decision.should_execute_parallel is False
    assert decision.reason == 'same_resource_conflict'


def test_same_type_file_edit_different_paths_parallel() -> None:
    scheduler = ActionScheduler(enabled=True)
    actions = [
        _FakeAction('edit', path='/a.py'),
        _FakeAction('edit', path='/b.py'),
    ]
    decision = scheduler.decide_parallel_batch(actions)
    assert decision.should_execute_parallel is True


def test_same_type_file_edit_same_path_sequential() -> None:
    scheduler = ActionScheduler(enabled=True)
    actions = [
        _FakeAction('edit', path='/same.py'),
        _FakeAction('edit', path='/same.py'),
    ]
    decision = scheduler.decide_parallel_batch(actions)
    assert decision.should_execute_parallel is False
    assert decision.reason == 'same_resource_conflict'


def test_same_type_terminal_different_sessions_parallel() -> None:
    scheduler = ActionScheduler(enabled=True)
    actions = [
        _FakeAction('terminal_run', session_id='sess-1'),
        _FakeAction('terminal_run', session_id='sess-2'),
    ]
    decision = scheduler.decide_parallel_batch(actions)
    assert decision.should_execute_parallel is True


def test_same_type_terminal_same_session_sequential() -> None:
    scheduler = ActionScheduler(enabled=True)
    actions = [
        _FakeAction('terminal_input', session_id='sess-1'),
        _FakeAction('terminal_read', session_id='sess-1'),
    ]
    decision = scheduler.decide_parallel_batch(actions)
    assert decision.should_execute_parallel is False
    assert decision.reason == 'same_resource_conflict'


# ── Mixed-type batches ────────────────────────────────────────────────────────


def test_mixed_type_batch_sequential() -> None:
    scheduler = ActionScheduler(enabled=True)
    actions = [_FakeAction('read'), _FakeAction('edit', path='/a.txt')]
    decision = scheduler.decide_parallel_batch(actions)
    assert decision.should_execute_parallel is False
    assert decision.reason == 'mixed_batch_sequential'


def test_read_plus_terminal_mixed_sequential() -> None:
    scheduler = ActionScheduler(enabled=True)
    actions = [_FakeAction('read'), _FakeAction('terminal_run')]
    decision = scheduler.decide_parallel_batch(actions)
    assert decision.should_execute_parallel is False
    assert decision.reason == 'mixed_batch_sequential'


def test_terminal_plus_edit_mixed_sequential() -> None:
    scheduler = ActionScheduler(enabled=True)
    actions = [
        _FakeAction('terminal_run', session_id='sess-1'),
        _FakeAction('edit', path='/a.py'),
    ]
    decision = scheduler.decide_parallel_batch(actions)
    assert decision.should_execute_parallel is False
    assert decision.reason == 'mixed_batch_sequential'


# ── Opaque MCP tools ──────────────────────────────────────────────────────────


def test_opaque_mcp_tool_forces_sequential() -> None:
    scheduler = ActionScheduler(enabled=True)
    actions = [
        _FakeAction('call_tool_mcp', name='random_api'),
        _FakeAction('read'),
    ]
    decision = scheduler.decide_parallel_batch(actions)
    assert decision.should_execute_parallel is False
    assert decision.reason == 'mixed_batch_sequential'


# ── Batch-size cap ─────────────────────────────────────────────────────────────


def test_batch_cap() -> None:
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
    assert len(decision.overflow) == 1


def test_default_max_parallel_batch_size() -> None:
    scheduler = ActionScheduler(enabled=True)
    assert scheduler.max_parallel_batch_size == 10
