"""Focused tests for .app-backed workspace state paths."""

from __future__ import annotations

import json

from backend.context.compactor.strategies.smart_compactor import SmartCompactor
from backend.engine.tools import working_memory as wm
from backend.engine.tools.task_tracker import TaskTracker


def test_working_memory_writes_under_app_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda project_root=None: tmp_path,
    )

    action = wm.build_working_memory_action(
        {'command': 'update', 'section': 'plan', 'content': 'next step'}
    )

    assert "Updated 'plan'" in action.thought
    memory_file = tmp_path / 'working_memory.json'
    assert memory_file.exists()
    assert json.loads(memory_file.read_text(encoding='utf-8'))['plan'] == 'next step'


def test_working_memory_update_all_sections_parses_markdown_headers(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda project_root=None: tmp_path,
    )

    content = '## HYPOTHESIS\ntry X\n\n## FINDINGS\nit worked\n'
    action = wm.build_working_memory_action(
        {'command': 'update', 'section': 'all', 'content': content}
    )

    assert 'Updated sections: hypothesis, findings' in action.thought
    payload = json.loads((tmp_path / 'working_memory.json').read_text(encoding='utf-8'))
    assert payload['hypothesis'].strip() == 'try X'
    assert payload['findings'].strip() == 'it worked'


def test_working_memory_clear_section_all_clears_all_sections(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda project_root=None: tmp_path,
    )

    memory_file = tmp_path / 'working_memory.json'
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

    action = wm.build_working_memory_action({'command': 'clear_section', 'section': 'all'})

    assert 'Cleared all sections' in action.thought
    payload = json.loads(memory_file.read_text(encoding='utf-8'))
    for section in ('hypothesis', 'findings', 'plan'):
        assert section not in payload


def test_task_tracker_persists_active_plan_under_app_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda project_root=None: tmp_path,
    )
    tracker = TaskTracker(tmp_path)
    task_list = [{'id': '1', 'description': 'Do it', 'status': 'doing'}]

    tracker.save_to_file(task_list)

    assert tracker.path == tmp_path / 'active_plan.json'
    assert tracker.load_from_file() == [
        {
            'id': '1',
            'description': 'Do it',
            'status': 'doing',
            'result': None,
            'tags': [],
            'subtasks': [],
        }
    ]


def test_smart_compactor_reads_doing_ids_from_app_plan(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda project_root=None: tmp_path,
    )
    plan_file = tmp_path / 'active_plan.json'
    plan_file.parent.mkdir(parents=True, exist_ok=True)
    plan_file.write_text(
        json.dumps(
            [
                {'id': '1', 'description': 'one', 'status': 'done'},
                {'id': '2', 'description': 'two', 'status': 'doing'},
            ]
        ),
        encoding='utf-8',
    )

    compactor = SmartCompactor(llm=None)

    assert compactor._load_doing_task_ids() == {'2'}
