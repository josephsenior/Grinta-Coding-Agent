"""Tests for canonical task state reducers and rendering."""

from __future__ import annotations

from backend.context.canonical_state import (
    CanonicalTaskState,
    apply_canonical_patch,
    load_canonical_state,
    reduce_events_into_state,
    reduce_snapshot_into_state,
    render_canonical_state_for_prompt,
    save_canonical_state,
    validate_canonical_state_for_compaction,
)
from backend.ledger.action import CmdRunAction, MessageAction, TaskTrackingAction
from backend.ledger.event import EventSource
from backend.ledger.observation import CmdOutputObservation, TerminalObservation


def _user(text: str, event_id: int) -> MessageAction:
    event = MessageAction(content=text)
    event.source = EventSource.USER
    event.id = event_id
    return event


def _cmd(command: str, event_id: int) -> CmdRunAction:
    event = CmdRunAction(command=command)
    event.id = event_id
    return event


def _output(
    command: str, content: str, event_id: int, exit_code: int
) -> CmdOutputObservation:
    event = CmdOutputObservation(content=content, command=command, exit_code=exit_code)
    event.id = event_id
    return event


def _tasks(task_list: list[dict], event_id: int) -> TaskTrackingAction:
    event = TaskTrackingAction(command='update', task_list=task_list)
    event.id = event_id
    return event


def test_reducer_tracks_latest_directive_and_verification() -> None:
    events = [
        _user('Fix the failing parser tests', 1),
        _cmd('pytest backend/tests/unit/test_parser.py', 2),
        _output('pytest backend/tests/unit/test_parser.py', '1 failed', 3, 1),
        _cmd('pytest backend/tests/unit/test_parser.py', 4),
        _output('pytest backend/tests/unit/test_parser.py', '2 passed', 5, 0),
    ]

    canonical = reduce_events_into_state(events, CanonicalTaskState(), persist=False)

    assert canonical.objective == 'Fix the failing parser tests'
    assert canonical.latest_directive == 'Fix the failing parser tests'
    assert canonical.verification.command == 'pytest backend/tests/unit/test_parser.py'
    assert canonical.verification.status == 'passed'
    assert canonical.verification.exit_code == 0


def test_reducer_preserves_task_tracker_as_next_action_and_checkpoint() -> None:
    events = [
        _user('Build the demo app', 1),
        _tasks(
            [
                {
                    'id': '1',
                    'description': 'Create foundation modules',
                    'status': 'done',
                },
                {
                    'id': '2',
                    'description': 'Implement node.py',
                    'status': 'in_progress',
                },
                {'id': '3', 'description': 'Add tests', 'status': 'todo'},
            ],
            2,
        ),
    ]

    canonical = reduce_events_into_state(events, CanonicalTaskState(), persist=False)
    rendered = render_canonical_state_for_prompt(canonical, char_budget=1600)

    assert canonical.next_action == 'Implement node.py'
    assert '[in_progress] Implement node.py' in canonical.active_plan
    assert 'current: Implement node.py' in canonical.implementation_checkpoint
    assert 'remaining: Add tests' in canonical.implementation_checkpoint
    assert 'Task tracker' in rendered


def test_background_task_persists_until_terminal_resolution() -> None:
    running = _output(
        'pytest -q',
        '[BACKGROUND_DETACH] session_id="terminal_7"',
        2,
        -2,
    )
    canonical = reduce_events_into_state(
        [_user('Run the suite', 1), running],
        CanonicalTaskState(),
        persist=False,
    )
    assert [task.session_id for task in canonical.background_tasks] == ['terminal_7']

    resolved = TerminalObservation(
        session_id='terminal_7',
        content='Process exited with code 0',
        state='exited',
    )
    resolved.id = 3
    canonical = reduce_events_into_state(
        [resolved],
        canonical,
        persist=False,
    )

    assert canonical.background_tasks == []


def test_failed_approaches_are_deduped_and_capped() -> None:
    snapshot = {
        'attempted_approaches': [
            {
                'type': 'command',
                'detail': 'pytest -q',
                'outcome': 'FAILED (exit=1): same failure',
            }
        ]
        * 20,
    }

    canonical = reduce_snapshot_into_state(
        snapshot,
        CanonicalTaskState(),
        latest_event_id=10,
    )

    assert len(canonical.failed_approaches) == 1
    assert canonical.failed_approaches[0].detail == 'pytest -q'


def test_recent_work_ledger_dedupes_commands_and_files() -> None:
    snapshot = {
        'files_touched': {
            'backend/context/prompt_window.py': {
                'action': 'read',
                'sha256': 'abcdef1234567890',
            }
        },
        'recent_commands': [
            {'command': 'pytest -q', 'output': 'failed\nline 1'},
            {'command': 'pytest -q', 'output': 'passed'},
        ],
    }

    canonical = reduce_snapshot_into_state(
        snapshot,
        CanonicalTaskState(),
        latest_event_id=10,
    )
    rendered = render_canonical_state_for_prompt(canonical, char_budget=1200)

    assert 'Recent work ledger' in rendered
    assert rendered.count('pytest -q') == 1
    assert 'backend/context/prompt_window.py' in rendered


def test_llm_patch_cannot_overwrite_newer_facts() -> None:
    canonical = CanonicalTaskState()
    canonical = apply_canonical_patch(
        canonical,
        {'next_action': 'Run the narrow parser test'},
        event_id=20,
    )
    canonical = apply_canonical_patch(
        canonical,
        {'next_action': 'Repeat the stale broad suite'},
        event_id=10,
    )

    assert canonical.next_action == 'Run the narrow parser test'


def test_validation_and_render_preserve_required_fields_under_budget() -> None:
    events = [
        _user('Fix CLI rendering', 1),
        _cmd('pytest backend/tests/unit/cli/test_renderer.py', 2),
        _output(
            'pytest backend/tests/unit/cli/test_renderer.py',
            '1 failed, 4 passed',
            3,
            1,
        ),
    ]
    canonical = reduce_events_into_state(events, CanonicalTaskState(), persist=False)

    result = validate_canonical_state_for_compaction(canonical, events)
    rendered = render_canonical_state_for_prompt(canonical, char_budget=900)

    assert result.ok
    assert 'Fix CLI rendering' in rendered
    assert 'Latest verification: FAILED' in rendered
    assert len(rendered) <= 900


def test_canonical_state_reload_preserves_current_fields(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        'backend.context.canonical_state.canonical_state_path',
        lambda state=None: tmp_path / 'canonical_task_state.json',
    )
    events = [
        _user('Repair context reload', 1),
        _cmd('pytest backend/tests/unit/context/test_canonical_state.py', 2),
        _output(
            'pytest backend/tests/unit/context/test_canonical_state.py',
            '5 passed',
            3,
            0,
        ),
    ]
    canonical = reduce_events_into_state(events, CanonicalTaskState(), persist=False)

    save_canonical_state(canonical)
    reloaded = load_canonical_state()

    assert reloaded.latest_directive == 'Repair context reload'
    assert reloaded.verification.status == 'passed'
    assert reloaded.source_event_ids['verification'] == 3
