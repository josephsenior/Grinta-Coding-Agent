"""Pure file-event helpers (no orchestrator dependency)."""

from __future__ import annotations

from typing import Any

from backend.cli.tui.helpers import (
    _count_text_lines,
    _encode_diff_view_from_contents,
    _extract_tagged_block,
)
from backend.ledger.observation import FileEditObservation, FileWriteObservation


def file_read_range_from_view_range(view_range: Any) -> str | None:
    if view_range and len(view_range) == 2:
        return f'{view_range[0]}:{view_range[1]}'
    return None


def file_read_range_from_bounds(start: int, end: int) -> str:
    if start not in (0, 1) or end != -1:
        end_str = str(end) if end != -1 else 'end'
        return f'{start}:{end_str}'
    return ''


def resolve_file_read_line_range(view_range: Any, start: int, end: int) -> str:
    result = file_read_range_from_view_range(view_range)
    if result is not None:
        return result
    return file_read_range_from_bounds(start, end)


def create_file_line_count(new_content: str, added: int | None = None) -> int:
    if added:
        return added
    return _count_text_lines(new_content)


def encode_create_file_diff(path: str, new_content: str) -> str | None:
    if not (new_content or '').strip():
        return None
    return _encode_diff_view_from_contents('', new_content, path=path)


def resolve_edit_mode_range(
    event: Any,
    start_line: int | None,
    end_line: int | None,
) -> tuple[str, str] | None:
    edit_mode = getattr(event, 'edit_mode', '')
    if edit_mode == 'range' and start_line is not None and end_line is not None:
        return 'Edited', f'{start_line}:{end_line}'
    return None


def resolve_no_cmd_line_range(start: int, end: int) -> tuple[str, str]:
    end_str = str(end) if end != -1 else 'end'
    return 'Edited', f'{start}:{end_str}'


def clean_file_edit_content(event: FileEditObservation) -> None:
    if hasattr(event, 'content') and event.content:
        from backend.cli.display.transcript import strip_indentation_warnings

        event.content = strip_indentation_warnings(event.content)


def file_write_observation_diff(event: FileWriteObservation) -> str | None:
    explicit = getattr(event, 'diff', None)
    if isinstance(explicit, str) and explicit.strip():
        return explicit
    return _extract_tagged_block(
        str(getattr(event, 'content', '') or ''),
        '<DIFF_PREVIEW>',
        '</DIFF_PREVIEW>',
    )
