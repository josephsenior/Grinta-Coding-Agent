"""Focused tests for .app-backed workspace state paths."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

from backend.context.compactor.strategies.smart_compactor import SmartCompactor
from backend.engine.tools import working_memory as wm
from backend.engine.tools.task_tracker import TaskTracker


def test_working_memory_writes_under_app_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda project_root=None: tmp_path,
    )
    wm.set_current_session_id('test-session')

    action = wm.build_working_memory_action(
        {'command': 'update', 'section': 'plan', 'content': 'next step'}
    )
    observation = wm.execute_working_memory(action)

    assert "Updated 'plan'" in observation.content
    memory_file = tmp_path / 'working_memory_test-session.json'
    assert memory_file.exists()
    assert json.loads(memory_file.read_text(encoding='utf-8'))['plan'] == 'next step'


def test_working_memory_update_all_sections_parses_markdown_headers(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda project_root=None: tmp_path,
    )
    wm.set_current_session_id('test-session')

    content = '## HYPOTHESIS\ntry X\n\n## FINDINGS\nit worked\n'
    action = wm.build_working_memory_action(
        {'command': 'update', 'section': 'all', 'content': content}
    )
    observation = wm.execute_working_memory(action)

    assert 'Updated sections: hypothesis, findings' in observation.content
    payload = json.loads(
        (tmp_path / 'working_memory_test-session.json').read_text(encoding='utf-8')
    )
    assert payload['hypothesis'].strip() == 'try X'
    assert payload['findings'].strip() == 'it worked'


def test_working_memory_clear_section_all_clears_all_sections(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda project_root=None: tmp_path,
    )
    wm.set_current_session_id('test-session')

    memory_file = tmp_path / 'working_memory_test-session.json'
    memory_file.write_text(
        json.dumps(
            {
                'hypothesis': 'h',
                'findings': 'f',
                'plan': 'p',
                '_last_updated': 'yesterday',
            }
        ),
        encoding='utf-8',
    )

    action = wm.build_working_memory_action(
        {'command': 'clear_section', 'section': 'all'}
    )
    observation = wm.execute_working_memory(action)

    assert 'Cleared all sections' in observation.content
    payload = json.loads(memory_file.read_text(encoding='utf-8'))
    for section in ('hypothesis', 'findings', 'plan'):
        assert section not in payload


def test_scratchpad_sync_is_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda project_root=None: tmp_path,
    )
    wm.set_current_session_id('test-session')
    notes = {'plan': 'keep the hot path deterministic'}

    assert wm.sync_scratchpad_to_working_memory(notes) == ['plan']
    assert wm.sync_scratchpad_to_working_memory(notes) == []

    payload = json.loads(
        (tmp_path / 'working_memory_test-session.json').read_text(encoding='utf-8')
    )
    assert payload['plan'].count('keep the hot path deterministic') == 1


def test_task_tracker_persists_active_plan_under_app_dir(tmp_path, monkeypatch) -> None:
    from backend.engine.tools.working_memory import set_current_session_id

    set_current_session_id(None)
    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda project_root=None: tmp_path,
    )
    tracker = TaskTracker(tmp_path)
    task_list = [{'id': '1', 'description': 'Do it', 'status': 'in_progress'}]

    tracker.save_to_file(task_list)

    assert tracker.path == tmp_path / '.session_context_unbound' / 'active_plan.json'
    assert tracker.load_from_file() == [
        {
            'id': '1',
            'description': 'Do it',
            'status': 'in_progress',
            'result': None,
            'tags': [],
            'subtasks': [],
        }
    ]


def test_task_tracker_save_retries_transient_replace_error(
    tmp_path, monkeypatch
) -> None:
    from backend.engine.tools.working_memory import set_current_session_id

    set_current_session_id(None)
    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda project_root=None: tmp_path,
    )
    tracker = TaskTracker(tmp_path)
    task_list = [{'id': '1', 'description': 'Do it', 'status': 'in_progress'}]
    real_replace = os.replace
    calls = {'count': 0}

    def flaky_replace(src, dst):
        calls['count'] += 1
        if calls['count'] == 1:
            raise PermissionError(5, 'Access is denied')
        return real_replace(src, dst)

    with patch(
        'backend.persistence.file_store.atomic_write.os.replace',
        side_effect=flaky_replace,
    ):
        tracker.save_to_file(task_list)

    assert calls['count'] >= 2
    assert tracker.load_from_file()[0]['description'] == 'Do it'


def test_task_tracker_concurrent_save_uses_unique_temp_files(
    tmp_path, monkeypatch
) -> None:
    """Concurrent saves must not share one fixed .tmp path (WinError 2 on replace)."""
    from concurrent.futures import ThreadPoolExecutor

    from backend.engine.tools.working_memory import set_current_session_id

    set_current_session_id(None)
    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda project_root=None: tmp_path,
    )
    tracker = TaskTracker(tmp_path)
    errors: list[Exception] = []

    def save(i: int) -> None:
        try:
            tracker.save_to_file(
                [{'id': '1', 'description': f'task {i}', 'status': 'todo'}]
            )
        except Exception as exc:
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(save, range(24)))

    assert not errors
    assert tracker.path.exists()
    assert tracker.load_from_file()[0]['description'].startswith('task ')


def test_acceptance_criteria_store_is_session_scoped(tmp_path, monkeypatch) -> None:
    from backend.core.criteria.acceptance_criteria_store import AcceptanceCriteriaStore
    from backend.engine.tools.working_memory import set_current_session_id

    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda project_root=None: tmp_path,
    )
    set_current_session_id('session-a')
    store_a = AcceptanceCriteriaStore()
    store_a.save_to_file([{'assertion': 'Tests pass', 'source': 'stated'}])

    set_current_session_id('session-b')
    store_b = AcceptanceCriteriaStore()
    assert store_b.load_from_file() == []
    assert store_b.path == tmp_path / 'acceptance_criteria_session-b.json'
    assert store_a.path == tmp_path / 'acceptance_criteria_session-a.json'
    set_current_session_id(None)


def test_task_tracker_is_session_scoped_when_bound(tmp_path, monkeypatch) -> None:
    from backend.engine.tools.working_memory import set_current_session_id

    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda project_root=None: tmp_path,
    )
    set_current_session_id('session-a')
    tracker_a = TaskTracker()
    tracker_a.save_to_file([{'id': '1', 'description': 'A', 'status': 'todo'}])

    set_current_session_id('session-b')
    tracker_b = TaskTracker()
    assert tracker_b.load_from_file() == []
    assert tracker_b.path == tmp_path / 'active_plan_session-b.json'
    set_current_session_id(None)


def test_smart_compactor_reads_in_progress_ids_from_app_plan(
    tmp_path, monkeypatch
) -> None:
    from backend.engine.tools.working_memory import set_current_session_id

    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda project_root=None: tmp_path,
    )
    set_current_session_id('compact-test')
    plan_file = tmp_path / 'active_plan_compact-test.json'
    plan_file.parent.mkdir(parents=True, exist_ok=True)
    plan_file.write_text(
        json.dumps(
            [
                {'id': '1', 'description': 'one', 'status': 'done'},
                {'id': '2', 'description': 'two', 'status': 'in_progress'},
            ]
        ),
        encoding='utf-8',
    )

    compactor = SmartCompactor(llm=None)

    assert compactor._load_in_progress_task_ids() == {'2'}
