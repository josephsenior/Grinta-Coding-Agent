"""Read/write/insert/replace method bodies for FileEditor.

These module functions are the extracted method bodies for the
low-level read, write, and line-manipulation methods on
``_FileEditorOpsMixin``. They are called as one-line forwarders
from the mixin class. Module functions invoke other methods via
``self._method(...)`` so that monkey-patching of the class
methods in tests still works.

Extracted from ``backend.execution.utils._file_editor_ops_mixin`` to
keep that module focused on the ops mixin class.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Literal

from backend.execution.utils._file_editor_io_helpers import (
    _encode_disk_payload,
    _FileReadMeta,
    _normalize_newlines_for_metadata,
)
from backend.execution.utils._file_editor_types import ToolResult
from backend.execution.utils._file_editor_view_mixin import _detect_indentation_mismatch


def read_file_with_meta_impl(
    self, file_path: Path
) -> tuple[str, _FileReadMeta]:
    """Read text and capture encoding + newline style for symmetric writes."""
    raw = file_path.read_bytes()
    if not raw:
        return '', _FileReadMeta(encoding='utf-8', newline='lf', had_bom=False)

    had_bom = False
    if raw.startswith(b'\xff\xfe'):
        text = raw[2:].decode('utf-16-le')
        encoding = 'utf-16-le'
        had_bom = True
    elif raw.startswith(b'\xfe\xff'):
        text = raw[2:].decode('utf-16-be')
        encoding = 'utf-16-be'
        had_bom = True
    elif raw.startswith(b'\xef\xbb\xbf'):
        text = raw[3:].decode('utf-8')
        encoding = 'utf-8-sig'
        had_bom = True
    else:
        try:
            text = raw.decode('utf-8')
            encoding = 'utf-8'
        except UnicodeDecodeError:
            text = raw.decode('latin-1')
            encoding = 'latin-1'

    crlf = text.count('\r\n')
    lone_lf = text.count('\n') - crlf
    newline: Literal['crlf', 'lf'] = (
        'crlf' if crlf > 0 and crlf >= lone_lf else 'lf'
    )
    return text, _FileReadMeta(encoding=encoding, newline=newline, had_bom=had_bom)


def read_file_impl(self, file_path: Path) -> str:
    """Read file content with encoding + BOM handling; remember I/O metadata."""
    text, meta = self._read_file_with_meta(file_path)
    self._remember_io_meta(file_path, meta)
    return text


def recent_write_key_impl(file_path: Path) -> str:
    try:
        return str(file_path.resolve())
    except OSError:
        return str(file_path)


def record_recent_write_impl(self, file_path: Path) -> None:
    """Stamp the path in ``_recent_writes`` after a successful write.

    Used by :meth:`_handle_replace_string` to detect the "stale
    old_string" case where the model has chained several
    ``replace_string`` calls on the same file in one turn. Entries are
    bounded so a long-lived editor instance does not grow unboundedly.
    """
    recent = getattr(self, '_recent_writes', None)
    if recent is None:
        return
    key = self._recent_write_key(file_path)
    recent[key] = time.monotonic()
    if len(recent) > 256:
        oldest_key = min(recent, key=recent.get)
        recent.pop(oldest_key, None)


def was_recently_written_impl(
    self, file_path: Path, *, window_seconds: float = 30.0
) -> bool:
    """True if the path was written to within ``window_seconds``.

    Only meaningful on instances that have actually performed writes;
    older instances without the attribute simply return ``False``.
    """
    recent = getattr(self, '_recent_writes', None)
    if not recent:
        return False
    last = recent.get(self._recent_write_key(file_path))
    if last is None:
        return False
    return (time.monotonic() - last) <= window_seconds


def write_file_impl(self, file_path: Path, content: str) -> str:
    """Write file atomically, preserving prior encoding/newline style when known."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = file_path.with_suffix(file_path.suffix + '.tmp')
    meta = self._take_io_meta(file_path)
    if meta is None:
        meta = _FileReadMeta(encoding='utf-8', newline='lf', had_bom=False)

    content = _normalize_newlines_for_metadata(content, meta)
    data = _encode_disk_payload(content, meta)

    try:
        temp_path.write_bytes(data)
        temp_path.replace(file_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise
    return content


def insert_at_line_impl(self, content: str, new_text: str, line_num: int) -> str:
    """Insert text at a specific line number (1-indexed)."""
    lines = content.splitlines(keepends=True)
    if not lines:
        lines = ['']

    if content and new_text and not new_text.endswith(('\n', '\r')):
        new_text = f'{new_text}{self._line_ending_for_content(content)}'

    line_idx = max(0, min(line_num - 1, len(lines)))

    new_lines = new_text.splitlines(keepends=True)
    if not new_lines:
        new_lines = [new_text]

    result_lines = lines[:line_idx] + new_lines + lines[line_idx:]
    return ''.join(result_lines)


def replace_range_impl(
    self,
    content: str,
    new_text: str,
    start_line: int,
    end_line: int,
    expected_hash: str | None = None,
) -> str | ToolResult:
    """Replace a range of lines with new text."""
    content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
    if expected_hash and content_hash != expected_hash:
        return ToolResult(
            output='',
            error=(
                'FILE_UNEXPECTEDLY_MODIFIED: file changed since it was read. '
                'Re-read the file and retry the edit.'
            ),
            old_content=content,
            new_content=content,
        )

    lines = content.splitlines(keepends=True)

    if not lines:
        if start_line == 1:
            return new_text
        return ToolResult(
            output='',
            error=f'Cannot edit range {start_line}-{end_line} in an empty file.',
            new_content=content,
        )

    if start_line < 1:
        return ToolResult(
            output='',
            error=f'Start line must be >= 1 (got {start_line})',
            new_content=content,
        )

    if end_line < start_line:
        return ToolResult(
            output='',
            error=f'end_line must be >= start_line (got start={start_line}, end={end_line})',
            new_content=content,
        )

    start_idx = start_line - 1
    end_idx = end_line

    if start_idx >= len(lines):
        return ToolResult(
            output='',
            error=f'Start line {start_line} is beyond file length ({len(lines)} lines)',
            new_content=content,
        )

    end_idx = min(end_idx, len(lines))

    original_newline = '\r\n' if '\r\n' in content else '\n'
    new_text_normalized = new_text.replace('\r\n', '\n').replace('\r', '\n')
    if original_newline == '\r\n':
        new_text_normalized = new_text_normalized.replace('\n', '\r\n')

    is_eof_replacement = end_idx >= len(lines)
    if (
        not is_eof_replacement
        and new_text_normalized
        and not new_text_normalized.endswith(original_newline)
    ):
        new_text_normalized += original_newline

    new_lines_to_insert = new_text_normalized.splitlines(keepends=True)

    result_lines = lines[:start_idx] + new_lines_to_insert + lines[end_idx:]

    self._last_indent_warnings = _detect_indentation_mismatch(
        lines, new_lines_to_insert, start_idx
    )

    return ''.join(result_lines)
