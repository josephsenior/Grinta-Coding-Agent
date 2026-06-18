"""Tests for pre_condensation_snapshot covering attempted approaches extraction."""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import backend.context.compaction.pre_condensation_snapshot as snapshot_module
from backend.context.compaction.pre_condensation_snapshot import extract_snapshot
from backend.ledger.action.agent import AgentThinkAction, TaskTrackingAction
from backend.ledger.action.commands import CmdRunAction
from backend.ledger.action.files import FileEditAction
from backend.ledger.action.message import MessageAction
from backend.ledger.event import EventSource
from backend.ledger.observation.commands import CmdOutputObservation
from backend.ledger.observation.error import ErrorObservation
from backend.ledger.observation.files import FileEditObservation, FileReadObservation


def _fake_event(name: str, **attrs):
    cls = type(name, (), {})
    event = cls()
    for key, value in attrs.items():
        setattr(event, key, value)
    return event


def _assert_approach(
    approach: dict[str, str],
    *,
    expected_type: str,
    detail_contains: str,
    outcome_contains: str,
) -> None:
    assert approach['type'] == expected_type
    assert detail_contains in approach['detail']
    assert outcome_contains in approach['outcome']


class TestPreCondensationSnapshot(unittest.TestCase):
    def test_snapshot_path_uses_agent_state_dir(self):
        from unittest.mock import patch

        from backend.engine.tools.working_memory import set_current_session_id

        agent = Path('C:/tmp/agent')
        with patch(
            'backend.core.workspace_resolution.workspace_agent_state_dir',
            return_value=agent,
        ):
            set_current_session_id(None)
            self.assertEqual(
                snapshot_module._snapshot_path(),
                agent / '.session_context_unbound' / 'pre_condensation_snapshot.json',
            )
            set_current_session_id('sess-42')
            self.assertEqual(
                snapshot_module._snapshot_path(),
                agent / 'pre_condensation_snapshot_sess-42.json',
            )

    def test_extract_snapshot_attempted_approaches(self):
        # Setup events
        events = [
            CmdRunAction(command='pip install flask'),
            CmdOutputObservation(
                content='Successfully installed',
                command='pip install flask',
                exit_code=0,
            ),
            FileEditAction(path='test.py', command='edit', new_str='new'),
            ErrorObservation(content='Match not found'),
            CmdRunAction(command='pytest'),
            CmdOutputObservation(
                content='FAILED tests/test_x.py', command='pytest', exit_code=1
            ),
        ]

        # Run
        snapshot = extract_snapshot(events)

        # Verify
        approaches = snapshot['attempted_approaches']
        assert len(approaches) == 3
        _assert_approach(
            approaches[0],
            expected_type='command',
            detail_contains='pip install flask',
            outcome_contains='SUCCESS',
        )
        _assert_approach(
            approaches[1],
            expected_type='file_edit',
            detail_contains='test.py',
            outcome_contains='FAILED',
        )
        _assert_approach(
            approaches[2],
            expected_type='command',
            detail_contains='pytest',
            outcome_contains='FAILED (exit=1)',
        )

    def test_extract_snapshot_records_test_results(self):
        events = [
            CmdRunAction(command='python -m pytest -q'),
            CmdOutputObservation(
                content='2 passed in 0.10s',
                command='python -m pytest -q',
                exit_code=0,
            ),
            CmdRunAction(command='npm test'),
            CmdOutputObservation(
                content='FAIL src/app.test.ts\nexpected true',
                command='npm test',
                exit_code=1,
            ),
        ]

        snapshot = extract_snapshot(events)

        assert snapshot['test_results'] == [
            {
                'command': 'python -m pytest -q',
                'status': 'passed',
                'exit_code': 0,
                'output': '2 passed in 0.10s',
            },
            {
                'command': 'npm test',
                'status': 'failed',
                'exit_code': 1,
                'output': 'FAIL src/app.test.ts\nexpected true',
            },
        ]

    def test_extract_snapshot_records_file_hashes(self):
        events = [
            FileReadObservation(path='src/read.py', content='print("read")\n'),
            FileEditAction(
                path='src/write.py',
                command='create_file',
                file_text='print("write")\n',
            ),
            FileEditObservation(
                content='edited',
                path='src/edit.py',
                new_content='print("edit")\n',
                new_content_hash='abc123def456',
            ),
        ]

        snapshot = extract_snapshot(events)

        files = snapshot['files_touched']
        assert files['src/read.py']['hash_source'] == 'read_observation'
        assert files['src/read.py']['size'] == len('print("read")\n')
        assert files['src/write.py']['hash_source'] == 'edit_payload'
        assert files['src/write.py']['type'] == 'edit'
        assert files['src/edit.py']['sha256'] == 'abc123def456'
        assert files['src/edit.py']['hash_source'] == 'edit_observation'

    def test_extract_snapshot_records_invalidated_assumptions(self):
        events = [
            AgentThinkAction(
                thought='Assumption invalidated: the parser error was not caused by TOML.'
            ),
            AgentThinkAction(thought='Use the simpler branch here'),
        ]

        snapshot = extract_snapshot(events)

        assert snapshot['invalidated_assumptions'] == [
            'Assumption invalidated: the parser error was not caused by TOML.'
        ]
        assert snapshot['decisions'] == ['Use the simpler branch here']

    def test_extract_snapshot_skips_condensation_control_noise(self):
        events = [
            AgentThinkAction(thought='Memory condensed. Resuming task.'),
            AgentThinkAction(thought='Fix config binding for the compactor.'),
        ]

        snapshot = extract_snapshot(events)

        assert snapshot['decisions'] == ['Fix config binding for the compactor.']

    def test_extract_snapshot_records_task_tracker_state(self):
        action = TaskTrackingAction(
            command='update',
            task_list=[
                {'id': '1', 'description': 'Create skeleton files', 'status': 'done'},
                {
                    'id': '2',
                    'description': 'Implement node.py',
                    'status': 'in_progress',
                },
                {'id': '3', 'description': 'Write tests', 'status': 'todo'},
            ],
        )
        action.id = 42

        snapshot = extract_snapshot([action])

        assert snapshot['task_plan']['event_id'] == 42
        assert snapshot['task_plan']['next_action'] == 'Implement node.py'
        assert snapshot['task_plan']['tasks'][0]['status'] == 'done'

    def test_extract_snapshot_skips_unstructured_long_thought_as_decision(self):
        thought = 'Let me think through the plan and strategy. ' * 40

        snapshot = extract_snapshot([AgentThinkAction(thought=thought)])

        assert snapshot['decisions'] == []

    def test_extract_snapshot_records_user_directives_and_background_task(self):
        first = MessageAction(content='Fix long-running compaction')
        first.source = EventSource.USER
        latest = MessageAction(content='Also preserve background processes')
        latest.source = EventSource.USER
        output = CmdOutputObservation(
            content='[BACKGROUND_DETACH] still running',
            command='pytest -q',
            exit_code=-2,
        )
        output.metadata.suffix = 'detached session_id="terminal_9"'
        output.metadata.command_still_running = True

        snapshot = extract_snapshot([first, latest, output])

        assert snapshot['objective'] == 'Fix long-running compaction'
        assert snapshot['latest_directive'] == 'Also preserve background processes'
        assert snapshot['recent_user_messages'] == [
            {'text': 'Fix long-running compaction'},
            {'text': 'Also preserve background processes'},
        ]
        assert snapshot['background_tasks'] == [
            {
                'session_id': 'terminal_9',
                'command': 'pytest -q',
                'status': 'still running',
                'next_action': 'terminal_read(session_id="terminal_9")',
            }
        ]

    def test_format_snapshot_for_injection(self):
        from backend.context.compaction.pre_condensation_snapshot import (
            format_snapshot_for_injection,
        )

        snapshot = {
            'events_condensed': 10,
            'files_touched': {'test.py': {'action': 'edit'}},
            'invalidated_assumptions': [
                'Assumption invalidated: the timeout was not network-related.'
            ],
            'test_results': [
                {
                    'command': 'pytest -q',
                    'status': 'failed',
                    'exit_code': 1,
                    'output': 'FAILED test_parser.py',
                }
            ],
            'attempted_approaches': [
                {
                    'type': 'command',
                    'detail': 'pytest',
                    'outcome': 'FAILED (exit=1): FAILED tests/test_x.py',
                }
            ],
        }

        formatted = format_snapshot_for_injection(snapshot)
        assert '<RESTORED_CONTEXT>' in formatted
        assert 'Events condensed: 10' in formatted
        assert 'test.py' in formatted
        assert 'FAILED approaches' in formatted
        assert 'pytest' in formatted
        assert 'Test results before condensation' in formatted
        assert 'FAILED (exit=1): pytest -q' in formatted
        assert 'Invalidated assumptions' in formatted
        assert 'timeout was not network-related' in formatted

    def test_file_edit_observation_benign_error_word_is_success(self):
        """Diff/code mentioning 'error' must not mark the approach as FAILED."""
        events = [
            FileEditAction(path='app.py', command='edit', new_str='b'),
            FileEditObservation(
                content='+def handle_error():\n    pass\n',
                path='app.py',
            ),
        ]
        snapshot = extract_snapshot(events)
        approaches = snapshot['attempted_approaches']
        assert len(approaches) == 1
        assert approaches[0]['outcome'] == 'SUCCESS'

    def test_file_edit_observation_skipped_prefix_is_failure(self):
        events = [
            FileEditAction(path='x.py', command='create_file', file_text=''),
            FileEditObservation(
                content='SKIPPED: file already exists',
                path='x.py',
            ),
        ]
        snapshot = extract_snapshot(events)
        assert snapshot['attempted_approaches'][0]['outcome'].startswith('FAILED')

    def test_file_edit_observation_failure_detector_known_shapes(self):
        assert snapshot_module._file_edit_observation_indicates_failure(
            '[edit error: failed patch]'
        )
        assert snapshot_module._file_edit_observation_indicates_failure(
            'ERROR: validation failed'
        )
        assert snapshot_module._file_edit_observation_indicates_failure(
            'critical verification failure while editing'
        )
        assert not snapshot_module._file_edit_observation_indicates_failure(
            'diff mentions error but succeeded'
        )

    def test_extract_file_info_handles_reads_and_cmd_paths(self):
        snapshot: dict[str, Any] = {'files_touched': {}}

        snapshot_module._extract_file_info(
            _fake_event('FileReadObservation', path='src/app.py'), snapshot
        )
        snapshot_module._extract_file_info(
            _fake_event('CmdRunAction', command='tail "logs/output.txt"'), snapshot
        )

        assert snapshot['files_touched']['src/app.py'] == {
            'action': 'read',
            'type': 'read',
        }
        assert snapshot['files_touched']['logs/output.txt'] == {
            'action': 'read_via_cmd',
            'type': 'read',
        }

    def test_extract_errors_honors_limit(self):
        snapshot = {'recent_errors': ['x'] * snapshot_module._MAX_ERRORS}

        snapshot_module._extract_errors(
            _fake_event('ErrorObservation', content='boom'), snapshot
        )

        assert snapshot['recent_errors'] == ['x'] * snapshot_module._MAX_ERRORS

    def test_extract_decisions_skips_boilerplate_and_honors_limit(self):
        snapshot: dict[str, Any] = {'decisions': []}

        snapshot_module._extract_decisions(
            _fake_event(
                'AgentThinkObservation',
                thought='\U0001f50d SELF-REFLECTION: boilerplate',
            ),
            snapshot,
        )
        snapshot_module._extract_decisions(
            _fake_event('AgentThinkAction', thought='Use the simpler branch here'),
            snapshot,
        )

        assert snapshot['decisions'] == ['Use the simpler branch here']

        full_snapshot = {'decisions': ['d'] * snapshot_module._MAX_DECISIONS}
        snapshot_module._extract_decisions(
            _fake_event('AgentThinkAction', thought='another'), full_snapshot
        )
        assert full_snapshot['decisions'] == ['d'] * snapshot_module._MAX_DECISIONS

    def test_recoverable_tool_schema_errors_are_not_durable(self):
        snapshot: dict[str, Any] = {
            'recent_errors': [],
            'decisions': [],
            'invalidated_assumptions': [],
            'attempted_approaches': [],
        }
        error_text = (
            'Missing required argument "type" in tool call read. '
            'Recover by emitting one corrected tool call with strict JSON arguments.'
        )

        snapshot_module._extract_errors(
            _fake_event('ErrorObservation', content=error_text), snapshot
        )
        snapshot_module._extract_decisions(
            _fake_event('AgentThinkAction', thought=error_text), snapshot
        )
        snapshot_module._extract_invalidated_assumptions(
            _fake_event('ErrorObservation', content=error_text), snapshot
        )
        snapshot_module._extract_attempted_approaches(
            [
                _fake_event('CmdRunAction', command='read file'),
                _fake_event('ErrorObservation', content=error_text),
            ],
            snapshot,
        )

        assert snapshot['recent_errors'] == []
        assert snapshot['decisions'] == []
        assert snapshot['invalidated_assumptions'] == []
        assert snapshot['attempted_approaches'] == []

    def test_extract_commands_honors_limit_and_truncates_long_output(self):
        full_snapshot: dict[str, Any] = {
            'recent_commands': [{}] * snapshot_module._MAX_COMMANDS
        }
        snapshot_module._extract_commands(
            _fake_event('CmdRunAction', command='pytest'), full_snapshot
        )
        assert full_snapshot['recent_commands'] == [{}] * snapshot_module._MAX_COMMANDS

        snapshot = {'recent_commands': [{'command': 'pytest'}]}
        content = '\n'.join(f'line {i}' for i in range(12))
        snapshot_module._extract_commands(
            _fake_event('CmdOutputObservation', content=content), snapshot
        )

        assert '... (truncated) ...' in snapshot['recent_commands'][0]['output']

    def test_extract_attempted_approaches_honors_limit(self):
        snapshot = {
            'attempted_approaches': [{'type': 'command'}]
            * snapshot_module._MAX_ATTEMPTED_APPROACHES
        }

        snapshot_module._extract_attempted_approaches(
            [_fake_event('CmdRunAction', command='pytest')], snapshot
        )

        assert (
            len(snapshot['attempted_approaches'])
            == snapshot_module._MAX_ATTEMPTED_APPROACHES
        )

    def test_process_event_for_approaches_returns_pending_for_unhandled_event(self):
        pending = {'type': 'command', 'detail': 'pytest'}

        result = snapshot_module._process_event_for_approaches(
            _fake_event('UnknownObservation'), [], pending
        )

        assert result == pending

    def test_save_load_and_delete_snapshot(self):
        snapshot_path = Path(self.id().replace('.', '_') + '.json')
        staging_path = snapshot_path.with_name(f'.{snapshot_path.name}.staging')
        snapshot = {
            'files_touched': {'a.py': {'action': 'edit'}},
            'recent_errors': [],
            'decisions': [],
        }

        try:
            with (
                patch.object(
                    snapshot_module, '_snapshot_path', return_value=snapshot_path
                ),
                patch.object(
                    snapshot_module, '_snapshot_staging_path', return_value=staging_path
                ),
            ):
                snapshot_module.save_snapshot(snapshot)
                assert staging_path.exists()
                assert not snapshot_path.exists()
                assert snapshot_module.load_snapshot() == snapshot

                snapshot_module.commit_snapshot()
                assert snapshot_path.exists()
                assert snapshot_module.load_snapshot() == snapshot

                snapshot_path.write_text('{invalid', encoding='utf-8')
                assert snapshot_module.load_snapshot() is None

                snapshot_path.write_text('{}', encoding='utf-8')
                snapshot_module.delete_snapshot()
                assert not snapshot_path.exists()
        finally:
            if snapshot_path.exists():
                snapshot_path.unlink()
            if staging_path.exists():
                staging_path.unlink()

    def test_load_snapshot_returns_none_when_file_missing(self):
        missing = Path(self.id().replace('.', '_') + '_missing.json')

        with (
            patch.object(snapshot_module, '_snapshot_path', return_value=missing),
            patch.object(
                snapshot_module, '_snapshot_staging_path', return_value=missing
            ),
        ):
            assert snapshot_module.load_snapshot() is None

    def test_delete_snapshot_swallows_oserror(self):
        snapshot_path = Path('delete_snapshot_oserror.json')

        with (
            patch.object(snapshot_module, '_snapshot_path', return_value=snapshot_path),
            patch.object(Path, 'exists', return_value=True),
            patch.object(Path, 'unlink', side_effect=OSError('locked')),
        ):
            snapshot_module.delete_snapshot()

    def test_format_helpers_cover_empty_and_populated_sections(self):
        for formatter, payload in (
            (snapshot_module._format_files_section, {}),
            (snapshot_module._format_errors_section, []),
            (snapshot_module._format_decisions_section, []),
            (snapshot_module._format_invalidated_assumptions_section, []),
            (snapshot_module._format_commands_section, []),
            (snapshot_module._format_test_results_section, []),
            (snapshot_module._format_approaches_section, []),
        ):
            assert formatter(payload) == []  # type: ignore[arg-type]

        files = snapshot_module._format_files_section({'a.py': {'action': 'edit'}})
        errors = snapshot_module._format_errors_section(['boom'])
        decisions = snapshot_module._format_decisions_section(['choose branch a'])
        commands = snapshot_module._format_commands_section(
            [{'command': 'pytest', 'output': 'ok'}]
        )
        approaches = snapshot_module._format_approaches_section(
            [
                {'type': 'command', 'detail': 'pytest', 'outcome': 'FAILED: boom'},
                {'type': 'command', 'detail': 'ruff', 'outcome': 'SUCCESS'},
            ]
        )

        assert [files[-1], errors[-1], decisions[-1], commands[-2], commands[-1]] == [
            '  edit: a.py',
            '  \u2022 boom',
            '  \u2022 choose branch a',
            '  $ pytest',
            '    \u2192 ok',
        ]
        assert 'FAILED approaches' in approaches[1]
        assert 'Succeeded approaches:' in approaches[-2]
