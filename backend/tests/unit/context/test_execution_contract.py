"""Tests for JSON-backed execution contract projection."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from backend.context.prompt.context_packet import build_context_packet
from backend.context.render.execution_contract import build_execution_contract
from backend.task_state.models import (
    ContractItem,
    TaskContract,
    TaskPlan,
    TaskState,
    TrackedTask,
)


def test_build_execution_contract_loads_tasks_from_json_store():
    tasks = [
        {'id': '1', 'description': 'Ship API', 'status': 'in_progress'},
        {'id': '2', 'description': 'Add tests', 'status': 'todo'},
    ]
    criteria = [
        {
            'id': 'ac-1',
            'assertion': 'pytest passes',
            'evidence': '',
            'source': 'stated',
        },
    ]
    with patch(
        'backend.context.render.execution_contract._load_task_state_safe',
        return_value=None,
    ):
        with patch('backend.core.task_tracker.TaskTracker') as tracker_cls:
            tracker_cls.return_value.load_from_file.return_value = tasks
            with patch('backend.core.criteria.AcceptanceCriteriaStore') as store_cls:
                store_cls.return_value.load_from_file.return_value = criteria
                body = build_execution_contract(state=SimpleNamespace())

    assert '(id=1)' in body
    assert 'Ship API' in body
    assert '[ac-1]' in body


def test_build_execution_contract_shows_empty_states_when_unconfigured():
    with patch(
        'backend.context.render.execution_contract._load_task_state_safe',
        return_value=None,
    ):
        with patch('backend.core.task_tracker.TaskTracker') as tracker_cls:
            tracker_cls.return_value.load_from_file.return_value = []
            with patch('backend.core.criteria.AcceptanceCriteriaStore') as store_cls:
                store_cls.return_value.load_from_file.return_value = []
                body = build_execution_contract(
                    state=SimpleNamespace(),
                    show_empty_states=True,
                )

    assert 'no durable tasks recorded' in body
    assert 'no durable contract conditions recorded' in body


def test_context_packet_includes_empty_execution_contract_when_unconfigured(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        'backend.context.canonical_state.canonical_state_path',
        lambda state=None: tmp_path / 'canonical_task_state.json',
    )
    with patch(
        'backend.context.render.execution_contract._load_task_state_safe',
        return_value=None,
    ):
        with patch('backend.core.task_tracker.TaskTracker') as tracker_cls:
            tracker_cls.return_value.load_from_file.return_value = []
            with patch('backend.core.criteria.AcceptanceCriteriaStore') as store_cls:
                store_cls.return_value.load_from_file.return_value = []
                packet = build_context_packet(
                    [],
                    [],
                    state=SimpleNamespace(),
                    char_budget=2400,
                )

    assert packet is not None
    assert '<EXECUTION_CONTRACT>' in packet.content
    assert 'no durable tasks recorded' in packet.content
    assert 'no durable contract conditions recorded' in packet.content


def test_context_packet_includes_execution_contract_without_canonical_task_block(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        'backend.context.canonical_state.canonical_state_path',
        lambda state=None: tmp_path / 'canonical_task_state.json',
    )
    tasks = [{'id': '1', 'description': 'Wire pipeline', 'status': 'todo'}]
    with patch(
        'backend.context.render.execution_contract._load_task_state_safe',
        return_value=None,
    ):
        with patch('backend.core.task_tracker.TaskTracker') as tracker_cls:
            tracker_cls.return_value.load_from_file.return_value = tasks
            with patch('backend.core.criteria.AcceptanceCriteriaStore') as store_cls:
                store_cls.return_value.load_from_file.return_value = []
                packet = build_context_packet(
                    [],
                    [],
                    state=SimpleNamespace(),
                    char_budget=2400,
                )

    assert packet is not None
    assert '<EXECUTION_CONTRACT>' in packet.content
    assert '(id=1)' in packet.content
    assert 'Wire pipeline' in packet.content
    assert 'Task tracker:' not in packet.content


def test_execution_contract_prefers_durable_task_state_over_legacy_stores():
    task_state = TaskState(
        contract=TaskContract(
            objective='Build the complete compiler and runtime',
            requirements=[
                ContractItem(
                    id='req-1',
                    text='All acceptance tests pass',
                    source='user',
                    status='unknown',
                )
            ],
        ),
        plan=TaskPlan(
            [
                TrackedTask(id='done', description='Fix runtime', status='done'),
                TrackedTask(id='next', description='Build backend', status='todo'),
            ]
        ),
    )
    with patch(
        'backend.context.render.execution_contract._load_task_state_safe',
        return_value=task_state,
    ):
        with patch('backend.core.task_tracker.TaskTracker') as legacy_tracker:
            body = build_execution_contract(
                state=SimpleNamespace(),
                show_empty_states=True,
            )

    legacy_tracker.assert_not_called()
    assert 'Recorded overall objective: Build the complete compiler and runtime' in body
    assert 'Recorded overall status: ACTIVE' in body
    assert 'open tasks: next' in body
    assert 'Build backend' in body
    assert '[req-1]' in body
    assert 'All acceptance tests pass' in body


def test_context_packet_reinjects_active_durable_task_state(tmp_path, monkeypatch):
    monkeypatch.setattr(
        'backend.context.canonical_state.canonical_state_path',
        lambda state=None: tmp_path / 'canonical_task_state.json',
    )
    task_state = TaskState(
        contract=TaskContract(objective='Finish the complete requested system'),
        plan=TaskPlan(
            [
                TrackedTask(id='phase-1', description='Runtime fixes', status='done'),
                TrackedTask(
                    id='phase-2',
                    description='Continue compiler backend',
                    status='in_progress',
                ),
            ]
        ),
    )
    with patch(
        'backend.context.render.execution_contract._load_task_state_safe',
        return_value=task_state,
    ):
        packet = build_context_packet(
            [],
            [],
            state=SimpleNamespace(),
            char_budget=2400,
        )

    assert packet is not None
    assert (
        'Recorded overall objective: Finish the complete requested system'
        in packet.content
    )
    assert 'Recorded overall status: ACTIVE' in packet.content
    assert 'open tasks: phase-2' in packet.content
    assert 'Continue compiler backend' in packet.content
