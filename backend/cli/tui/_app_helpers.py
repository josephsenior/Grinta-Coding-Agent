"""Module-level helper functions for backend.cli.tui.app.

Extracted from app.py to keep the main module under
the per-file LOC budget. Pure code motion.
"""

from __future__ import annotations

import difflib

from rich.text import Text

from backend.cli.tui._app_constants import (
    _FILE_DIFF_AUTO_COLLAPSE_LINES,
    _TERMINAL_MOUSE_REPORT_RE,
    _TERMINAL_ORPHAN_PARAM_TOKEN_RE,
    _WELCOME_FIGLET_CACHE,
    _WELCOME_FIGLET_FALLBACK,
)
from backend.cli.tui.widgets.activity_card import (
    encode_diff_line,
    encode_split_diff_line,
)


def _rich_text(text: str) -> Text:
    """Convert text with potential ANSI and markup to a Rich Text object."""
    return Text.from_ansi(text)


def _strip_ansi(text: str) -> str:
    """Strip all ANSI escape sequences from text using Rich's parser."""
    return _rich_text(text).plain


def _strip_terminal_control_literals(text: str) -> str:
    """Remove terminal mouse reports that some consoles leak as input text."""
    if not text:
        return text
    text = _TERMINAL_MOUSE_REPORT_RE.sub('', text)
    return _TERMINAL_ORPHAN_PARAM_TOKEN_RE.sub('', text)


def _sanitize_terminal_display_text(text: str) -> str:
    """Strip terminal control traffic before rendering PTY output in Textual."""
    if not text:
        return text
    return _strip_terminal_control_literals(_strip_ansi(text))


def _render_thinking_with_diff(text: str) -> Text:
    """Render thinking text as plain muted text."""
    return Text(text or '', style='dim lightgray')


def _count_text_lines(text: str) -> int:
    """Count visible lines in a text blob."""
    return text.count('\n') + 1 if text else 0


def _format_diff_summary(added: int, removed: int) -> str | None:
    """Format a compact add/remove summary for file edit cards."""
    parts: list[str] = []
    if added:
        parts.append(f'+{added}')
    if removed:
        parts.append(f'-{removed}')
    return ' '.join(parts) if parts else None


def _count_unified_diff_changes(diff_text: str | None) -> tuple[int, int]:
    """Count added and removed payload lines in a unified diff."""
    if not diff_text:
        return 0, 0
    added = 0
    removed = 0
    for line in diff_text.splitlines():
        if line.startswith('+') and not line.startswith('+++'):
            added += 1
        elif line.startswith('-') and not line.startswith('---'):
            removed += 1
    return added, removed


def _encode_unified_diff_text(diff_text: str, *, max_lines: int = 200) -> str | None:
    """Encode a unified diff into full-width TUI diff rows."""
    if not diff_text:
        return None

    lines = diff_text.splitlines()
    encoded: list[str] = []
    visible_lines = lines[:max_lines]
    for line in visible_lines:
        if line.startswith(('---', '+++', '@@')):
            kind = 'ctx'
        elif line.startswith('+'):
            kind = 'add'
        elif line.startswith('-'):
            kind = 'rem'
        else:
            kind = 'ctx'
        encoded.append(encode_diff_line(line or ' ', kind))

    remaining = len(lines) - len(visible_lines)
    if remaining > 0:
        encoded.append(encode_diff_line(f'... {remaining} more diff lines', 'ctx'))

    return '\n'.join(encoded) if encoded else None


def _split_combined_diff(diff_text: str) -> list[tuple[str, str]]:
    """Split a combined unified diff (multi-file) into per-file (path, diff_text) pairs.

    Standard unified diff separates files with ``--- a/path`` / ``+++ b/b/path``
    headers. This function splits on those boundaries.
    """
    per_file: list[tuple[str, str]] = []
    current_lines: list[str] = []
    current_path: str | None = None

    for line in diff_text.splitlines():
        if line.startswith('--- '):
            if current_path and current_lines:
                per_file.append((current_path, '\n'.join(current_lines)))
            current_lines = [line]
            current_path = None
        elif line.startswith('+++ ') and current_path is None:
            raw = line[4:].strip()
            if raw.startswith('b/'):
                raw = raw[2:]
            if raw and raw != '/dev/null':
                current_path = raw
            current_lines.append(line)
        else:
            current_lines.append(line)

    if current_path and current_lines:
        per_file.append((current_path, '\n'.join(current_lines)))

    return per_file


def _numbered_diff_line(kind: str, line_no: int, line: str, pad: int) -> str:
    prefix = {'add': '+', 'rem': '-'}.get(kind, ' ')
    return f'{prefix}{line_no:>{pad}}|{line}'


