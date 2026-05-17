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


def _build_command_text(command: str) -> Text:
    """Build styled command text with syntax-aware highlighting."""
    text = Text()
    text.append('PS> ', style='bold #91abec')

    cmd = command.strip()
    if len(cmd) > 120:
        cmd = cmd[:117] + '…'

    # Highlight common PowerShell/Shell patterns
    parts = []
    current = ''
    in_string = False
    string_char = ''
    i = 0
    while i < len(cmd):
        ch = cmd[i]
        if not in_string and ch in ('"', "'"):
            if current:
                parts.append(('cmd', current))
                current = ''
            in_string = True
            string_char = ch
            current = ch
        elif in_string and ch == string_char:
            current += ch
            parts.append(('string', current))
            current = ''
            in_string = False
        elif in_string:
            current += ch
        elif ch == ' ' and current:
            # Check if it's a known command
            lower = current.lower()
            if lower in (
                'cd',
                'ls',
                'dir',
                'pwd',
                'cat',
                'echo',
                'type',
                'mkdir',
                'rm',
                'del',
                'copy',
                'move',
                'ren',
                'git',
                'npm',
                'pip',
                'python',
                'node',
                'cargo',
                'go',
                'rustc',
                'make',
                'cmake',
                'docker',
                'kubectl',
                'curl',
                'wget',
                'ssh',
                'scp',
                'rsync',
                'tar',
                'zip',
                'unzip',
                'grep',
                'find',
                'awk',
                'sed',
                'head',
                'tail',
                'sort',
                'uniq',
                'wc',
                'tee',
                'xargs',
                'env',
                'export',
                'source',
                'bash',
                'sh',
                'zsh',
                'fish',
                'pwsh',
                'powershell',
                'cmd',
                'set',
                'if',
                'for',
                'while',
                'foreach',
                'switch',
                'function',
                'param',
                'return',
                'exit',
                'break',
                'continue',
                'throw',
                'try',
                'catch',
                'finally',
                'using',
                'class',
                'enum',
                'workflow',
                'configuration',
                'inlinescript',
                'parallel',
                'sequence',
            ):
                parts.append(('keyword', current))
            elif lower.startswith('-') or lower.startswith('/'):
                parts.append(('flag', current))
            elif '=' in current and not current.startswith('$'):
                parts.append(('assignment', current))
            else:
                parts.append(('arg', current))
            current = ''
            parts.append(('space', ' '))
        else:
            current += ch
        i += 1

    if current:
        lower = current.lower()
        if lower in (
            'cd',
            'ls',
            'dir',
            'pwd',
            'cat',
            'echo',
            'type',
            'mkdir',
            'rm',
            'del',
            'copy',
            'move',
            'ren',
            'git',
            'npm',
            'pip',
            'python',
            'node',
            'cargo',
            'go',
            'rustc',
            'make',
            'cmake',
            'docker',
            'kubectl',
            'curl',
            'wget',
            'ssh',
            'scp',
            'rsync',
            'tar',
            'zip',
            'unzip',
            'grep',
            'find',
            'awk',
            'sed',
            'head',
            'tail',
            'sort',
            'uniq',
            'wc',
            'tee',
            'xargs',
            'env',
            'export',
            'source',
            'bash',
            'sh',
            'zsh',
            'fish',
            'pwsh',
            'powershell',
            'cmd',
            'set',
            'if',
            'for',
            'while',
            'foreach',
            'switch',
            'function',
            'param',
            'return',
            'exit',
            'break',
            'continue',
            'throw',
            'try',
            'catch',
            'finally',
            'using',
            'class',
            'enum',
            'workflow',
            'configuration',
            'inlinescript',
            'parallel',
            'sequence',
        ):
            parts.append(('keyword', current))
        elif lower.startswith('-') or lower.startswith('/'):
            parts.append(('flag', current))
        elif '=' in current and not current.startswith('$'):
            parts.append(('assignment', current))
        else:
            parts.append(('arg', current))

    style_map = {
        'keyword': 'bold #e9e9e9',
        'string': '#54efae',
        'flag': '#f6ff8f',
        'assignment': '#91abec',
        'arg': NAVY_TEXT_PRIMARY,
        'space': '',
        'cmd': NAVY_TEXT_PRIMARY,
    }

    for kind, value in parts:
        text.append(value, style=style_map.get(kind, ''))

    return text


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

    # Command line with prompt
    cmd_text = _build_command_text(command)
    content_parts.append(cmd_text)

    # Duration and exit code on same line
    meta_parts = []
    if duration:
        meta_parts.append(Text(duration, style=NAVY_TEXT_DIM))
    if exit_code is not None:
        if exit_code == 0:
            meta_parts.append(Text(f'  exit {exit_code}', style=CLR_STATUS_OK))
        else:
            meta_parts.append(Text(f'  exit {exit_code}', style=CLR_STATUS_ERR))

    if meta_parts:
        meta_line = Text()
        for i, part in enumerate(meta_parts):
            if i > 0:
                meta_line.append('  ')
            meta_line.append(part)
        content_parts.append(meta_line)

    # Output preview
    if output:
        raw_lines = [ln for ln in output.splitlines()]
        preview = raw_lines[:8]

        if preview:
            content_parts.append(Text(''))  # spacer
            for line in preview:
                if len(line) > 120:
                    line = line[:117] + '…'
                content_parts.append(Text(line, style=NAVY_TEXT_MUTED))

            if len(raw_lines) > 8:
                content_parts.append(
                    Text(f'... {len(raw_lines) - 8} more lines', style=NAVY_TEXT_DIM)
                )

    # Build panel
    panel_title = Text('Shell', style='bold #f6ff8f')
    panel = Panel(
        Group(*content_parts),
        title=panel_title,
        title_align='left',
        border_style=CLR_CARD_BORDER,
        padding=(0, 2),
    )

    return panel
