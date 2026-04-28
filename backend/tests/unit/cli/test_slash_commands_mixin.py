"""Tests for backend.cli._repl.slash_commands_mixin.SlashCommandsMixin."""

from __future__ import annotations

import io
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from backend.cli._repl.slash_commands_mixin import SlashCommandsMixin
from backend.cli.repl import _parse_slash_command


# ---------------------------------------------------------------------------
# Minimal fake host class that provides SlashCommandsMixin requirements
# ---------------------------------------------------------------------------


class _FakeRenderer:
    """Minimal renderer mock with tracked calls."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.markdown_blocks: list[tuple[str, str]] = []
        self.history_cleared = False
        self.last_assistant_message_text = 'Last assistant reply'

    def add_system_message(self, msg: str, *, title: str = '') -> None:
        self.messages.append((title, msg))

    def add_markdown_block(self, title: str, body: str) -> None:
        self.markdown_blocks.append((title, body))

    def clear_history(self) -> None:
        self.history_cleared = True

    def set_cli_tool_icons(self, value: Any) -> None:
        pass

    @contextmanager
    def suspend_live(self):
        yield


class _MockHudState:
    cost_usd = 0.0042
    context_tokens = 1024
    llm_calls = 3
    model = 'openai/gpt-4o'


class _MockHud:
    state = _MockHudState()

    def plain_text(self) -> str:
        return 'HUD text'

    def update_model(self, model: str) -> None:
        pass

    @staticmethod
    def describe_model(model_id: str) -> tuple[str, str]:
        parts = model_id.split('/', 1) if '/' in model_id else ('unknown', model_id)
        return parts[0], parts[1]


class _FakeRepl(SlashCommandsMixin):
    """Minimal host for SlashCommandsMixin that satisfies all self.* accesses."""

    def __init__(self, project_root: Path | None = None) -> None:
        self._renderer: _FakeRenderer | None = _FakeRenderer()
        self._console = Console(quiet=True)
        self._config = MagicMock()
        self._config.enable_think = False
        self._config.cli_tool_icons = True
        self._hud = _MockHud()
        self._controller: MagicMock | None = None
        self._event_stream = None
        self._next_action = None
        self._pending_resume: str | None = None
        self._last_user_message = 'previous message'
        self._project_root = project_root or Path.cwd()

    def _warn(self, msg: str) -> None:
        if self._renderer:
            self._renderer.add_system_message(msg, title='warning')

    def _usage(self, cmd: str) -> str:
        return f'{cmd} [args]'

    def _reject_extra_args(self, parsed: Any) -> bool:
        if parsed.args:
            self._warn(f'Usage: {self._usage(parsed.name)}')
            return True
        return False

    def _command_project_root(self) -> Path:
        return self._project_root


def _repl(project_root: Path | None = None) -> _FakeRepl:
    return _FakeRepl(project_root)


def _parse(cmd: str):
    return _parse_slash_command(cmd)


# ---------------------------------------------------------------------------
# _handle_command / _handle_parsed_command
# ---------------------------------------------------------------------------

class TestHandleCommand:
    def test_exit_command(self) -> None:
        r = _repl()
        result = r._handle_command('/exit')
        assert result is False

    def test_unknown_command(self) -> None:
        r = _repl()
        result = r._handle_command('/nonexistent')
        assert result is True
        assert r._renderer is not None
        titles = [t for t, _ in r._renderer.messages]
        assert 'warning' in titles

    def test_parse_error_warns(self) -> None:
        r = _repl()
        result = r._handle_command('/help "unclosed')
        assert result is True
        assert r._renderer is not None
        titles = [t for t, _ in r._renderer.messages]
        assert 'warning' in titles


# ---------------------------------------------------------------------------
# _cmd_exit
# ---------------------------------------------------------------------------

class TestCmdExit:
    def test_returns_false(self) -> None:
        r = _repl()
        result = r._cmd_exit(_parse('/exit'))
        assert result is False

    def test_adds_goodbye_message(self) -> None:
        r = _repl()
        r._cmd_exit(_parse('/exit'))
        assert r._renderer is not None
        messages = [m for _, m in r._renderer.messages]
        assert any('Goodbye' in m for m in messages)

    def test_no_renderer(self) -> None:
        r = _repl()
        r._renderer = None
        result = r._cmd_exit(_parse('/exit'))
        assert result is False


# ---------------------------------------------------------------------------
# _cmd_clear
# ---------------------------------------------------------------------------

class TestCmdClear:
    def test_clears_history(self) -> None:
        r = _repl()
        result = r._cmd_clear(_parse('/clear'))
        assert result is True
        assert r._renderer is not None
        assert r._renderer.history_cleared

    def test_rejects_extra_args(self) -> None:
        r = _repl()
        result = r._cmd_clear(_parse('/clear extra'))
        assert result is True
        assert r._renderer is not None
        titles = [t for t, _ in r._renderer.messages]
        assert 'warning' in titles
        # History not cleared when extra args
        assert not r._renderer.history_cleared


# ---------------------------------------------------------------------------
# _cmd_status
# ---------------------------------------------------------------------------

class TestCmdStatus:
    def test_shows_hud_text(self) -> None:
        r = _repl()
        result = r._cmd_status(_parse('/status'))
        assert result is True
        assert r._renderer is not None
        messages = [m for _, m in r._renderer.messages]
        assert any('HUD text' in m for m in messages)

    def test_rejects_extra_args(self) -> None:
        r = _repl()
        result = r._cmd_status(_parse('/status extra'))
        assert result is True


# ---------------------------------------------------------------------------
# _cmd_cost
# ---------------------------------------------------------------------------

class TestCmdCost:
    def test_shows_cost(self) -> None:
        r = _repl()
        result = r._cmd_cost(_parse('/cost'))
        assert result is True
        assert r._renderer is not None
        messages = [m for _, m in r._renderer.messages]
        assert any('0.0042' in m or 'cost' in m.lower() for m in messages)

    def test_rejects_extra_args(self) -> None:
        r = _repl()
        result = r._cmd_cost(_parse('/cost extra'))
        assert result is True


# ---------------------------------------------------------------------------
# _cmd_think
# ---------------------------------------------------------------------------

class TestCmdThink:
    def test_toggle_on(self) -> None:
        r = _repl()
        r._config.enable_think = False
        result = r._cmd_think(_parse('/think'))
        assert result is True
        assert r._renderer is not None
        messages = [m for _, m in r._renderer.messages]
        assert any('ON' in m for m in messages)

    def test_toggle_off(self) -> None:
        r = _repl()
        r._config.enable_think = True
        result = r._cmd_think(_parse('/think'))
        assert result is True
        assert r._renderer is not None
        messages = [m for _, m in r._renderer.messages]
        assert any('OFF' in m for m in messages)

    def test_set_on_explicitly(self) -> None:
        r = _repl()
        r._config.enable_think = False
        result = r._cmd_think(_parse('/think on'))
        assert result is True
        assert r._renderer is not None
        messages = [m for _, m in r._renderer.messages]
        assert any('ON' in m for m in messages)

    def test_set_off_explicitly(self) -> None:
        r = _repl()
        r._config.enable_think = True
        result = r._cmd_think(_parse('/think off'))
        assert result is True
        assert r._renderer is not None
        messages = [m for _, m in r._renderer.messages]
        assert any('OFF' in m for m in messages)

    def test_invalid_value(self) -> None:
        r = _repl()
        result = r._cmd_think(_parse('/think maybe'))
        assert result is True
        assert r._renderer is not None
        messages = [m for _, m in r._renderer.messages]
        assert any('Usage' in m or '/think' in m for m in messages)

    def test_too_many_args(self) -> None:
        r = _repl()
        result = r._cmd_think(_parse('/think on off'))
        assert result is True


# ---------------------------------------------------------------------------
# _cmd_resume
# ---------------------------------------------------------------------------

class TestCmdResume:
    def test_valid_arg_sets_pending(self) -> None:
        r = _repl()
        result = r._cmd_resume(_parse('/resume 3'))
        assert result is True
        assert r._pending_resume == '3'

    def test_no_args_warns(self) -> None:
        r = _repl()
        result = r._cmd_resume(_parse('/resume'))
        assert result is True
        assert r._pending_resume is None
        assert r._renderer is not None
        titles = [t for t, _ in r._renderer.messages]
        assert 'warning' in titles

    def test_too_many_args_warns(self) -> None:
        r = _repl()
        result = r._cmd_resume(_parse('/resume 1 2'))
        assert result is True
        assert r._pending_resume is None


# ---------------------------------------------------------------------------
# _cmd_retry
# ---------------------------------------------------------------------------

class TestCmdRetry:
    def test_retry_with_last_message(self) -> None:
        r = _repl()
        r._last_user_message = 'do the thing'
        result = r._cmd_retry(_parse('/retry'))
        assert result is True
        assert r._next_action is not None
        from backend.ledger.action import MessageAction
        assert isinstance(r._next_action, MessageAction)
        assert r._next_action.content == 'do the thing'

    def test_retry_no_last_message(self) -> None:
        r = _repl()
        r._last_user_message = ''
        result = r._cmd_retry(_parse('/retry'))
        assert result is True
        assert r._next_action is None
        assert r._renderer is not None
        messages = [m for _, m in r._renderer.messages]
        assert any('retry' in m.lower() or 'previous' in m.lower() for m in messages)

    def test_retry_rejects_extra_args(self) -> None:
        r = _repl()
        result = r._cmd_retry(_parse('/retry extra'))
        assert result is True


# ---------------------------------------------------------------------------
# _cmd_compact
# ---------------------------------------------------------------------------

class TestCmdCompact:
    def test_sets_condensation_action(self) -> None:
        r = _repl()
        result = r._cmd_compact(_parse('/compact'))
        assert result is True
        assert r._next_action is not None
        from backend.ledger.action.agent import CondensationRequestAction
        assert isinstance(r._next_action, CondensationRequestAction)

    def test_rejects_extra_args(self) -> None:
        r = _repl()
        result = r._cmd_compact(_parse('/compact arg'))
        assert result is True
        assert r._next_action is None


# ---------------------------------------------------------------------------
# _cmd_checkpoint
# ---------------------------------------------------------------------------

class TestCmdCheckpoint:
    def test_list_sub_command(self) -> None:
        r = _repl()
        with patch.object(r, '_handle_checkpoint_list') as mock_list:
            result = r._cmd_checkpoint(_parse('/checkpoint list'))
        assert result is True
        mock_list.assert_called_once()

    def test_diff_sub_command(self) -> None:
        r = _repl()
        with patch.object(r, '_handle_checkpoint_diff') as mock_diff:
            result = r._cmd_checkpoint(_parse('/checkpoint diff abc123'))
        assert result is True
        mock_diff.assert_called_once()

    def test_label_queues_checkpoint(self) -> None:
        r = _repl()
        result = r._cmd_checkpoint(_parse('/checkpoint my label'))
        assert result is True
        assert r._next_action is not None
        from backend.ledger.action import MessageAction
        assert isinstance(r._next_action, MessageAction)
        assert 'my label' in r._next_action.content

    def test_no_label(self) -> None:
        r = _repl()
        result = r._cmd_checkpoint(_parse('/checkpoint'))
        assert result is True
        assert r._next_action is not None


# ---------------------------------------------------------------------------
# _cmd_copy
# ---------------------------------------------------------------------------

class TestCmdCopy:
    def test_copy_ok(self) -> None:
        r = _repl()
        with patch('backend.cli.repl._copy_to_system_clipboard', return_value=(True, 'Copied!')):
            result = r._cmd_copy(_parse('/copy'))
        assert result is True
        assert r._renderer is not None
        messages = [m for _, m in r._renderer.messages]
        assert any('Copied' in m for m in messages)

    def test_copy_fail(self) -> None:
        r = _repl()
        with patch('backend.cli.repl._copy_to_system_clipboard', return_value=(False, 'Failed!')):
            result = r._cmd_copy(_parse('/copy'))
        assert result is True
        assert r._renderer is not None
        titles = [t for t, _ in r._renderer.messages]
        assert 'warning' in titles


# ---------------------------------------------------------------------------
# _cmd_sessions
# ---------------------------------------------------------------------------

class TestCmdSessions:
    def test_calls_list_sessions(self) -> None:
        r = _repl()
        with patch('backend.cli.session_manager.list_sessions') as mock_list:
            result = r._cmd_sessions(_parse('/sessions'))
        assert result is True
        mock_list.assert_called_once()

    def test_list_subcommand(self) -> None:
        r = _repl()
        with patch('backend.cli.session_manager.list_sessions') as mock_list:
            result = r._cmd_sessions(_parse('/sessions list'))
        assert result is True
        mock_list.assert_called_once()

    def test_custom_limit(self) -> None:
        r = _repl()
        with patch('backend.cli.session_manager.list_sessions') as mock_list:
            result = r._cmd_sessions(_parse('/sessions 10'))
        assert result is True
        args, kwargs = mock_list.call_args
        assert kwargs.get('limit') == 10

    def test_invalid_limit(self) -> None:
        r = _repl()
        result = r._cmd_sessions(_parse('/sessions notanumber'))
        assert result is True
        assert r._renderer is not None
        titles = [t for t, _ in r._renderer.messages]
        assert 'warning' in titles

    def test_limit_less_than_1(self) -> None:
        r = _repl()
        result = r._cmd_sessions(_parse('/sessions 0'))
        assert result is True
        assert r._renderer is not None
        titles = [t for t, _ in r._renderer.messages]
        assert 'warning' in titles


# ---------------------------------------------------------------------------
# _cmd_autonomy
# ---------------------------------------------------------------------------

class TestCmdAutonomy:
    def test_no_args_shows_current(self) -> None:
        r = _repl()
        result = r._cmd_autonomy(_parse('/autonomy'))
        assert result is True
        assert r._renderer is not None
        messages = [m for _, m in r._renderer.messages]
        assert any('Autonomy' in m or 'autonomy' in m.lower() for m in messages)

    def test_valid_level_no_controller(self) -> None:
        r = _repl()
        r._controller = None
        result = r._cmd_autonomy(_parse('/autonomy full'))
        assert result is True
        assert r._renderer is not None
        messages = [m for _, m in r._renderer.messages]
        assert any('controller' in m.lower() or 'warning' in m.lower() for m in messages)

    def test_valid_level_with_controller(self) -> None:
        r = _repl()
        mock_ac = MagicMock()
        mock_ac.autonomy_level = 'balanced'
        mock_ctrl = MagicMock()
        mock_ctrl.autonomy_controller = mock_ac
        r._controller = mock_ctrl
        result = r._cmd_autonomy(_parse('/autonomy supervised'))
        assert result is True
        assert mock_ac.autonomy_level == 'supervised'

    def test_invalid_level(self) -> None:
        r = _repl()
        result = r._cmd_autonomy(_parse('/autonomy turbo'))
        assert result is True
        assert r._renderer is not None
        messages = [m for _, m in r._renderer.messages]
        assert any('invalid' in m.lower() or 'turbo' in m.lower() for m in messages)

    def test_too_many_args(self) -> None:
        r = _repl()
        result = r._cmd_autonomy(_parse('/autonomy supervised full'))
        assert result is True


# ---------------------------------------------------------------------------
# _cmd_model
# ---------------------------------------------------------------------------

class TestCmdModel:
    def test_no_args_shows_current(self) -> None:
        r = _repl()
        with patch('backend.cli.config_manager.get_current_model', return_value='openai/gpt-4o'):
            result = r._cmd_model(_parse('/model'))
        assert result is True
        assert r._renderer is not None
        messages = [m for _, m in r._renderer.messages]
        assert any('model' in m.lower() or 'provider' in m.lower() for m in messages)

    def test_valid_model_switch(self) -> None:
        r = _repl()
        with patch('backend.cli.config_manager.update_model') as mock_update, \
             patch('backend.cli.config_manager.get_current_model', return_value='anthropic/claude-haiku-4'):
            result = r._cmd_model(_parse('/model anthropic/claude-haiku-4'))
        assert result is True
        mock_update.assert_called_once_with('anthropic/claude-haiku-4')

    def test_invalid_model_no_slash(self) -> None:
        r = _repl()
        result = r._cmd_model(_parse('/model gpt4'))
        assert result is True
        assert r._renderer is not None
        titles = [t for t, _ in r._renderer.messages]
        assert 'warning' in titles

    def test_model_starts_with_slash(self) -> None:
        r = _repl()
        result = r._cmd_model(_parse('/model /foo/bar'))
        assert result is True
        assert r._renderer is not None
        titles = [t for t, _ in r._renderer.messages]
        assert 'warning' in titles

    def test_too_many_args(self) -> None:
        r = _repl()
        result = r._cmd_model(_parse('/model openai/gpt-4o extra'))
        assert result is True
        assert r._renderer is not None
        titles = [t for t, _ in r._renderer.messages]
        assert 'warning' in titles


# ---------------------------------------------------------------------------
# _cmd_help
# ---------------------------------------------------------------------------

class TestCmdHelp:
    def test_help_no_args(self) -> None:
        r = _repl()
        result = r._cmd_help(_parse('/help'))
        assert result is True
        assert r._renderer is not None
        assert len(r._renderer.markdown_blocks) > 0

    def test_help_with_command(self) -> None:
        r = _repl()
        result = r._cmd_help(_parse('/help settings'))
        assert result is True

    def test_help_too_many_args(self) -> None:
        r = _repl()
        result = r._cmd_help(_parse('/help a b'))
        assert result is True
        assert r._renderer is not None
        titles = [t for t, _ in r._renderer.messages]
        assert 'warning' in titles


# ---------------------------------------------------------------------------
# _cmd_diff
# ---------------------------------------------------------------------------

class TestCmdDiff:
    def test_diff_no_git(self, tmp_path: Path) -> None:
        r = _repl(tmp_path)
        # git not found — FileNotFoundError
        with patch('subprocess.run', side_effect=FileNotFoundError):
            result = r._cmd_diff(_parse('/diff'))
        assert result is True
        assert r._renderer is not None
        titles = [t for t, _ in r._renderer.messages]
        assert 'warning' in titles

    def test_diff_success(self, tmp_path: Path) -> None:
        r = _repl(tmp_path)
        mock_proc = MagicMock()
        mock_proc.stdout = 'M  src/main.py'
        mock_proc.stderr = ''
        mock_proc.returncode = 0
        with patch('subprocess.run', return_value=mock_proc):
            result = r._cmd_diff(_parse('/diff'))
        assert result is True
        assert r._renderer is not None
        messages = [m for _, m in r._renderer.messages]
        assert any('src/main.py' in m for m in messages)

    def test_diff_name_only(self, tmp_path: Path) -> None:
        r = _repl(tmp_path)
        mock_proc = MagicMock()
        mock_proc.stdout = 'src/main.py'
        mock_proc.stderr = ''
        mock_proc.returncode = 0
        with patch('subprocess.run', return_value=mock_proc):
            result = r._cmd_diff(_parse('/diff --name-only'))
        assert result is True

    def test_diff_invalid_flag(self, tmp_path: Path) -> None:
        r = _repl(tmp_path)
        result = r._cmd_diff(_parse('/diff --unknown-flag'))
        assert result is True
        assert r._renderer is not None
        titles = [t for t, _ in r._renderer.messages]
        assert 'warning' in titles

    def test_diff_too_many_paths(self, tmp_path: Path) -> None:
        r = _repl(tmp_path)
        result = r._cmd_diff(_parse('/diff path1 path2'))
        assert result is True
        assert r._renderer is not None
        titles = [t for t, _ in r._renderer.messages]
        assert 'warning' in titles


# ---------------------------------------------------------------------------
# _handle_checkpoint_list
# ---------------------------------------------------------------------------

class TestHandleCheckpointList:
    def test_no_rollback_manager(self) -> None:
        r = _repl()
        r._handle_checkpoint_list([])
        assert r._renderer is not None
        messages = [m for _, m in r._renderer.messages]
        assert any('rollback' in m.lower() or 'checkpoint' in m.lower() for m in messages)

    def test_empty_checkpoints(self) -> None:
        r = _repl()
        mock_mgr = MagicMock()
        mock_mgr.list_checkpoints.return_value = []
        with patch.object(r, '_resolve_rollback_manager', return_value=mock_mgr):
            r._handle_checkpoint_list([])
        assert r._renderer is not None
        messages = [m for _, m in r._renderer.messages]
        assert any('no checkpoint' in m.lower() for m in messages)

    def test_lists_checkpoints(self) -> None:
        r = _repl()
        import time
        entries = [
            {'id': 'cp-abc123', 'timestamp': time.time(), 'checkpoint_type': 'manual', 'description': 'Before refactor'},
            {'id': 'cp-def456', 'timestamp': time.time() - 60, 'checkpoint_type': 'auto', 'description': ''},
        ]
        mock_mgr = MagicMock()
        mock_mgr.list_checkpoints.return_value = entries
        with patch.object(r, '_resolve_rollback_manager', return_value=mock_mgr):
            r._handle_checkpoint_list([])
        assert r._renderer is not None
        messages = [m for _, m in r._renderer.messages]
        assert any('cp-abc123' in m for m in messages)

    def test_invalid_limit_warns(self) -> None:
        r = _repl()
        r._handle_checkpoint_list(['notanumber'])
        assert r._renderer is not None
        titles = [t for t, _ in r._renderer.messages]
        assert 'warning' in titles


# ---------------------------------------------------------------------------
# _handle_checkpoint_diff
# ---------------------------------------------------------------------------

class TestHandleCheckpointDiff:
    def test_no_args_warns(self) -> None:
        r = _repl()
        r._handle_checkpoint_diff([])
        assert r._renderer is not None
        titles = [t for t, _ in r._renderer.messages]
        assert 'warning' in titles

    def test_no_rollback_manager(self) -> None:
        r = _repl()
        r._handle_checkpoint_diff(['cp-123'])
        assert r._renderer is not None
        messages = [m for _, m in r._renderer.messages]
        assert any('rollback' in m.lower() for m in messages)

    def test_checkpoint_not_found(self) -> None:
        r = _repl()
        mock_mgr = MagicMock()
        mock_mgr.list_checkpoints.return_value = [{'id': 'cp-abc'}]
        with patch.object(r, '_resolve_rollback_manager', return_value=mock_mgr):
            r._handle_checkpoint_diff(['zzz-not-found'])
        assert r._renderer is not None
        titles = [t for t, _ in r._renderer.messages]
        assert 'warning' in titles

    def test_diff_with_sha(self, tmp_path: Path) -> None:
        r = _repl(tmp_path)
        mock_mgr = MagicMock()
        mock_mgr.workspace_path = tmp_path
        mock_mgr.list_checkpoints.return_value = [
            {'id': 'cp-abc123', 'git_commit_sha': 'abc123', 'description': 'test'},
        ]
        mock_proc = MagicMock()
        mock_proc.stdout = 'diff --git a/foo b/foo'
        mock_proc.stderr = ''
        mock_proc.returncode = 0
        with patch.object(r, '_resolve_rollback_manager', return_value=mock_mgr), \
             patch('subprocess.run', return_value=mock_proc):
            r._handle_checkpoint_diff(['cp-abc'])
        assert r._renderer is not None
        assert len(r._renderer.markdown_blocks) > 0


# ---------------------------------------------------------------------------
# _format_checkpoint_entry
# ---------------------------------------------------------------------------

class TestFormatCheckpointEntry:
    def test_full_entry(self) -> None:
        import time
        entry = {
            'id': 'cp-abc123def456',
            'timestamp': time.time(),
            'checkpoint_type': 'manual',
            'description': 'Before the refactor',
        }
        result = SlashCommandsMixin._format_checkpoint_entry(entry)
        assert 'cp-abc123def' in result
        assert 'manual' in result
        assert 'Before the refactor' in result

    def test_missing_fields(self) -> None:
        result = SlashCommandsMixin._format_checkpoint_entry({})
        assert '?' in result


# ---------------------------------------------------------------------------
# _compute_checkpoint_diff_text
# ---------------------------------------------------------------------------

class TestComputeCheckpointDiffText:
    def test_no_sha(self) -> None:
        result = SlashCommandsMixin._compute_checkpoint_diff_text(None, '/some/path')
        assert 'no git commit' in result

    def test_with_sha_success(self, tmp_path: Path) -> None:
        mock_proc = MagicMock()
        mock_proc.stdout = 'diff output'
        mock_proc.stderr = ''
        with patch('subprocess.run', return_value=mock_proc):
            result = SlashCommandsMixin._compute_checkpoint_diff_text('abc123', str(tmp_path))
        assert 'diff output' in result

    def test_with_sha_empty_output(self, tmp_path: Path) -> None:
        mock_proc = MagicMock()
        mock_proc.stdout = ''
        mock_proc.stderr = ''
        with patch('subprocess.run', return_value=mock_proc):
            result = SlashCommandsMixin._compute_checkpoint_diff_text('abc123', str(tmp_path))
        assert 'empty diff' in result

    def test_git_exception(self, tmp_path: Path) -> None:
        with patch('subprocess.run', side_effect=OSError('git not found')):
            result = SlashCommandsMixin._compute_checkpoint_diff_text('abc123', str(tmp_path))
        assert 'failed' in result.lower()


# ---------------------------------------------------------------------------
# _render_unknown_command
# ---------------------------------------------------------------------------

class TestRenderUnknownCommand:
    def test_suggests_close_match(self) -> None:
        r = _repl()
        r._render_unknown_command('/sttings')
        assert r._renderer is not None
        messages = [m for _, m in r._renderer.messages]
        # Should suggest /settings
        assert any('settings' in m.lower() for m in messages)

    def test_no_renderer(self) -> None:
        r = _repl()
        r._renderer = None
        r._render_unknown_command('/zzz')  # Should not raise
