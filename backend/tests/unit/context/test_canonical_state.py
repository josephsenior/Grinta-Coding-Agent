"""Tests for canonical task state reducers and rendering."""

from __future__ import annotations

from backend.context.canonical_state import (
    CanonicalTaskState,
    apply_canonical_patch,
    clip_with_marker,
    load_canonical_state,
    reduce_events_into_state,
    reduce_snapshot_into_state,
    render_canonical_state_for_prompt,
    save_canonical_state,
    validate_canonical_state_for_compaction,
)
from backend.context.canonical_state.ops import (
    _merge_narrative,
    _narrative_overlap,
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


def test_clip_with_marker_passthrough_when_fits() -> None:
    text = 'short output'
    assert clip_with_marker(text, 100, prefer='tail') == text
    assert clip_with_marker(text, 100, prefer='head') == text


def test_clip_with_marker_tail_keeps_end_and_marks() -> None:
    # The actionable assertion line lives at the END of a traceback.
    body = 'noise line\n' * 200 + 'AssertionError: expected 3 got 4'
    clipped = clip_with_marker(body, 120, prefer='tail')
    assert len(clipped) <= 120
    assert 'AssertionError: expected 3 got 4' in clipped
    assert 'chars omitted' in clipped


def test_clip_with_marker_head_keeps_start_and_marks() -> None:
    body = 'START-MARKER' + ('x' * 500)
    clipped = clip_with_marker(body, 100, prefer='head')
    assert len(clipped) <= 100
    assert clipped.startswith('START-MARKER')
    assert 'chars omitted' in clipped


def test_verification_output_clip_preserves_failing_assertion() -> None:
    """A long failing verification output must keep its final assertion line."""
    long_output = (
        'collecting ...\n' * 400
        + 'E   AssertionError: parser dropped the trailing token'
    )
    events = [
        _user('Fix the parser', 1),
        _cmd('pytest backend/tests/unit/test_parser.py', 2),
        _output(
            'pytest backend/tests/unit/test_parser.py',
            long_output,
            3,
            1,
        ),
    ]
    canonical = reduce_events_into_state(events, CanonicalTaskState(), persist=False)

    # The durable canonical output keeps the actionable failing line + marker.
    assert 'AssertionError: parser dropped the trailing token' in (
        canonical.verification.output
    )
    assert '... (truncated) ...' in canonical.verification.output

    # The prompt render stays bounded and still surfaces the failing tail.
    rendered = render_canonical_state_for_prompt(canonical, char_budget=2000)
    assert 'AssertionError: parser dropped the trailing token' in rendered


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


def test_explicit_pivot_records_superseding_directive() -> None:
    events = [
        _user('Refactor the parser module for readability', 1),
        _user('actually, forget the refactor, just fix the failing test', 2),
    ]
    canonical = reduce_events_into_state(events, CanonicalTaskState(), persist=False)
    rendered = render_canonical_state_for_prompt(canonical, char_budget=2000)

    # Original objective is preserved verbatim ...
    assert canonical.objective == 'Refactor the parser module for readability'
    # ... and the pivot is surfaced separately, never overwriting it.
    assert (
        canonical.superseding_directive
        == 'actually, forget the refactor, just fix the failing test'
    )
    assert 'Objective superseded by' in rendered
    assert 'just fix the failing test' in canonical.next_action


def test_additive_refinement_does_not_supersede_objective() -> None:
    """Quality-safety: a clarification must NOT trigger supersession."""
    events = [
        _user('Build the export feature', 1),
        _user('also add unit tests for it', 2),
    ]
    canonical = reduce_events_into_state(events, CanonicalTaskState(), persist=False)

    assert canonical.objective == 'Build the export feature'
    assert canonical.superseding_directive == ''


def test_superseding_directive_survives_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        'backend.context.canonical_state.canonical_state_path',
        lambda state=None: tmp_path / 'canonical_task_state.json',
    )
    events = [
        _user('Add a caching layer', 1),
        _user('scrap that, new task: migrate the database schema', 2),
    ]
    canonical = reduce_events_into_state(events, CanonicalTaskState(), persist=False)
    save_canonical_state(canonical)
    reloaded = load_canonical_state()

    assert reloaded.objective == 'Add a caching layer'
    assert 'migrate the database schema' in reloaded.superseding_directive


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


def test_narrative_summary_merged_across_compactions() -> None:
    """Compaction #2 must not overwrite the session-arc narrative from
    compaction #1 — it should merge them so 'Built from scratch' survives."""
    canonical = CanonicalTaskState()
    canonical = apply_canonical_patch(
        canonical,
        {
            'narrative_summary': (
                'Built a complete autograd engine from scratch in Python. '
                'Created 19 source files across autograd/, autograd/ops/, '
                'and autograd/jit/ packages.'
            ),
            'completed_tasks': 'All 10 operators, JIT pipeline, test suite',
        },
        event_id=80,
        source='structured_compactor',
    )
    original_narrative = canonical.narrative_summary
    assert 'from scratch' in original_narrative

    canonical = apply_canonical_patch(
        canonical,
        {
            'narrative_summary': (
                'Fixed a critical row-major indexing bug that affected '
                'SumOp, SoftmaxOp, and AddOp broadcasting.'
            ),
            'completed_tasks': (
                'All 10 operators, JIT pipeline, test suite, '
                'fixed row-major indexing bug'
            ),
        },
        event_id=100,
        source='structured_compactor',
    )

    assert 'from scratch' in canonical.narrative_summary
    assert 'row-major indexing bug' in canonical.narrative_summary
    assert 'Fixed a critical' in canonical.narrative_summary


