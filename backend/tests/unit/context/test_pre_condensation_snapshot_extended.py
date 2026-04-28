"""Tests for pre_condensation_snapshot covering attempted approaches extraction."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from backend.context import pre_condensation_snapshot as snapshot_module
from backend.context.pre_condensation_snapshot import extract_snapshot
from backend.ledger.action.commands import CmdRunAction
from backend.ledger.action.files import FileEditAction
from backend.ledger.observation.commands import CmdOutputObservation
from backend.ledger.observation.error import ErrorObservation
from backend.ledger.observation.files import FileEditObservation


def _fake_event(name: str, **attrs):
    cls = type(name, (), {})
    event = cls()
    for key, value in attrs.items():
        setattr(event, key, value)
    return event


class TestPreCondensationSnapshot(unittest.TestCase):
    def test_snapshot_path_uses_agent_state_dir(self):
        from unittest.mock import patch

        agent = Path('C:/tmp/agent')
        with patch(
            'backend.core.workspace_resolution.workspace_agent_state_dir',
            return_value=agent,
        ):
            self.assertEqual(
                snapshot_module._snapshot_path(),
                agent / 'pre_condensation_snapshot.json',
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
            FileEditAction(
                path='test.py', command='replace_text', old_str='old', new_str='new'
            ),
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

        # Success command
        assert approaches[0]['type'] == 'command'
        assert 'pip install flask' in approaches[0]['detail']
        assert approaches[0]['outcome'] == 'SUCCESS'

        # Failed file edit
        assert approaches[1]['type'] == 'file_edit'
        assert 'test.py' in approaches[1]['detail']
        assert 'FAILED' in approaches[1]['outcome']

        # Failed command
        assert approaches[2]['type'] == 'command'
        assert 'pytest' in approaches[2]['detail']
        assert 'FAILED (exit=1)' in approaches[2]['outcome']

    def test_format_snapshot_for_injection(self):
        from backend.context.pre_condensation_snapshot import (
            format_snapshot_for_injection,
        )

        snapshot = {
            'events_condensed': 10,
            'files_touched': {'test.py': {'action': 'edit'}},
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

    def test_file_edit_observation_benign_error_word_is_success(self):
        """Diff/code mentioning 'error' must not mark the approach as FAILED."""
        events = [
            FileEditAction(
                path='app.py', command='replace_text', old_str='a', new_str='b'
            ),
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
            FileEditAction(path='x.py', command='create_file', old_str='', new_str=''),
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
        snapshot = {'files_touched': {}}

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
        snapshot = {'decisions': []}

        snapshot_module._extract_decisions(
            _fake_event('AgentThinkObservation', thought='🔍 SELF-REFLECTION: boilerplate'),
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

    def test_extract_commands_honors_limit_and_truncates_long_output(self):
        full_snapshot = {'recent_commands': [{}] * snapshot_module._MAX_COMMANDS}
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

        assert len(snapshot['attempted_approaches']) == snapshot_module._MAX_ATTEMPTED_APPROACHES

    def test_process_event_for_approaches_returns_pending_for_unhandled_event(self):
        pending = {'type': 'command', 'detail': 'pytest'}

        result = snapshot_module._process_event_for_approaches(
            _fake_event('UnknownObservation'), [], pending
        )

        assert result == pending

    def test_save_load_and_delete_snapshot(self):
        snapshot_path = Path(self.id().replace('.', '_') + '.json')
        snapshot = {'files_touched': {'a.py': {'action': 'edit'}}, 'recent_errors': [], 'decisions': []}

        try:
            with patch.object(snapshot_module, '_snapshot_path', return_value=snapshot_path):
                snapshot_module.save_snapshot(snapshot)
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

    def test_load_snapshot_returns_none_when_file_missing(self):
        missing = Path(self.id().replace('.', '_') + '_missing.json')

        with patch.object(snapshot_module, '_snapshot_path', return_value=missing):
            assert snapshot_module.load_snapshot() is None

    def test_delete_snapshot_swallows_oserror(self):
        snapshot_path = Path('delete_snapshot_oserror.json')

        with patch.object(snapshot_module, '_snapshot_path', return_value=snapshot_path), patch.object(
            Path, 'exists', return_value=True
        ), patch.object(Path, 'unlink', side_effect=OSError('locked')):
            snapshot_module.delete_snapshot()

    def test_format_helpers_cover_empty_and_populated_sections(self):
        assert snapshot_module._format_files_section({}) == []
        assert snapshot_module._format_errors_section([]) == []
        assert snapshot_module._format_decisions_section([]) == []
        assert snapshot_module._format_commands_section([]) == []
        assert snapshot_module._format_approaches_section([]) == []

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

        assert files[-1] == '  edit: a.py'
        assert errors[-1] == '  • boom'
        assert decisions[-1] == '  • choose branch a'
        assert commands[-2] == '  $ pytest'
        assert commands[-1] == '    → ok'
        assert 'FAILED approaches' in approaches[1]
        assert 'Succeeded approaches:' in approaches[-2]
