"""Shared parsing and background-session helpers for bash execution."""

from __future__ import annotations

import re
import traceback
from typing import TYPE_CHECKING, Any, cast

import bashlex  # pyright: ignore[reportMissingTypeStubs]

from backend.core.logger import app_logger as logger
from backend.execution.utils.unified_shell import UnifiedShellSession
from backend.ledger.observation import ErrorObservation

if TYPE_CHECKING:
    from libtmux.pane import Pane
    from libtmux.window import Window

    from backend.ledger.action import CmdRunAction


BashlexNode = Any


def _get_bashlex_parsing_errors() -> tuple[type[BaseException], ...]:
    parsing_error = getattr(getattr(bashlex, 'errors', None), 'ParsingError', None)
    if isinstance(parsing_error, type) and issubclass(parsing_error, BaseException):
        return (parsing_error, NotImplementedError, TypeError, AttributeError)
    return (NotImplementedError, TypeError, AttributeError)


_BASHLEX_PARSING_ERRORS = _get_bashlex_parsing_errors()


def _parse_bash(command: str) -> list[BashlexNode]:
    typed_bashlex = cast(Any, bashlex)
    return cast(list[BashlexNode], typed_bashlex.parse(command))


def split_bash_commands(commands: str) -> list[str]:
    """Split bash commands string into individual commands."""
    if not commands.strip():
        return ['']
    try:
        parsed = _parse_bash(commands)
    except _BASHLEX_PARSING_ERRORS:
        logger.debug(
            'Failed to parse bash commands\n[input]: %s\n[warning]: %s\nThe original command will be returned as is.',
            commands,
            traceback.format_exc(),
        )
        return [commands]
    result: list[str] = []
    last_end = 0
    for node in parsed:
        start, end = node.pos
        if start > last_end:
            between = commands[last_end:start]
            logger.debug('BASH PARSING between: %s', between)
            if result:
                result[-1] += between.rstrip()
            elif between.strip():
                result.append(between.rstrip())
        command = commands[start:end].rstrip()
        logger.debug('BASH PARSING command: %s', command)
        result.append(command)
        last_end = end
    remaining = commands[last_end:].rstrip()
    logger.debug('BASH PARSING remaining: %s', remaining)
    if last_end < len(commands):
        if result:
            result[-1] += remaining
            logger.debug('BASH PARSING result[-1] += remaining: %s', result[-1])
        elif remaining:
            result.append(remaining)
            logger.debug('BASH PARSING result.append(remaining): %s', result[-1])
    return result


def escape_bash_special_chars(command: str) -> str:
    r"""Escape characters that have different interpretations in bash vs python."""
    if not command.strip():
        return ''
    try:
        parts: list[str] = []
        last_pos = 0

        def visit_node(node: Any) -> None:
            nonlocal last_pos
            if (
                node.kind == 'redirect'
                and hasattr(node, 'heredoc')
                and (node.heredoc is not None)
            ):
                between = command[last_pos : node.pos[0]]
                parts.append(between)
                parts.append(command[node.pos[0] : node.heredoc.pos[0]])
                parts.append(command[node.heredoc.pos[0] : node.heredoc.pos[1]])
                last_pos = node.pos[1]
                return
            if node.kind == 'word':
                between = command[last_pos : node.pos[0]]
                word_text = command[node.pos[0] : node.pos[1]]
                between = re.sub('\\\\([;&|><])', '\\\\\\\\\1', between)
                parts.append(between)
                if (
                    (word_text.startswith('"') and word_text.endswith('"'))
                    or (word_text.startswith("'") and word_text.endswith("'"))
                    or (word_text.startswith('$(') and word_text.endswith(')'))
                    or (word_text.startswith('`') and word_text.endswith('`'))
                ):
                    parts.append(word_text)
                else:
                    word_text = re.sub('\\\\([;&|><])', '\\\\\\\\\1', word_text)
                    parts.append(word_text)
                last_pos = node.pos[1]
                return
            if hasattr(node, 'parts'):
                for part in node.parts:
                    visit_node(part)

        nodes = _parse_bash(command)
        for node in nodes:
            between = command[last_pos : node.pos[0]]
            between = re.sub('\\\\([;&|><])', '\\\\\\\\\1', between)
            parts.append(between)
            last_pos = node.pos[0]
            visit_node(node)
        remaining = command[last_pos:]
        parts.append(remaining)
        return ''.join(parts)
    except _BASHLEX_PARSING_ERRORS:
        logger.debug(
            'Failed to parse bash commands for special characters escape\n[input]: %s\n[warning]: %s\nThe original command will be returned as is.',
            command,
            traceback.format_exc(),
        )
        return command


def remove_command_prefix(command_output: str, command: str) -> str:
    """Remove command prefix from command output."""
    return command_output.lstrip().removeprefix(command.lstrip()).lstrip()


class BackgroundPaneSession(UnifiedShellSession):
    """Read-only view of a backgrounded tmux pane."""

    def __init__(self, pane: 'Pane', window: 'Window', cwd: str) -> None:
        self._pane = pane
        self._window = window
        self._cwd = cwd

    def initialize(self) -> None:  # noqa: D401
        pass

    def execute(self, action: 'CmdRunAction') -> ErrorObservation:
        return ErrorObservation(
            'Cannot execute commands on a background-only pane session.'
        )

    def close(self) -> None:
        try:
            self._window.kill_window()
        except Exception:
            logger.debug('Failed to kill background pane window', exc_info=True)

    @property
    def cwd(self) -> str:
        return self._cwd

    def get_detected_server(self):
        return None

    def read_output(self) -> str:
        try:
            lines = self._pane.cmd('capture-pane', '-J', '-pS', '-').stdout
            return '\n'.join(line.rstrip() for line in lines)
        except Exception:
            return ''

    def read_output_since(self, offset: int) -> tuple[str, int, int | None]:
        full = self.read_output()
        total = len(full)
        safe = max(0, offset)
        delta = full[safe:] if safe < total else ''
        return delta, total, None

    def write_input(self, data: str, is_control: bool = False) -> None:
        if is_control:
            self._pane.send_keys(data, enter=False)
        else:
            self._pane.send_keys(data, enter=True)
