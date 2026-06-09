"""Shell command renderer.

Terminal-style panel with prompt, command, and output preview.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from backend.cli.theme import (
    CLR_CARD_BORDER,
    CLR_STATUS_ERR,
    CLR_STATUS_OK,
    NAVY_TEXT_DIM,
    NAVY_TEXT_MUTED,
    NAVY_TEXT_PRIMARY,
)

if TYPE_CHECKING:
    from rich.console import Console


_KNOWN_COMMANDS: frozenset[str] = frozenset({
    'cd', 'ls', 'dir', 'pwd', 'cat', 'echo', 'type', 'mkdir', 'rm', 'del',
    'copy', 'move', 'ren', 'git', 'npm', 'pip', 'python', 'node', 'cargo',
    'go', 'rustc', 'make', 'cmake', 'docker', 'kubectl', 'curl', 'wget',
    'ssh', 'scp', 'rsync', 'tar', 'zip', 'unzip', 'grep', 'find', 'awk',
    'sed', 'head', 'tail', 'sort', 'uniq', 'wc', 'tee', 'xargs', 'env',
    'export', 'source', 'bash', 'sh', 'zsh', 'fish', 'pwsh', 'powershell',
    'cmd', 'set', 'if', 'for', 'while', 'foreach', 'switch', 'function',
    'param', 'return', 'exit', 'break', 'continue', 'throw', 'try', 'catch',
    'finally', 'using', 'class', 'enum', 'workflow', 'configuration',
    'inlinescript', 'parallel', 'sequence',
})

_STYLE_MAP: dict[str, str] = {
    'keyword': 'bold #e9e9e9',
    'string': '#54efae',
    'flag': '#f6ff8f',
    'assignment': '#91abec',
    'arg': NAVY_TEXT_PRIMARY,
    'space': '',
    'cmd': NAVY_TEXT_PRIMARY,
}


def _classify_token(token: str) -> str:
    lower = token.lower()
    if lower in _KNOWN_COMMANDS:
        return 'keyword'
    if lower.startswith('-') or lower.startswith('/'):
        return 'flag'
    if '=' in token and not token.startswith('$'):
        return 'assignment'
    return 'arg'


def _process_token_char(ch, current, in_string, string_char, parts):
    if in_string:
        if ch == string_char:
            current += ch
            parts.append(('string', current))
            return '', False, ''
        return current + ch, True, string_char
    if ch in ('"', "'"):
        if current:
            parts.append((_classify_token(current), current))
        return ch, True, ch
    if ch == ' ':
        if current:
            parts.append((_classify_token(current), current))
            parts.append(('space', ' '))
        return '', False, ''
    return current + ch, False, ''


def _tokenize_command(cmd: str) -> list[tuple[str, str]]:
    parts: list[tuple[str, str]] = []
    current = ''
    in_string = False
    string_char = ''

    for ch in cmd:
        current, in_string, string_char = _process_token_char(
            ch, current, in_string, string_char, parts
        )

    if current:
        parts.append((_classify_token(current), current))

    return parts


def _build_command_text(command: str) -> Text:
    """Build styled command text with syntax-aware highlighting."""
    text = Text()
    text.append('PS> ', style='bold #91abec')

    cmd = command.strip()
    if len(cmd) > 120:
        cmd = cmd[:117] + '\u2026'

    for kind, value in _tokenize_command(cmd):
        text.append(value, style=_STYLE_MAP.get(kind, ''))

    return text


def _build_meta_line(duration: str, exit_code: int | None) -> Text | None:
    meta_parts = []
    if duration:
        meta_parts.append(Text(duration, style=NAVY_TEXT_DIM))
    if exit_code is not None:
        style = CLR_STATUS_OK if exit_code == 0 else CLR_STATUS_ERR
        meta_parts.append(Text(f'  exit {exit_code}', style=style))
    if not meta_parts:
        return None
    meta_line = Text()
    for i, part in enumerate(meta_parts):
        if i > 0:
            meta_line.append('  ')
        meta_line.append(part)
    return meta_line


def _build_output_preview(output: str) -> list[Text]:
    lines: list[Text] = []
    raw_lines = [ln for ln in output.splitlines()]
    preview = raw_lines[:8]
    if not preview:
        return lines
    lines.append(Text(''))
    for line in preview:
        if len(line) > 120:
            line = line[:117] + '\u2026'
        lines.append(Text(line, style=NAVY_TEXT_MUTED))
    if len(raw_lines) > 8:
        lines.append(
            Text(f'... {len(raw_lines) - 8} more lines', style=NAVY_TEXT_DIM)
        )
    return lines


def render_shell_command(
    command: str,
    output: str | None = None,
    exit_code: int | None = None,
    duration: str = '',
    *,
    console: 'Console | None' = None,
) -> Panel:
    """Render a shell command as a terminal-style panel.

    Returns a Rich Panel suitable for console.print().
    """
    content_parts = []

    cmd_text = _build_command_text(command)
    content_parts.append(cmd_text)

    meta = _build_meta_line(duration, exit_code)
    if meta:
        content_parts.append(meta)

    if output:
        content_parts.extend(_build_output_preview(output))

    panel_title = Text('Shell', style='bold #f6ff8f')
    panel = Panel(
        Group(*content_parts),
        title=panel_title,
        title_align='left',
        border_style=CLR_CARD_BORDER,
        padding=(0, 2),
    )

    return panel
