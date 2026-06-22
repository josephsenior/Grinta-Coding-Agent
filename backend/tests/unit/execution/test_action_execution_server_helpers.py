from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.execution.aes import helpers as h
from backend.ledger.action import MessageAction
from backend.ledger.observation import (
    ErrorObservation,
    FileEditObservation,
    FileReadObservation,
)


def _executor() -> SimpleNamespace:
    ex = SimpleNamespace()
    ex.username = 'u'
    ex._initial_cwd = 'C:/ws'
    ex.security_config = SimpleNamespace(execution_profile='hardened_local')
    ex.session_manager = SimpleNamespace(
        tool_registry=None, get_session=lambda _sid: None, close_session=MagicMock()
    )
    ex._terminal_session_seq = 0
    ex._terminal_sessions_awaiting_interaction = []
    ex._terminal_open_commands_no_interaction = []
    ex._terminal_read_cursor = {}
    ex._workspace_root = lambda: Path('C:/ws').resolve()
    ex._is_workspace_restricted_profile = lambda: True
    ex._resolve_effective_cwd = lambda requested_cwd, base_cwd=None: (
        h.resolve_effective_cwd(ex, requested_cwd, base_cwd)
    )
    ex._clear_terminal_read_cursor = MagicMock()
    ex._normalize_terminal_command = h.normalize_terminal_command
    return ex


def test_build_shell_git_and_env_commands() -> None:
    ex = _executor()
    cmd_ps = h.build_shell_git_config_command(ex, True)
    cmd_bash = h.build_shell_git_config_command(ex, False)
    assert '$env:GIT_AUTHOR_NAME = "u"' in cmd_ps
    assert '$env:GIT_AUTHOR_EMAIL = "u@example.com"' in cmd_ps
    assert 'export GIT_AUTHOR_NAME="u"' in cmd_bash
    assert 'GIT_COMMITTER_EMAIL="u@example.com"' in cmd_bash
    assert 'git config --global' not in cmd_ps
    assert 'git config --global' not in cmd_bash
    assert 'function global:env_check' in h.build_env_check_command(True)
    assert "alias env_check='" in h.build_env_check_command(False)


def test_uses_powershell_shell_contract_windows_and_session_fallback() -> None:
    ex = _executor()
    with patch('backend.execution.aes.helpers.OS_CAPS') as caps:
        caps.is_windows = False
        assert h.uses_powershell_shell_contract(ex) is False

    class PowerShellSession:
        pass

    ex.session_manager.get_session = lambda _sid: PowerShellSession()
    with patch('backend.execution.aes.helpers.OS_CAPS') as caps:
        caps.is_windows = True
        assert h.uses_powershell_shell_contract(ex) is True


def test_close_interactive_terminal_sessions_closes_terminal_prefix_only() -> None:
    ex = MagicMock()
    ex.session_manager.sessions = {
        'default': MagicMock(),
        'terminal_1': MagicMock(),
        'terminal_2': MagicMock(),
        'bg-abc': MagicMock(),
    }
    ex._terminal_sessions_awaiting_interaction = ['terminal_1']
    ex._terminal_read_cursor = {'terminal_1': 5}
    ex._terminal_empty_read_streak = {'terminal_1': 2}

    closed = h.close_interactive_terminal_sessions(ex)

    assert set(closed) == {'terminal_1', 'terminal_2'}
    assert ex.session_manager.close_session.call_count == 2
    assert 'terminal_1' not in ex._terminal_read_cursor
    assert 'terminal_1' not in ex._terminal_empty_read_streak


def test_strip_and_failure_signature_and_terminal_mode_hints() -> None:
    assert h.strip_ansi_obs_text('\x1b[31mred\x1b[0m') == 'red'
    assert h.extract_failure_signature('a\nb\nc\nd') == 'b | c | d'
    assert h.terminal_mode('snapshot') == 'snapshot'
    assert h.terminal_mode('weird') == 'delta'
    assert h.terminal_read_empty_hints(mode='delta', has_new_output=False)[
        'delta_empty'
    ]
    assert h.terminal_read_empty_hints(mode='snapshot', has_new_output=False)[
        'snapshot_empty'
    ]


def test_combined_structured_edit_diff_tracks_snapshot_changes(tmp_path) -> None:
    target = tmp_path / 'demo.txt'
    target.write_text('old\n', encoding='utf-8')
    snapshots = {target: ('old\n', 'demo.txt')}

    target.write_text('new\n', encoding='utf-8')

    diff = h._combined_structured_edit_diff(snapshots)
    assert diff is not None
    assert '--- demo.txt' in diff
    assert '+++ demo.txt' in diff
    assert '-old' in diff
    assert '+new' in diff


