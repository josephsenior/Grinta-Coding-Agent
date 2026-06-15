"""Unit tests for shell observation helper utilities."""

from __future__ import annotations

import pytest

from backend.cli.event_rendering.observations.shell_helpers import (
    _cmd_stdout_syntax_extras,
    _looks_like_command_echo,
    _terminal_output_lexer,
)


def test_terminal_output_lexer_detects_json_traceback_and_text() -> None:
    assert _terminal_output_lexer('') == 'text'
    assert _terminal_output_lexer('{"ok": true}') == 'json'
    assert _terminal_output_lexer('Traceback (most recent call last)\n') == 'pytb'
    assert _terminal_output_lexer('plain log line') == 'text'


def test_cmd_stdout_syntax_extras_skips_short_and_plain_text() -> None:
    assert _cmd_stdout_syntax_extras('short') is None
    long_plain = '\n'.join(f'line {idx}' for idx in range(20))
    assert _cmd_stdout_syntax_extras(long_plain) is None


def test_cmd_stdout_syntax_extras_returns_syntax_for_json() -> None:
    payload = '{"items": [' + ','.join(f'"{idx}"' for idx in range(30)) + ']}'
    extras = _cmd_stdout_syntax_extras(payload)
    assert extras is not None
    assert len(extras) == 1


@pytest.mark.parametrize(
    ('line', 'expected'),
    [
        ('', True),
        ('$ npm test', True),
        ('❯ run', True),
        ('> build', True),
        ('actual output', False),
    ],
)
def test_looks_like_command_echo(line: str, expected: bool) -> None:
    assert _looks_like_command_echo(line) is expected
