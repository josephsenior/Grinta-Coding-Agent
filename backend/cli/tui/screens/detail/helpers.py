"""Shared markup helpers for detail screens."""

from __future__ import annotations

from typing import Any

from backend.cli.tui.widgets.scan_line.card import SCAN_LINE_BORDER_COLORS

DETAIL_DEFAULT_ACCENT = '#5eead4'

# Muted macOS-style traffic lights (low brightness)
_TRAFFIC_RED = '#c45c55'
_TRAFFIC_YELLOW = '#c9a23f'
_TRAFFIC_GREEN = '#57a85f'


def traffic_lights_markup(title: str = '') -> str:
    """Three-dot window chrome row for terminal detail panes."""
    lights = f'[{_TRAFFIC_RED}]●[/] [{_TRAFFIC_YELLOW}]●[/] [{_TRAFFIC_GREEN}]●[/]'
    if not title:
        return lights
    return f'{lights}  [#6f83aa]{title}[/]'


def render_command_syntax(command: str) -> Any:
    """Syntax-highlight a shell command for detail panes."""
    from rich.syntax import Syntax

    from backend.cli.theme.syntax_theme import grinta_syntax_kwargs

    body = (command or '').strip() or ' '
    return Syntax(
        f'$ {body}',
        'bash',
        line_numbers=False,
        word_wrap=True,
        padding=(0, 1),
        **grinta_syntax_kwargs(background_color='#060a14'),
    )


def render_terminal_output(text: str, *, language: str = 'text') -> Any:
    """Syntax-highlight terminal scrollback / shell output."""
    from rich.syntax import Syntax

    from backend.cli.theme.syntax_theme import grinta_syntax_kwargs

    body = text or ' '
    if body.endswith('\n'):
        body = body.rstrip('\n')
    return Syntax(
        body,
        language,
        line_numbers=True,
        word_wrap=True,
        padding=(0, 1),
        **grinta_syntax_kwargs(background_color='#060a14'),
    )


def detail_accent_for_state(state: str) -> str:
    """Map scan-line card state to a left-pipe accent color."""
    return SCAN_LINE_BORDER_COLORS.get(state, DETAIL_DEFAULT_ACCENT)


def split_detail_title(title: str) -> tuple[str, str]:
    """Split ``'Shell  npm install'`` into kind + heading."""
    if '  ' in title:
        kind, heading = title.split('  ', 1)
        return kind.strip(), heading.strip()
    return '', title.strip()


def format_numbered_block(text: str, *, tone: str = '#c8d4e8') -> str:
    """Line-numbered monospace block for shell/terminal output."""
    lines = text.splitlines()
    if not lines:
        return text
    width = len(str(len(lines)))
    numbered: list[str] = []
    for index, line in enumerate(lines, 1):
        gutter = f'[#374151]{index:>{width}} │[/] '
        numbered.append(gutter + f'[{tone}]{line}[/]')
    return '\n'.join(numbered)


def format_shell_command(command: str) -> str:
    """Styled ``$ command`` prompt row."""
    return f'[#5eead4]$[/] [bold #e9e9e9]{command}[/]'


def format_meta_chips(parts: list[str]) -> str:
    """Join muted meta fragments with a centered dot."""
    return ' [#54597b]·[/] '.join(parts)


def format_exit_chip(exit_code: int | None, *, is_background: bool = False) -> str | None:
    if is_background:
        return '[#6B9FD4]detached to background[/]'
    if exit_code is None:
        return None
    if exit_code == 0:
        return '[#639922]✓ exit 0[/]'
    return f'[#E24B4A]✗ exit {exit_code}[/]'


def format_section_heading(label: str) -> str:
    return f'[bold #8f9fc1]{label}[/]'
