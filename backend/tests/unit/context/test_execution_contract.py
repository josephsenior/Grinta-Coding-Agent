"""Tests for JSON-backed execution contract projection."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from backend.context.prompt.context_packet import build_context_packet
from backend.context.render.execution_contract import build_execution_contract


def test_build_execution_contract_loads_tasks_from_json_store():
    tasks = [
        {'id': '1', 'description': 'Ship API', 'status': 'in_progress'},
        {'id': '2', 'description': 'Add tests', 'status': 'todo'},
    ]
    criteria = [
        {'id': 'ac-1', 'assertion': 'pytest passes', 'evidence': '', 'source': 'stated'},
    ]
    with patch('backend.core.task_tracker.TaskTracker') as tracker_cls:
        tracker_cls.return_value.load_from_file.return_value = tasks
        with patch(
            'backend.core.criteria.AcceptanceCriteriaStore'
        ) as store_cls:
            store_cls.return_value.render_for_prompt_lines.return_value = [
                '- Acceptance gates:',
                '  - [ac-1] pytest passes',
            ]
            body = build_execution_contract(state=SimpleNamespace())

    assert '(id=1)' in body
    assert 'Ship API' in body
    assert '[ac-1]' in body


def test_build_execution_contract_shows_empty_states_when_unconfigured():
    with patch('backend.core.task_tracker.TaskTracker') as tracker_cls:
        tracker_cls.return_value.load_from_file.return_value = []
        with patch(
            'backend.core.criteria.AcceptanceCriteriaStore'
        ) as store_cls:
            store_cls.return_value.render_for_prompt_lines.return_value = [
                '- Acceptance gates:',
                '  (no acceptance criteria defined yet — use acceptance_criteria(update) to scope outcomes)',
            ]
            body = build_execution_contract(
                state=SimpleNamespace(),
                show_empty_states=True,
            )

    assert 'no tasks configured yet' in body
    assert 'no acceptance criteria defined yet' in body


def test_context_packet_includes_empty_execution_contract_when_unconfigured(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        'backend.context.canonical_state.canonical_state_path',
        lambda state=None: tmp_path / 'canonical_task_state.json',
    )
    with patch('backend.core.task_tracker.TaskTracker') as tracker_cls:
        tracker_cls.return_value.load_from_file.return_value = []
        with patch(
            'backend.core.criteria.AcceptanceCriteriaStore'
        ) as store_cls:
            store_cls.return_value.render_for_prompt_lines.return_value = [
                '- Acceptance gates:',
                '  (no acceptance criteria defined yet — use acceptance_criteria(update) to scope outcomes)',
            ]
            packet = build_context_packet(
                [],
                [],
                state=SimpleNamespace(),
                char_budget=2400,
            )

    assert packet is not None
    assert '<EXECUTION_CONTRACT>' in packet.content
    assert 'no tasks configured yet' in packet.content
    assert 'no acceptance criteria defined yet' in packet.content


def test_context_packet_includes_execution_contract_without_canonical_task_block(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        'backend.context.canonical_state.canonical_state_path',
        lambda state=None: tmp_path / 'canonical_task_state.json',
    )
    tasks = [{'id': '1', 'description': 'Wire pipeline', 'status': 'todo'}]
    with patch('backend.core.task_tracker.TaskTracker') as tracker_cls:
        tracker_cls.return_value.load_from_file.return_value = tasks
        with patch(
            'backend.core.criteria.AcceptanceCriteriaStore'
        ) as store_cls:
            store_cls.return_value.render_for_prompt_lines.return_value = []
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
