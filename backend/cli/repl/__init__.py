"""Slash commands, non-interactive CLI, and shared REPL helpers.

Production entry points: TUI (:mod:`backend.cli.tui`) and
:func:`backend.cli.repl.noninteractive.run_noninteractive` for piped input.
"""

from backend.cli.repl.noninteractive import run_noninteractive

__all__ = ['run_noninteractive']
