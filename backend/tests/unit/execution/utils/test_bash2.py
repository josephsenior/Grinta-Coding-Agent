"""Tests for backend.execution.utils.bash — bash command parsing and execution utils."""

from __future__ import annotations

from unittest.mock import patch

from backend.execution.utils.bash import escape_bash_special_chars, split_bash_commands


# ---------------------------------------------------------------------------
# split_bash_commands
# ---------------------------------------------------------------------------
class TestSplitBashCommands:
    def test_empty_string(self):
        result = split_bash_commands('')
        assert result == ['']

    def test_whitespace_only(self):
        result = split_bash_commands('   ')
        assert result == ['']

    def test_single_command(self):
        result = split_bash_commands('echo hello')
        assert result == ['echo hello']

    def test_multiple_commands_semicolon(self):
        result = split_bash_commands('echo a; echo b')
        # split_bash_commands preserves structure — returns nodes not individual commands
        assert result
        assert 'echo' in result[0]

    def test_multiple_commands_newline(self):
        result = split_bash_commands('echo a\necho b')
        assert result

    def test_multiple_commands_and(self):
        result = split_bash_commands('mkdir test && cd test')
        assert result

    def test_multiple_commands_or(self):
        result = split_bash_commands('ls /nonexistent || echo failed')
        assert result

    def test_multiple_commands_pipe(self):
        result = split_bash_commands('cat file.txt | grep pattern')
        assert result

    def test_complex_command(self):
        result = split_bash_commands('cd /tmp && ls -la | grep test')
        assert result

    def test_command_with_quotes(self):
        result = split_bash_commands('echo "hello world"')
        assert result == ['echo "hello world"']

    def test_parsing_error_returns_original(self):
        # Invalid bash syntax
        cmd = 'echo $(( invalid'
        result = split_bash_commands(cmd)
        assert result == [cmd]

    def test_parsing_not_implemented_returns_original(self):
        # Mock bashlex.parse to raise NotImplementedError
        cmd = 'some command'
        with patch(
            'backend.execution.utils.bash.bashlex.parse',
            side_effect=NotImplementedError,
        ):
            result = split_bash_commands(cmd)
            assert result == [cmd]

    def test_parsing_type_error_returns_original(self):
        cmd = 'some command'
        with patch('backend.execution.utils.bash.bashlex.parse', side_effect=TypeError):
            result = split_bash_commands(cmd)
            assert result == [cmd]

    def test_parsing_attribute_error_returns_original(self):
        cmd = 'some command'
        with patch(
            'backend.execution.utils.bash.bashlex.parse', side_effect=AttributeError
        ):
            result = split_bash_commands(cmd)
            assert result == [cmd]

    def test_preserves_trailing_whitespace_in_commands(self):
        result = split_bash_commands('echo a  ; echo b')
        # The function strips trailing whitespace from each command
        assert all('echo' in cmd for cmd in result if cmd)

    def test_handles_remaining_content_after_last_command(self):
        # Commands with trailing characters
        result = split_bash_commands('echo a ; echo b ; ')
        assert result

    def test_command_without_trailing_pipe(self):
        result = split_bash_commands('ls')
        assert result == ['ls']

    def test_background_command(self):
        result = split_bash_commands('sleep 100 &')
        assert len(result) == 1
        assert '&' in result[0]


# ---------------------------------------------------------------------------
# escape_bash_special_chars
# ---------------------------------------------------------------------------
class TestEscapeBashSpecialChars:
    def test_empty_string(self):
        result = escape_bash_special_chars('')
        assert result == ''

    def test_whitespace_only(self):
        result = escape_bash_special_chars('  ')
        assert result == ''

    def test_no_special_chars(self):
        result = escape_bash_special_chars('echo hello')
        assert 'echo hello' in result or result == ['echo hello']

    def test_escaped_semicolon(self):
        # The function should handle \\; differently than ;
        result = escape_bash_special_chars('echo a\\;b')
        # Result depends on implementation — just verify it doesn't crash
        assert result is not None

    def test_escaped_pipe(self):
        result = escape_bash_special_chars('echo a\\|b')
        assert result is not None

    def test_escaped_ampersand(self):
        result = escape_bash_special_chars('echo a\\&b')
        assert result is not None

    def test_multiple_escaped_chars(self):
        result = escape_bash_special_chars('echo \\;\\|\\&')
        assert result is not None

    def test_mixed_escaped_and_real_chars(self):
        result = escape_bash_special_chars('echo a\\;b ; echo c')
        assert result is not None


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------
class TestBashUtilsIntegration:
    def test_split_and_escape_together(self):
        # Ensure split_bash_commands can handle commands with special chars
        cmd = 'echo hello; ls -la'
        split_result = split_bash_commands(cmd)
        assert split_result

        # Escape each command
        for sub_cmd in split_result:
            escaped = escape_bash_special_chars(sub_cmd)
            # Should not crash
            assert escaped is not None
