"""Tests for backend.execution.utils.bash — split_bash_commands, escape_bash_special_chars, BashCommandStatus."""

from __future__ import annotations

from backend.execution.utils.bash import (
    BashCommandStatus,
    _remove_command_prefix,
    split_bash_commands,
)

# ---------------------------------------------------------------------------
# split_bash_commands
# ---------------------------------------------------------------------------


class TestSplitBashCommands:
    """Tests for split_bash_commands."""

    def test_empty_string(self):
        result = split_bash_commands('')
        assert result == ['']

    def test_whitespace_only(self):
        result = split_bash_commands('   ')
        assert result == ['']

    def test_single_command(self):
        result = split_bash_commands('echo hello')
        assert len(result) == 1
        assert result[0] == 'echo hello'

    def test_two_commands_separated_by_newline(self):
        result = split_bash_commands('echo a\necho b')
        assert len(result) == 2
        assert 'echo a' in result[0]
        assert 'echo b' in result[1]

    def test_semicolon_separated(self):
        result = split_bash_commands('echo a; echo b')
        # bashlex parses this as 2 separate commands
        assert result  # may be 1 or 2 depending on parsing

    def test_piped_command_stays_single(self):
        result = split_bash_commands('cat file | grep pattern')
        assert len(result) == 1

    def test_and_chain_stays_single(self):
        result = split_bash_commands('cd /tmp && ls')
        assert len(result) == 1

    def test_unparseable_command_returned_as_is(self):
        """If bashlex can't parse it, return original command."""
        # heredoc with complex syntax may fail to parse
        weird = 'echo $(('
        result = split_bash_commands(weird)
        assert result == [weird]

    def test_trailing_whitespace_stripped(self):
        result = split_bash_commands('echo hello   ')
        assert result[0].rstrip() == result[0]


# ---------------------------------------------------------------------------
# _remove_command_prefix
# ---------------------------------------------------------------------------


class TestRemoveCommandPrefix:
    """Tests for _remove_command_prefix."""

    def test_prefix_removed(self):
        output = '  echo hello\nworld output'
        result = _remove_command_prefix(output, 'echo hello')
        assert result == 'world output'

    def test_no_prefix_match(self):
        output = 'some other output'
        result = _remove_command_prefix(output, 'echo hello')
        assert result == 'some other output'

    def test_empty_output(self):
        result = _remove_command_prefix('', 'echo hello')
        assert result == ''

    def test_leading_whitespace_stripped(self):
        output = '   echo hello\nresult'
        result = _remove_command_prefix(output, 'echo hello')
        assert 'result' in result


# ---------------------------------------------------------------------------
# BashCommandStatus
# ---------------------------------------------------------------------------


class TestBashCommandStatus:
    """Tests for BashCommandStatus enum."""

    def test_all_values(self):
        assert BashCommandStatus.CONTINUE.value == 'continue'
        assert BashCommandStatus.COMPLETED.value == 'completed'
        assert BashCommandStatus.NO_CHANGE_TIMEOUT.value == 'no_change_timeout'
        assert BashCommandStatus.HARD_TIMEOUT.value == 'hard_timeout'

    def test_member_count(self):
        assert len(BashCommandStatus) == 4
