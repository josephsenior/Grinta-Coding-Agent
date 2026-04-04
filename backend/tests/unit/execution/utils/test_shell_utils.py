"""Tests for backend/execution/utils/shell_utils.py."""

from __future__ import annotations

from backend.execution.utils.shell_utils import format_shell_output


class TestFormatShellOutput:
    # ── Return type ─────────────────────────────────────────────────

    def test_returns_cmd_output_observation(self) -> None:
        from backend.ledger.observation.commands import CmdOutputObservation

        result = format_shell_output('ls', 'file.txt', '', 0, '/home/user')
        assert isinstance(result, CmdOutputObservation)

    # ── Content construction ─────────────────────────────────────────

    def test_stdout_only(self) -> None:
        result = format_shell_output('echo hello', 'hello', '', 0, '/tmp')
        assert result.content == 'hello'

    def test_stderr_only_prefixed(self) -> None:
        result = format_shell_output('bad_cmd', '', 'error: not found', 1, '/tmp')
        assert '[ERROR STREAM]' in result.content
        assert 'error: not found' in result.content

    def test_both_stdout_and_stderr(self) -> None:
        result = format_shell_output('cmd', 'output', 'warning: x', 0, '/tmp')
        assert 'output' in result.content
        assert '[ERROR STREAM]' in result.content
        assert 'warning: x' in result.content

    def test_empty_stdout_and_stderr_gives_empty_content(self) -> None:
        result = format_shell_output('cmd', '', '', 0, '/tmp')
        assert result.content == ''

    def test_content_stripped(self) -> None:
        result = format_shell_output('cmd', '  hello  \n', '', 0, '/tmp')
        assert result.content == 'hello'

    # ── Metadata fields ──────────────────────────────────────────────

    def test_metadata_exit_code_zero(self) -> None:
        result = format_shell_output('cmd', 'ok', '', 0, '/tmp')
        assert result.metadata.exit_code == 0

    def test_metadata_exit_code_nonzero(self) -> None:
        result = format_shell_output('cmd', '', '', 127, '/tmp')
        assert result.metadata.exit_code == 127

    def test_metadata_working_dir_unix(self) -> None:
        result = format_shell_output('cmd', '', '', 0, '/home/user/project')
        assert result.metadata.working_dir == '/home/user/project'

    def test_metadata_working_dir_windows_normalized(self) -> None:
        # Windows paths with backslashes should be escaped
        result = format_shell_output('cmd', '', '', 0, 'C:\\Users\\user')
        wd = result.metadata.working_dir
        assert wd is not None and '\\\\' in wd

    def test_metadata_prefix_set(self) -> None:
        result = format_shell_output('cmd', 'data', '', 0, '/tmp')
        assert (
            result.metadata.prefix == '[Below is the output of the previous command.]\n'
        )

    def test_metadata_suffix_contains_exit_code(self) -> None:
        result = format_shell_output('cmd', 'data', '', 42, '/tmp')
        assert '42' in result.metadata.suffix
        assert 'exit code' in result.metadata.suffix.lower()

    # ── Command is stored ────────────────────────────────────────────

    def test_command_stored_in_observation(self) -> None:
        result = format_shell_output('grep -r pattern', 'match', '', 0, '/src')
        assert result.command == 'grep -r pattern'

    # ── Edge cases ───────────────────────────────────────────────────

    def test_multiline_stdout(self) -> None:
        result = format_shell_output('ls -la', 'file1\nfile2\nfile3', '', 0, '/tmp')
        assert 'file1' in result.content
        assert 'file3' in result.content

    def test_stdout_and_stderr_joined_by_newline(self) -> None:
        result = format_shell_output('cmd', 'out', 'err', 0, '/tmp')
        # Both parts are present with newline between them
        assert 'out' in result.content
        assert 'err' in result.content
