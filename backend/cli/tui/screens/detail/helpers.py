"""Shared markup helpers for detail screens."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.cli.tui.transcript_typography import (
    TX_BODY,
    TX_BODY_DIM,
    TX_KEY_HINT,
    TX_META,
    TX_MUTED,
    TX_SECTION,
)
from backend.cli.tui.widgets.scan_line.card import SCAN_LINE_BORDER_COLORS

if TYPE_CHECKING:
    from backend.cli.tui.screens.detail.base import DetailScreen

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
    return f'{lights}  [{TX_META}]{title}[/]'


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
    from backend.cli.tui.helpers import _format_terminal_output_for_display

    body = text or ' '
    if body.endswith('\n'):
        body = body.rstrip('\n')
    if '\x1b' in body or '\u001b' in body:
        return _format_terminal_output_for_display(body)

    from rich.syntax import Syntax

    from backend.cli.theme.syntax_theme import grinta_syntax_kwargs

    lexer = (
        language
        if language and language != 'text'
        else _guess_terminal_output_lexer(body)
    )
    return Syntax(
        body,
        lexer,
        line_numbers=True,
        word_wrap=True,
        padding=(0, 1),
        **grinta_syntax_kwargs(background_color='#060a14'),
    )


def _guess_terminal_output_lexer(text: str) -> str:
    """Best-effort lexer for plain shell output without ANSI escapes."""
    sample = (text or '').strip()
    if not sample:
        return 'text'
    head = sample[:4000]
    if head.lstrip().startswith(('{', '[')):
        return 'json'
    if 'Traceback (most recent call last)' in head or 'File "' in head:
        return 'python'
    if 'error[E' in head or ' --> ' in head:
        return 'rust'
    return 'console'


def detail_accent_for_state(state: str) -> str:
    """Map scan-line card state to a left-pipe accent color."""
    return SCAN_LINE_BORDER_COLORS.get(state, DETAIL_DEFAULT_ACCENT)


def split_detail_title(title: str) -> tuple[str, str]:
    """Split ``'Shell  npm install'`` into kind + heading."""
    if '  ' in title:
        kind, heading = title.split('  ', 1)
        return kind.strip(), heading.strip()
    return '', title.strip()


def format_meta_chips(parts: list[str]) -> str:
    """Join muted meta fragments with a centered dot."""
    return f' [{TX_MUTED}]·[/] '.join(parts)


def format_exit_chip(
    exit_code: int | None, *, is_background: bool = False
) -> str | None:
    if is_background:
        return '[#6B9FD4]detached to background[/]'
    if exit_code is None:
        return None
    if exit_code == 0:
        return '[#639922]✓ exit 0[/]'
    return f'[#E24B4A]✗ exit {exit_code}[/]'


def format_section_heading(label: str) -> str:
    return f'[bold {TX_SECTION}]{label}[/]'


def format_url(url: str) -> str:
    """Styled URL for detail meta rows."""
    return f'[bold {TX_KEY_HINT}]{url}[/]'


def list_row_arrow(text: str, *, tone: str = TX_BODY) -> str:
    """Consistent arrow-prefixed list row markup."""
    return f'[{TX_BODY}]→[/] [{tone}]{text}[/]'


def list_row_bullet(text: str, *, tone: str = TX_BODY) -> str:
    """Bullet-prefixed list row for checklist-style detail panes."""
    return f'[{TX_MUTED}]●[/] [{tone}]{text}[/]'


def format_criterion_line(item: dict[str, Any]) -> str:
    """Render one acceptance criterion as a single detail line."""
    assertion = str(item.get('assertion') or '').strip()
    if not assertion:
        return ''
    source = str(item.get('source') or 'stated').strip().lower()
    evidence = str(item.get('evidence') or '').strip()
    criterion_id = str(item.get('id') or '').strip()
    id_prefix = f'[{criterion_id}] ' if criterion_id else ''
    line = f'{id_prefix}({source}) {assertion}'
    if evidence:
        line += f' — {evidence}'
    return line


def criteria_rows_from_observation(obs: Any) -> list[dict[str, Any]]:
    """Extract structured criteria rows from an observation payload."""
    import re

    criteria_list = getattr(obs, 'criteria_list', None)
    if isinstance(criteria_list, list):
        rows = [item for item in criteria_list if isinstance(item, dict)]
        if rows:
            return rows

    content = str(getattr(obs, 'content', '') or '')
    parsed: list[dict[str, Any]] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        match = re.match(r'^\d+\.\s+\((\w+)\)\s+(.+)$', line)
        if not match:
            continue
        source = match.group(1).strip().lower()
        rest = match.group(2).strip()
        evidence: str | None = None
        if ' — ' in rest:
            assertion, evidence = rest.rsplit(' — ', 1)
        else:
            assertion = rest
        parsed.append(
            {
                'assertion': assertion.strip(),
                'source': source,
                'evidence': evidence.strip() if evidence else None,
            }
        )
    return parsed


def kv_row(name: str, value: str) -> str:
    """Name = value row for debugger variables and similar."""
    return f'[{TX_BODY}]{name}[/] [{TX_MUTED}]=[/] [{TX_KEY_HINT}]{value}[/]'


def build_terminal_detail_content(
    screen: DetailScreen,
    *,
    meta_parts: list[str],
    command: str,
    output: str,
    frame_title: str,
    show_command_when_no_output: bool = True,
    meta_widget_id: str = '',
    cmd_widget_id: str = '',
    output_widget_id: str = '',
    empty_widget_id: str = '',
    empty_message: str = '(no output)',
) -> list:
    """Shared body builder for shell and terminal detail screens."""
    widgets: list = []

    if meta_parts:
        widgets.append(
            screen.meta_row(format_meta_chips(meta_parts), widget_id=meta_widget_id)
        )

    frame_parts: list = []
    if command and (show_command_when_no_output or not output):
        frame_parts.append(
            screen.syntax_block(
                render_command_syntax(command),
                widget_id=cmd_widget_id,
            )
        )
    if output:
        frame_parts.append(
            screen.syntax_block(
                render_terminal_output(output, language='text'),
                widget_id=output_widget_id,
            )
        )
    if frame_parts:
        widgets.append(screen.terminal_frame(*frame_parts, title=frame_title[:48]))
    elif not command:
        widgets.append(screen.empty_state(empty_message, widget_id=empty_widget_id))

    return widgets


def format_cwd_meta(cwd: str) -> str:
    return f'[{TX_BODY_DIM}]{cwd}[/]'


def format_session_meta(session_id: str) -> str:
    return f'[{TX_KEY_HINT}]{session_id}[/]'