def _encode_split_diff_contents(
    old_content: str,
    new_content: str,
    *,
    max_lines: int = 200,
    n_context_lines: int = 3,
) -> str | None:
    """Encode before/after text into aligned two-pane TUI diff rows."""
    old_lines = old_content.split('\n')
    new_lines = new_content.split('\n')
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    encoded: list[str] = []
    for group_idx, group in enumerate(matcher.get_grouped_opcodes(n_context_lines)):
        if group_idx > 0:
            encoded.append(encode_split_diff_line('...', '...', 'ctx', 'ctx'))
        max_line_no = max((op[2] for op in group), default=0)
        max_line_no = max(max_line_no, max((op[4] for op in group), default=0))
        pad = max(1, len(str(max_line_no)))
        for tag, i1, i2, j1, j2 in group:
            for row in _split_diff_opcode_rows(
                tag,
                old_lines,
                new_lines,
                i1,
                i2,
                j1,
                j2,
                pad,
            ):
                if len(encoded) >= max_lines:
                    encoded.append(
                        encode_split_diff_line(
                            '... more diff rows',
                            '... more diff rows',
                            'ctx',
                            'ctx',
                        )
                    )
                    return '\n'.join(encoded)
                encoded.append(
                    encode_split_diff_line(
                        row[0],
                        row[1],
                        row[2],
                        row[3],
                    )
                )
    return '\n'.join(encoded) if encoded else None


def _split_diff_opcode_rows(
    tag: str,
    old_lines: list[str],
    new_lines: list[str],
    i1: int,
    i2: int,
    j1: int,
    j2: int,
    pad: int,
) -> list[tuple[str, str, str, str]]:
    handlers = {
        'equal': _equal_rows,
        'delete': _delete_rows,
        'insert': _insert_rows,
        'replace': _replace_rows,
    }
    handler = handlers.get(tag)
    if handler is None:
        return []
    return handler(old_lines, new_lines, i1, i2, j1, j2, pad)


def _equal_rows(
    old_lines: list[str], new_lines: list[str],
    i1: int, i2: int, j1: int, j2: int, pad: int,
) -> list[tuple[str, str, str, str]]:
    rows = []
    for offset, old_index in enumerate(range(i1, i2)):
        new_index = j1 + offset
        rows.append((
            _numbered_diff_line('ctx', old_index + 1, old_lines[old_index], pad),
            _numbered_diff_line('ctx', new_index + 1, new_lines[new_index], pad),
            'ctx', 'ctx',
        ))
    return rows


def _delete_rows(
    old_lines: list[str], new_lines: list[str],
    i1: int, i2: int, j1: int, j2: int, pad: int,
) -> list[tuple[str, str, str, str]]:
    rows = []
    for old_index in range(i1, i2):
        rows.append((
            _numbered_diff_line('rem', old_index + 1, old_lines[old_index], pad),
            '', 'rem', 'ctx',
        ))
    return rows


def _insert_rows(
    old_lines: list[str], new_lines: list[str],
    i1: int, i2: int, j1: int, j2: int, pad: int,
) -> list[tuple[str, str, str, str]]:
    rows = []
    for new_index in range(j1, j2):
        rows.append((
            '',
            _numbered_diff_line('add', new_index + 1, new_lines[new_index], pad),
            'ctx', 'add',
        ))
    return rows


def _replace_rows(
    old_lines: list[str], new_lines: list[str],
    i1: int, i2: int, j1: int, j2: int, pad: int,
) -> list[tuple[str, str, str, str]]:
    rows = []
    old_count = i2 - i1
    new_count = j2 - j1
    for offset in range(max(old_count, new_count)):
        old_index = i1 + offset
        new_index = j1 + offset
        left = (
            _numbered_diff_line('rem', old_index + 1, old_lines[old_index], pad)
            if offset < old_count else ''
        )
        right = (
            _numbered_diff_line('add', new_index + 1, new_lines[new_index], pad)
            if offset < new_count else ''
        )
        rows.append((
            left, right,
            'rem' if left else 'ctx',
            'add' if right else 'ctx',
        ))
    return rows


def _join_secondary_parts(*parts: str | None) -> str | None:
    """Join compact secondary labels while skipping blanks."""
    values = [part for part in parts if part]
    return ' · '.join(values) if values else None


def _extract_tagged_block(content: str, start_tag: str, end_tag: str) -> str | None:
    """Return the first non-empty tagged block from an observation content string."""
    start = content.find(start_tag)
    if start == -1:
        return None
    body_start = start + len(start_tag)
    end = content.find(end_tag, body_start)
    if end == -1:
        return None
    block = content[body_start:end].strip()
    return block or None


def _should_collapse_file_diff(diff_text: str) -> bool:
    return len(diff_text.splitlines()) > _FILE_DIFF_AUTO_COLLAPSE_LINES


def _get_welcome_figlet() -> str:
    global _WELCOME_FIGLET_CACHE
    if _WELCOME_FIGLET_CACHE is not None:
        return _WELCOME_FIGLET_CACHE
    try:
        import pyfiglet as _pyfiglet

        _WELCOME_FIGLET_CACHE = _pyfiglet.figlet_format('GRINTA', font='slant').rstrip(
            '\n'
        )
    except Exception:
        _WELCOME_FIGLET_CACHE = '\n'.join(_WELCOME_FIGLET_FALLBACK)
    return _WELCOME_FIGLET_CACHE