def test_structured_edit_verification_reports_python_compile_failure(tmp_path) -> None:
    target = tmp_path / 'demo.py'
    target.write_text('return 1\n', encoding='utf-8')
    snapshots = {target: ('def ok():\n    return 1\n', 'demo.py')}

    text, files, ok = h._structured_edit_verification_receipt(snapshots)

    assert ok is False
    assert 'syntax=failed' in text
    assert files[0]['syntax'] == 'failed'
    assert "'return' outside function" in files[0]['syntax_detail']


def test_workspace_resolution_and_path_validation() -> None:
    ex = _executor()
    assert h.resolve_effective_cwd(ex, None) == Path('C:/ws').resolve()
    assert h.resolve_effective_cwd(ex, 'src') == Path('C:/ws/src').resolve()
    with patch(
        'backend.execution.aes.helpers.path_is_within_workspace',
        return_value=False,
    ):
        err = h.validate_workspace_scoped_cwd(ex, 'cmd', '../outside')
    assert isinstance(err, ErrorObservation)


def test_validate_interactive_session_scope_closes_escaped_session() -> None:
    ex = _executor()
    s = SimpleNamespace(cwd='C:/outside')
    with patch(
        'backend.execution.aes.helpers.path_is_within_workspace',
        return_value=False,
    ):
        err = h.validate_interactive_session_scope(ex, 't1', s)
    assert isinstance(err, ErrorObservation)
    ex.session_manager.close_session.assert_called_once_with('t1')
    ex._clear_terminal_read_cursor.assert_called_once_with('t1')


def test_predict_and_evaluate_interactive_terminal_command() -> None:
    ex = _executor()
    with patch(
        'backend.execution.aes.helpers.path_is_within_workspace',
        return_value=True,
    ):
        cwd, err = h.predict_interactive_cwd_change(
            ex, 'cd sub', Path('C:/ws').resolve()
        )
    assert err is None and cwd is not None

    with patch(
        'backend.execution.aes.helpers.path_is_within_workspace',
        return_value=False,
    ):
        cwd2, err2 = h.predict_interactive_cwd_change(
            ex, 'cd ..\\..\\x', Path('C:/ws').resolve()
        )
    assert cwd2 is None and err2 is not None

    p, obs = h.evaluate_interactive_terminal_command(
        ex, 'echo x && echo y', Path('C:/ws')
    )
    assert p is None and isinstance(obs, ErrorObservation)


def test_detect_shell_mismatch_scaffold_and_grep_filter() -> None:
    mismatch = h.detect_powershell_in_bash_mismatch(
        'Get-Content "x.py"', '/bin/bash: Get-Content: command not found'
    )
    assert mismatch is not None and 'PowerShell cmdlet' in mismatch

    scaffold = h.detect_scaffold_setup_failure(
        'npm create vite@latest . -- --template react && npm install',
        'npm ERR! enoent Could not read package.json: no such file or directory',
    )
    assert scaffold is not None

    assert "[Grep: No lines matched pattern 'z+']" in h.apply_grep_filter('a\nb', 'z+')
    assert '[Grep Error: Invalid regex pattern' in h.apply_grep_filter('a', '(')


def test_terminal_ids_guardrails_and_cursor_helpers() -> None:
    ex = _executor()
    ex.session_manager.sessions = {'terminal_1': object()}
    assert h.next_terminal_session_id(ex) == 'terminal_2'
    assert h.normalize_terminal_command('  Echo   Hi ') == 'echo hi'

    ex._terminal_sessions_awaiting_interaction = [
        'terminal_1',
        'terminal_2',
        'terminal_3',
    ]
    ex._terminal_open_commands_no_interaction = ['echo x', 'echo x', 'echo x']
    err = h.terminal_open_guardrail_error(ex, 'echo x')
    assert isinstance(err, ErrorObservation)

    miss = h.missing_terminal_session_error(ex, 'terminal_999', operation='read')
    assert isinstance(miss, ErrorObservation)
    assert 'terminal_999' in miss.content

    h.advance_terminal_read_cursor(ex, 't', 42, mode='delta')
    assert h.get_terminal_read_cursor(ex, 't') == 42
    h.clear_terminal_read_cursor(ex, 't')
    assert h.get_terminal_read_cursor(ex, 't') == 0


