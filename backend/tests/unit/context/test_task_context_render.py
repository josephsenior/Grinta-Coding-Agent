"""Tests for shared task/goal context renderers."""

from __future__ import annotations

from backend.context.render.task_context import (
    render_acceptance_gates,
    render_active_scope,
    render_goal_header,
    render_task_plan,
)


class _Canonical:
    objective = 'Build feature X'
    latest_directive = 'Also add tests'
    next_action = 'Run pytest'


def test_render_goal_header_includes_objective_and_next_action():
    lines = render_goal_header(_Canonical())
    joined = '\n'.join(lines)
    assert 'Build feature X' in joined
    assert 'Also add tests' in joined
    assert 'Run pytest' in joined


def test_render_active_scope_skips_done_tasks():
    task_plan = {
        'tasks': [
            {'id': '1', 'description': 'Done task', 'status': 'done'},
            {'id': '2', 'description': 'Active task', 'status': 'in_progress'},
        ]
    }
    lines = render_active_scope(task_plan)
    joined = '\n'.join(lines)
    assert 'Active task' in joined
    assert '(id=2)' in joined
    assert 'Done task' not in joined


def test_render_task_plan_includes_done_tasks_with_ids():
    task_plan = {
        'tasks': [
            {'id': '1', 'description': 'Done task', 'status': 'done'},
            {'id': '2', 'description': 'Active task', 'status': 'in_progress'},
        ]
    }
    lines = render_task_plan(task_plan)
    joined = '\n'.join(lines)
    assert '(id=1)' in joined
    assert '(id=2)' in joined
    assert 'Done task' in joined


def test_render_acceptance_gates_includes_assertions_and_ids():
    criteria = [
        {'id': 'ac-1', 'assertion': 'All tests pass', 'evidence': 'pytest green'},
    ]
    lines = render_acceptance_gates(criteria)
    joined = '\n'.join(lines)
    assert '[ac-1]' in joined
    assert 'All tests pass' in joined
    assert 'pytest green' in joined


def test_render_task_plan_empty_state():
    lines = render_task_plan([], show_empty=True)
    joined = '\n'.join(lines)
    assert 'no tasks configured yet' in joined
    assert 'task_tracker' in joined


def test_render_acceptance_gates_empty_state():
    lines = render_acceptance_gates([], show_empty=True)
    joined = '\n'.join(lines)
    assert 'no acceptance criteria defined yet' in joined
    assert 'acceptance_criteria' in joined
