"""Shell output helpers for observation rendering."""

from __future__ import annotations

import json
from typing import Any

from rich.syntax import Syntax

from backend.cli.theme import NAVY_BG, get_grinta_pygments_style


def _terminal_output_lexer(body: str) -> str:
    """Pick a Pygments lexer for PTY/shell output (JSON, tracebacks, plain)."""
    raw = body or ''
    head = raw.lstrip()
    if not head:
        return 'text'
    if head[0] in '{[':
        try:
            json.loads(raw[: min(len(raw), 500_000)])
            return 'json'
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    low = raw.lower()
    if 'traceback (most recent call last)' in low:
        return 'pytb'
    return 'text'


def _cmd_stdout_syntax_extras(content: str) -> list[Any] | None:
    """Rich Syntax block for bulky structured shell stdout (JSON, tracebacks, …).

    Plain prose/log lines stay hidden on success — only non-``text`` lexers
    (JSON, Python tracebacks, …) get an inline preview.
    """
    c = (content or '').strip()
    if len(c) < 120:
        return None
    n_lines = len([ln for ln in c.splitlines() if ln.strip()])
    lex = _terminal_output_lexer(c)
    if lex == 'text':
        return None
    cap = 12_000
    body = c[:cap] + ('…' if len(c) > cap else '')
    return [
        Syntax(
            body,
            lex,
            word_wrap=True,
            theme=get_grinta_pygments_style(),
            line_numbers=n_lines > 10,
            background_color=NAVY_BG,
        )
    ]


def _looks_like_command_echo(line: str) -> bool:
    """Check if a line is likely the echoed command (not actual output)."""
    stripped_line = line.strip()
    if not stripped_line:
        return True
    if (
        stripped_line.startswith('$ ')
        or stripped_line.startswith('❯ ')
        or stripped_line.startswith('> ')
    ):
        return True
    return False