def test_terminal_read_modes_and_resize() -> None:
    ex = _executor()
    session = SimpleNamespace(
        read_output=lambda: 'buf',
        read_output_since=lambda off: ('tail', off + 4, 0),
        resize=MagicMock(),
    )
    c, n, has, d = h.read_terminal_with_mode(
        executor=ex, session=session, mode='snapshot', offset=None
    )
    assert c == 'buf' and n is None and has is True and d is None
    c2, n2, has2, _ = h.read_terminal_with_mode(
        executor=ex, session=session, mode='delta', offset=10
    )
    assert c2 == 'tail' and n2 == 14 and has2 is True

    assert h.apply_terminal_resize_if_requested(ex, session, 30, 100) is None
    assert isinstance(
        h.apply_terminal_resize_if_requested(ex, session, 0, 100), ErrorObservation
    )


def test_terminal_input_preflight_rejects_copied_prompt_artifacts() -> None:
    bash_prompt = h.terminal_input_preflight_error(
        '$ pytest',
        shell_kind='powershell',
    )
    assert isinstance(bash_prompt, ErrorObservation)
    assert 'Terminal input rejected' in bash_prompt.content
    assert 'copied shell prompt' in bash_prompt.content

    assert (
        h.terminal_input_preflight_error(
            '$env:PATH',
            shell_kind='powershell',
        )
        is None
    )

    ps_prompt = h.terminal_input_preflight_error(
        'PS C:\\repo> Get-ChildItem',
        shell_kind='powershell',
    )
    assert isinstance(ps_prompt, ErrorObservation)
    assert 'copied powershell prompt' in ps_prompt.content

    continuation = h.terminal_input_preflight_error(
        '>> Get-ChildItem',
        shell_kind='powershell',
    )
    assert isinstance(continuation, ErrorObservation)
    assert 'continuation prompt' in continuation.content


def test_terminal_output_state_detects_powershell_continuation_prompt() -> None:
    assert (
        h.terminal_output_state(
            'incomplete string\n>> ',
            default='SESSION_INTERACTED',
            shell_kind='powershell',
        )
        == 'SESSION_CONTINUATION_PROMPT'
    )
    assert (
        h.terminal_output_state(
            'incomplete string\n>> ',
            default='SESSION_INTERACTED',
            shell_kind='bash',
        )
        == 'SESSION_INTERACTED'
    )


def test_should_poll_terminal_input_delta_only_for_pty_sessions() -> None:
    class PtyInteractiveShellSession:
        pass

    assert h.should_poll_terminal_input_delta(PtyInteractiveShellSession()) is True
    assert h.should_poll_terminal_input_delta(SimpleNamespace(_pty=object())) is True
    assert h.should_poll_terminal_input_delta(SimpleNamespace()) is False


def test_file_read_edit_helpers() -> None:
    ex = _executor()
    ex.file_editor = object()
    out = h.handle_aci_file_read(ex, SimpleNamespace(path='a.py', view_range=None))
    assert isinstance(out, FileReadObservation)

    with (
        patch('os.path.isdir', return_value=True),
        patch(
            'backend.execution.aes.file_operations.handle_directory_view',
            return_value=FileReadObservation(path='d', content='dir'),
        ),
    ):
        dir_obs = h.edit_try_directory_view(
            ex, 'C:/ws/dir', 'dir', SimpleNamespace(command='read_file')
        )
    assert isinstance(dir_obs, FileReadObservation)


def test_build_edit_result_obs_accepts_message_action_outcome() -> None:
    action = SimpleNamespace(path='.')
    payload = {'file_edits': [{'path': 'a.py', 'operation': 'replace', 'content': 'x'}]}
    outcome = MessageAction(content='✓ multi_edit committed 1 file(s) atomically')
    with (
        patch.object(h, '_combined_structured_edit_diff', return_value=''),
        patch.object(
            h,
            '_structured_edit_verification_receipt',
            return_value=('verified', [], True),
        ),
    ):
        obs = h._build_edit_result_obs(
            outcome,
            {'C:/ws/a.py': ('old', 'a.py')},
            action,
            payload,
        )
    assert isinstance(obs, FileEditObservation)
    assert 'multi_edit committed' in obs.content


def test_edit_via_file_editor_marks_replace_string_as_existing_file() -> None:
    ex = _executor()
    ex.file_editor = object()
    action = SimpleNamespace(
        path='demo.txt',
        command='replace_string',
        file_text=None,
        view_range=None,
        new_str='gamma',
        old_string='alpha',
        replace_all=False,
        insert_line=None,
        start_line=None,
        end_line=None,
        edit_mode=None,
        expected_hash=None,
        overwrite_existing=False,
    )
    with patch(
        'backend.execution.aes.file_operations.execute_file_editor',
        return_value=(
            'replaced',
            (None, 'gamma'),
            {'operation': 'replace_string', 'ok': True},
        ),
    ):
        obs = h.edit_via_file_editor(ex, action)
    assert isinstance(obs, FileEditObservation)
    assert obs.outcome == 'edited'
    assert obs.tool_result['operation'] == 'replace_string'