def test_narrative_summary_replaced_when_high_overlap() -> None:
    """If the new narrative is a superset of the old one (high word overlap),
    the new one replaces the old — no unnecessary duplication."""
    canonical = CanonicalTaskState()
    canonical = apply_canonical_patch(
        canonical,
        {'narrative_summary': 'Built an autograd engine from scratch with 10 operators'},
        event_id=50,
    )
    canonical = apply_canonical_patch(
        canonical,
        {
            'narrative_summary': (
                'Built an autograd engine from scratch with 10 operators. '
                'Fixed row-major indexing bug. All 86 tests pass.'
            ),
        },
        event_id=80,
    )

    assert canonical.narrative_summary.count('from scratch') == 1


def test_completed_tasks_preserved_in_canonical_state() -> None:
    """completed_tasks from the compaction patch must be stored in the
    canonical state and rendered in the prompt."""
    canonical = CanonicalTaskState()
    canonical = apply_canonical_patch(
        canonical,
        {
            'completed_tasks': 'Tensor class, 10 operators, JIT pipeline, 86 tests',
            'narrative_summary': 'Built from scratch',
        },
        event_id=80,
    )

    assert 'Tensor class' in canonical.completed_tasks
    rendered = render_canonical_state_for_prompt(canonical)
    assert 'Work completed this session' in rendered
    assert 'Tensor class' in rendered


# ---------------------------------------------------------------------------
# _merge_narrative — direct unit tests
# ---------------------------------------------------------------------------


class TestMergeNarrative:
    """Direct tests for the _merge_narrative helper."""

    def test_empty_existing_returns_incoming(self):
        assert _merge_narrative('', 'Built engine from scratch') == 'Built engine from scratch'

    def test_empty_incoming_returns_existing(self):
        assert _merge_narrative('Built engine from scratch', '') == 'Built engine from scratch'

    def test_both_empty_returns_empty(self):
        assert _merge_narrative('', '') == ''

    def test_existing_substring_of_incoming_returns_incoming(self):
        existing = 'Built autograd engine from scratch'
        incoming = 'Built autograd engine from scratch. Fixed row-major bug. All tests pass.'
        result = _merge_narrative(existing, incoming)
        assert result == incoming
        assert result.count('from scratch') == 1

    def test_incoming_substring_of_existing_returns_existing(self):
        existing = 'Built engine. Fixed bug. Added tests. Wrote docs.'
        incoming = 'Built engine.'
        result = _merge_narrative(existing, incoming)
        assert result == existing

    def test_low_overlap_prepends_existing(self):
        existing = 'Built a complete autograd engine from scratch with 19 files'
        incoming = 'Fixed a critical row-major indexing bug in SumOp broadcasting'
        result = _merge_narrative(existing, incoming)
        assert 'from scratch' in result
        assert 'row-major' in result
        assert 'Recent:' in result

    def test_high_overlap_replaces_with_incoming(self):
        existing = 'Built autograd engine from scratch with 10 operators and JIT pipeline'
        incoming = 'Built autograd engine from scratch with 10 operators and JIT pipeline. Fixed indexing bug.'
        result = _merge_narrative(existing, incoming)
        assert result == incoming
        assert 'Recent:' not in result

    def test_respects_max_chars(self):
        existing = 'A' * 500
        incoming = 'B' * 500
        result = _merge_narrative(existing, incoming, max_chars=100)
        assert len(result) <= 100

    def test_merge_does_not_double_count_when_superset(self):
        """The demo1 bug: compaction #3 focused only on recent fixes, losing
        'from scratch'. _merge_narrative must prepend the original."""
        compaction_1 = (
            'Built a complete autograd engine from scratch in Python. '
            'Created 19 source files across autograd/, autograd/ops/, '
            'and autograd/jit/ packages.'
        )
        compaction_3 = (
            'Fixed a critical row-major indexing bug that affected '
            'SumOp, SoftmaxOp, and AddOp broadcasting.'
        )
        result = _merge_narrative(compaction_1, compaction_3)
        assert 'from scratch' in result
        assert 'row-major' in result
        assert 'Recent:' in result


# ---------------------------------------------------------------------------
# _narrative_overlap — direct unit tests
# ---------------------------------------------------------------------------


class TestNarrativeOverlap:
    """Direct tests for the _narrative_overlap helper."""

    def test_identical_strings_return_1(self):
        assert _narrative_overlap('hello world', 'hello world') == 1.0

    def test_empty_a_returns_0(self):
        assert _narrative_overlap('', 'anything') == 0.0

    def test_empty_b_returns_0(self):
        assert _narrative_overlap('anything', '') == 0.0

    def test_both_empty_returns_0(self):
        assert _narrative_overlap('', '') == 0.0

    def test_no_overlap_returns_0(self):
        assert _narrative_overlap('apple banana', 'cherry date') == 0.0

    def test_partial_overlap(self):
        result = _narrative_overlap('apple banana cherry', 'banana cherry date')
        # words_a = {apple, banana, cherry}, intersection = {banana, cherry}
        assert 0.5 < result < 0.7

    def test_case_insensitive(self):
        result = _narrative_overlap('Hello World', 'hello world')
        assert result == 1.0

    def test_superset_b_covers_all_a(self):
        result = _narrative_overlap('built engine', 'built engine fixed tests')
        assert result == 1.0
