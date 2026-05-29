"""Shared edit-operation helpers for FileEditor."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def _file_editor_module():
    from backend.execution.utils import file_editor as fe

    return fe


def _tool_result(**kwargs):
    return _file_editor_module().ToolResult(**kwargs)


def resolve_edit_content(file_text_val: str | None, new_str_val: str | None) -> str:
    return new_str_val or file_text_val or ''


def line_ending_for_content(content: str) -> str:
    if '\r\n' in content:
        return '\r\n'
    return '\n'


def _apply_edit_implicit(
    editor: Any,
    old_content_str: str,
    file_text_val: str | None,
    new_str_val: str | None,
    insert_line: int | None,
    start_line: int | None,
    end_line: int | None,
) -> str | Any:
    """Insert/range/full-file paths when ``edit_mode`` is unset."""
    if start_line is not None and end_line is not None:
        return editor._replace_range(
            old_content_str,
            resolve_edit_content(file_text_val, new_str_val),
            start_line,
            end_line,
        )
    if insert_line is not None:
        return editor._insert_at_line(
            old_content_str,
            resolve_edit_content(file_text_val, new_str_val),
            insert_line,
        )
    if file_text_val:
        return file_text_val
    return _tool_result(
        output='',
        error=(
            'Deterministic edit failed: when edit_mode is not provided, '
            'you must provide start_line/end_line (range) or insert_line (insert).'
        ),
        new_content=old_content_str,
    )


def apply_edit_logic(
    editor: Any,
    old_content_str: str,
    file_text_val: str | None,
    new_str_val: str | None,
    insert_line: int | None,
    start_line: int | None,
    end_line: int | None,
    *,
    edit_mode: str | None = None,
    expected_hash: str | None = None,
    file_path: Path | None = None,
) -> str | Any:
    resolved_mode = (edit_mode or '').strip().lower() or None

    def branch_range() -> str | Any:
        missing = []
        if start_line is None:
            missing.append('start_line')
        if end_line is None:
            missing.append('end_line')
        if missing:
            if len(missing) == 1:
                missing_str = missing[0]
            else:
                missing_str = 'start_line and end_line (both)'
            return _tool_result(
                output='',
                error=(
                    f'[ERROR] edit_mode=range requires start_line and end_line. '
                    f'[CAUSE] {missing_str} {"was" if len(missing) == 1 else "were"} omitted from the tool call. '
                    f'[SUGGESTION] Provide both start_line and end_line as integers (1-based, inclusive) '
                    f'alongside new_str. '
                    f'Example: {{"command": "edit", "edit_mode": "range", "start_line": 1, '
                    f'"end_line": 10, "new_str": "...replacement text..."}}.'
                ),
                new_content=old_content_str,
            )
        assert start_line is not None
        assert end_line is not None
        return replace_range_guarded(
            editor,
            old_content_str,
            resolve_edit_content(file_text_val, new_str_val),
            start_line,
            end_line,
            expected_hash=expected_hash,
        )

    if resolved_mode == 'range':
        return branch_range()
    if resolved_mode is not None:
        return _tool_result(
            output='',
            error=f'Unsupported edit_mode: {resolved_mode!r}',
            new_content=old_content_str,
        )
    return _apply_edit_implicit(
        editor,
        old_content_str,
        file_text_val,
        new_str_val,
        insert_line,
        start_line,
        end_line,
    )


def slice_text_by_line_range(content: str, start_line: int, end_line: int) -> str:
    lines = content.splitlines(keepends=True)
    if not lines or start_line < 1:
        return ''
    start_idx = start_line - 1
    end_idx = min(len(lines), end_line)
    if start_idx >= len(lines):
        return ''
    return ''.join(lines[start_idx:end_idx])


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def replace_range_guarded(
    editor: Any,
    content: str,
    new_text: str,
    start_line: int,
    end_line: int,
    *,
    expected_hash: str | None = None,
) -> str | Any:
    if expected_hash:
        current_slice = slice_text_by_line_range(content, start_line, end_line)
        if sha256_text(current_slice) != expected_hash:
            return _tool_result(
                output='',
                error='Range guard failed: expected_hash does not match target slice.',
                new_content=content,
            )
    return editor._replace_range(content, new_text, start_line, end_line)
