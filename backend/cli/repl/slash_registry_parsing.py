"""Slash-command parsing.

Handles:
* persistent history file location and creation;
* alias resolution (``/quit`` → ``/exit``);
* quote-preserving tokenization of the command line;
* the public ``parse_slash_command`` entry point that returns a
  :class:`ParsedSlashCommand`.
"""

from __future__ import annotations

from pathlib import Path

from backend.cli.repl.slash_registry_commands import _COMMAND_ALIASES
from backend.cli.repl.slash_registry_models import (
    ParsedSlashCommand,
    SlashCommandParseError,
)

_HISTORY_DIR = Path.home() / '.grinta'
_HISTORY_FILE = _HISTORY_DIR / 'history.txt'


def ensure_history() -> Path:
    _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    if not _HISTORY_FILE.exists():
        _HISTORY_FILE.touch()
    return _HISTORY_FILE


def canonical_command_name(command: str) -> str:
    """Normalize slash-command aliases to a single canonical name."""
    lowered = command.lower()
    return _COMMAND_ALIASES.get(lowered, lowered)


def split_command_words(text: str) -> tuple[str, ...]:
    """Split a REPL command line with quotes while preserving backslashes."""
    words: list[str] = []
    current: list[str] = []
    quote: str | None = None
    in_word = False

    for char in text.strip():
        if char in {'"', "'"}:
            if quote == char:
                quote = None
                in_word = True
                continue
            if quote is None:
                quote = char
                in_word = True
                continue
        if char.isspace() and quote is None:
            if in_word:
                words.append(''.join(current))
                current = []
                in_word = False
            continue
        current.append(char)
        in_word = True

    if quote is not None:
        raise SlashCommandParseError(f'Unclosed {quote} quote in command.')
    if in_word:
        words.append(''.join(current))
    return tuple(words)


def parse_slash_command(text: str) -> ParsedSlashCommand:
    """Parse and canonicalize a slash command line."""
    words = split_command_words(text)
    if not words or not words[0].startswith('/'):
        raise SlashCommandParseError('Expected a slash command.')
    raw_name = words[0].lower()
    return ParsedSlashCommand(
        raw_name=raw_name,
        name=canonical_command_name(raw_name),
        args=words[1:],
    )
