"""Data models for the slash-command registry.

Pure value types: ``SlashCommandSpec`` describes a command (used by help
and tab-completion), ``ParsedSlashCommand`` is the tokenized result of
parsing a user-typed command, and ``SlashCommandParseError`` is raised
on malformed input.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SlashCommandSpec:
    """Metadata used by help text and prompt-toolkit completion."""

    name: str
    description: str
    usage: str
    aliases: tuple[str, ...] = ()
    #: Grouping key for `/help` (see ``_HELP_SECTIONS_ORDER``).
    help_section: str = 'system'


@dataclass(frozen=True)
class ParsedSlashCommand:
    """A slash command tokenized without breaking Windows paths."""

    raw_name: str
    name: str
    args: tuple[str, ...]


class SlashCommandParseError(ValueError):
    """Raised when the user entered a malformed slash command."""
