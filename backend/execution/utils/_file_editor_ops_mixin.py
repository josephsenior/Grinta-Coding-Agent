"""View, Edit, Write, and Read/Write primitive methods for FileEditor.

Pure code motion: split from ``backend.execution.utils.file_editor`` to
keep that module under the 40 KB file-size cap. No logic changes.
"""

from __future__ import annotations

import difflib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from backend.core.type_safety.path_validation import SafePath
from backend.core.type_safety.sentinels import MISSING, Sentinel, is_missing
from backend.execution.utils._file_editor_types import ToolResult
from backend.execution.utils._file_editor_view_mixin import _detect_indentation_mismatch

def _find_changed_ranges(
    old_lines: list[str],
    new_lines: list[str],
) -> list[tuple[int, int]]:
    """Find ranges of changed lines in the new content.

    Returns list of (start, end) tuples for changed regions.
    """
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    changed: list[tuple[int, int]] = []

    for tag, _, _, j1, j2 in matcher.get_opcodes():
        if tag != 'equal' and j2 > j1:
            changed.append((j1, j2))

    return changed
def _merge_ranges_with_context(
    changed_ranges: list[tuple[int, int]],
    total_lines: int,
    context_lines: int,
) -> list[tuple[int, int]]:
    """Merge overlapping changed ranges and add context padding."""
    merged: list[tuple[int, int]] = []

    for start, end in changed_ranges:
        ctx_start = max(0, start - context_lines)
        ctx_end = min(total_lines, end + context_lines)

        if merged and ctx_start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], ctx_end))
        else:
            merged.append((ctx_start, ctx_end))

    return merged
def _format_range_lines(
    new_lines: list[str],
    changed_ranges: list[tuple[int, int]],
    ctx_start: int,
    ctx_end: int,
    total_lines: int,
) -> list[str]:
    """Format lines for a single context range with line numbers and markers."""
    output: list[str] = []

    header = (
        f'Updated file view (lines {ctx_start + 1}-{ctx_end} of {total_lines}):'
        if ctx_start > 0 or ctx_end < total_lines
        else f'Updated file view ({total_lines} lines):'
    )
    output.append(header)

    for i in range(ctx_start, ctx_end):
        line_num = i + 1
        is_changed = any(start <= i < end for start, end in changed_ranges)
        marker = '>>> ' if is_changed else '    '
        line_content = new_lines[i] if i < len(new_lines) else ''
        output.append(f'{marker}{line_num}\t{line_content}')

    return output
def _format_context_window(
    old_content: str,
    new_content: str,
    context_lines: int = 5,
) -> str:
    """Generate a context window showing the edited region with line numbers.

    Uses difflib to find changed lines, then shows a window of context_lines
    before and after each change region. Edited lines are marked with '>>> '.

    Args:
        old_content: Original file content.
        new_content: Updated file content.
        context_lines: Number of context lines before/after changes.

    Returns:
        Formatted string with line numbers and context window.
    """
    old_lines = old_content.splitlines() if old_content else []
    new_lines = new_content.splitlines() if new_content else []

    changed_ranges = _find_changed_ranges(old_lines, new_lines)
    if not changed_ranges:
        return ''

    merged_ranges = _merge_ranges_with_context(
        changed_ranges, len(new_lines), context_lines
    )

    output_parts: list[str] = []
    total_lines = len(new_lines)

    for idx, (ctx_start, ctx_end) in enumerate(merged_ranges):
        if idx > 0:
            output_parts.append('...')
        output_parts.extend(
            _format_range_lines(
                new_lines, changed_ranges, ctx_start, ctx_end, total_lines
            )
        )

    return '\n'.join(output_parts)
def _to_changed_line_spans(
    old_content: str | None, new_content: str | None
) -> list[dict[str, int]]:
    """Return compact 1-based inclusive line spans for changed regions."""
    if old_content is None or new_content is None:
        return []
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()
    spans: list[dict[str, int]] = []
    for start, end in _find_changed_ranges(old_lines, new_lines):
        if end <= start:
            continue
        spans.append({'start_line': start + 1, 'end_line': end})
    return spans
@dataclass(frozen=True)
class _FileReadMeta:
    """Encoding and newline style for round-tripping disk I/O."""

    encoding: str
    newline: Literal['crlf', 'lf']
    had_bom: bool

_QUOTE_TRANSLATE = str.maketrans(
    {
        '\u201c': '"',
        '\u201d': '"',
        '\u2018': "'",
        '\u2019': "'",
    }
)
def normalize_quotes(s: str) -> str:
    """Map typographic quotes to straight quotes (Claude Code normalizeQuotes)."""
    return s.translate(_QUOTE_TRANSLATE)
def _compose_create_file_success_message(content: str) -> str:
    preview_lines = content.splitlines()[:20]
    preview_str = '\n'.join(f'{i + 1}\t{line}' for i, line in enumerate(preview_lines))
    if len(content.splitlines()) > 20:
        preview_str += '\n...\n(File truncated)'
    line_end_desc = '\\r\\n' if '\r\n' in content else '\\n'
    return (
        'File created successfully. '
        f'Line endings: {line_end_desc}. File preview:\n{preview_str}'
    )

def _compose_write_success_message(
    *,
    is_create: bool,
    content: str,
    soft_warning: str,
) -> str:
    if is_create:
        output_msg = _compose_create_file_success_message(content)
    else:
        output_msg = 'File written successfully'
    if soft_warning:
        output_msg = f'{output_msg}\n{soft_warning}'
    return output_msg
def _normalize_newlines_for_metadata(content: str, meta: _FileReadMeta) -> str:
    if meta.newline == 'crlf':
        content = content.replace('\r\n', '\n')
        content = content.replace('\r', '')
        return content.replace('\n', '\r\n')
    return content
def _encode_disk_payload(content: str, meta: _FileReadMeta) -> bytes:
    if meta.encoding == 'utf-16-le':
        return b'\xff\xfe' + content.encode('utf-16-le')
    if meta.encoding == 'utf-16-be':
        return b'\xfe\xff' + content.encode('utf-16-be')
    if meta.encoding == 'utf-8-sig' or (meta.had_bom and meta.encoding == 'utf-8'):
        return b'\xef\xbb\xbf' + content.encode('utf-8')
    if meta.encoding == 'latin-1':
        return content.encode('latin-1')
    return content.encode('utf-8')
_LARGE_EXISTING_CODE_FILE_LINES = 200
_CODE_FILE_SUFFIXES: frozenset[str] = frozenset(
    {
        '.py',
        '.js',
        '.jsx',
        '.ts',
        '.tsx',
        '.go',
        '.rs',
        '.java',
        '.c',
        '.cpp',
        '.cc',
        '.cxx',
        '.h',
        '.hpp',
        '.cs',
        '.rb',
        '.php',
        '.swift',
        '.kt',
        '.scala',
    }
)
def _is_large_existing_code_file(file_path: Path, content: str | None) -> bool:
    if content is None or file_path.suffix.lower() not in _CODE_FILE_SUFFIXES:
        return False
    return len(content.splitlines()) >= _LARGE_EXISTING_CODE_FILE_LINES


class _FileEditorOpsMixin:
    def _handle_edit(
        self,
        file_path: Path,
        file_text: str | Sentinel | None,
        new_str: str | Sentinel | None,
        insert_line: int | None,
        start_line: int | None,
        end_line: int | None,
        *,
        edit_mode: str | None = None,
        expected_hash: str | None = None,
        expected_file_hash: str | None = None,
        dry_run: bool = False,
    ) -> ToolResult:
        """Handle edit command - modify file content."""
        try:
            old_content = self._read_file(file_path) if file_path.exists() else None
            old_content_str = old_content or ''

            file_text_val, new_str_val = self._extract_edit_params(file_text, new_str)

            new_content = self._apply_edit_logic(
                old_content_str,
                file_text_val,
                new_str_val,
                insert_line,
                start_line,
                end_line,
                edit_mode=edit_mode,
                expected_hash=expected_hash,
                file_path=file_path,
            )
            if isinstance(new_content, ToolResult):
                new_content.old_content = old_content
                return new_content

            target_kind = (
                'range'
                if (edit_mode or '').strip().lower() == 'range'
                else ('insert' if insert_line is not None else 'text')
            )

            return self._finalize_edit_result(
                file_path,
                old_content,
                new_content,
                dry_run,
                target_kind=target_kind,
                requested_start_line=start_line,
                requested_end_line=end_line,
            )

        except Exception as e:
            return ToolResult(
                output='',
                error=f'Error editing file: {e}',
                old_content=None,
                new_content=None,
            )

    def _handle_replace_string(
        self,
        file_path: Path,
        old_string: str | None,
        new_string: str,
        *,
        replace_all: bool,
        dry_run: bool,
    ) -> ToolResult:
        """Replace exact text occurrences using the safe edit pipeline."""
        try:
            if old_string is None or old_string == '':
                return ToolResult(
                    output='',
                    error='replace_string old_string must not be empty.',
                    error_code='EMPTY_OLD_STRING',
                    retryable=False,
                    operation='replace_string',
                )
            preflight = self._preflight_content_guard(file_path, new_string)
            if preflight is not None:
                return ToolResult(
                    output='',
                    error=preflight,
                    error_code='CONTENT_APPEARS_SERIALIZED'
                    if 'CONTENT_APPEARS_SERIALIZED' in preflight
                    else 'CONTENT_PREFLIGHT_FAILED',
                    retryable=False,
                    operation='replace_string',
                )
            if not file_path.exists():
                return ToolResult(
                    output='',
                    error=f'File not found: {file_path}',
                    error_code='FILE_NOT_FOUND',
                    retryable=False,
                    operation='replace_string',
                )

            old_content = self._read_file(file_path)
            newline = '\r\n' if '\r\n' in old_content else '\n'
            old_match = old_string.replace('\r\n', '\n').replace('\r', '\n')
            new_replacement = new_string.replace('\r\n', '\n').replace('\r', '\n')
            if newline == '\r\n':
                old_match = old_match.replace('\n', '\r\n')
                new_replacement = new_replacement.replace('\n', '\r\n')

            match_count = old_content.count(old_match)
            if match_count == 0:
                return ToolResult(
                    output='',
                    error='replace_string old_string was not found exactly.',
                    old_content=old_content,
                    new_content=old_content,
                    error_code='OLD_STRING_NOT_FOUND',
                    retryable=True,
                    operation='replace_string',
                    metadata={'match_count': 0},
                )
            if match_count > 1 and not replace_all:
                return ToolResult(
                    output='',
                    error=(
                        'replace_string old_string matched multiple occurrences. '
                        'Make old_string more specific or set replace_all=true.'
                    ),
                    old_content=old_content,
                    new_content=old_content,
                    error_code='OLD_STRING_NOT_UNIQUE',
                    retryable=True,
                    operation='replace_string',
                    metadata={'match_count': match_count},
                )

            new_content = old_content.replace(
                old_match,
                new_replacement,
                -1 if replace_all else 1,
            )
            return self._finalize_edit_result(
                file_path,
                old_content,
                new_content,
                dry_run,
                target_kind='exact_string',
            )
        except Exception as e:
            return ToolResult(
                output='',
                error=f'Error replacing string: {e}',
                old_content=None,
                new_content=None,
                error_code='REPLACE_STRING_ERROR',
                retryable=True,
                operation='replace_string',
            )

    def _build_receipt(
        self,
        *,
        file_path: Path,
        old_content: str | None,
        new_content: str | None,
        operation: str,
        target_kind: str,
        verification_passed: bool,
        requested_start_line: int | None = None,
        requested_end_line: int | None = None,
        rollback_available: bool = True,
    ) -> dict[str, Any]:
        return {
            'path': str(file_path),
            'pre_hash': self._sha256_text(old_content or ''),
            'post_hash': self._sha256_text(new_content or ''),
            'operation': operation,
            'target_kind': target_kind,
            'changed_line_spans': _to_changed_line_spans(old_content, new_content),
            'verification_passed': verification_passed,
            'rollback_available': rollback_available,
            'requested_start_line': requested_start_line,
            'requested_end_line': requested_end_line,
        }

    def _verify_post_write(
        self,
        *,
        file_path: Path,
        expected_content: str,
        old_content: str | None,
        operation: str,
        target_kind: str,
        requested_start_line: int | None = None,
        requested_end_line: int | None = None,
    ) -> ToolResult | None:
        actual_content = self._read_file(file_path)
        if actual_content == expected_content:
            return None
        receipt = self._build_receipt(
            file_path=file_path,
            old_content=old_content,
            new_content=actual_content,
            operation=operation,
            target_kind=target_kind,
            verification_passed=False,
            requested_start_line=requested_start_line,
            requested_end_line=requested_end_line,
        )
        return ToolResult(
            output='',
            error=(
                'EDIT_VERIFICATION_FAILED: file contents on disk did not match the intended write. '
                'Re-read the file and retry with a smaller verified edit.'
            ),
            old_content=old_content,
            new_content=actual_content,
            error_code='EDIT_VERIFICATION_FAILED',
            retryable=True,
            operation=operation,
            metadata=receipt,
        )

    def _finalize_edit_result(
        self,
        file_path: Path,
        old_content: str | None,
        new_content: str,
        dry_run: bool,
        *,
        target_kind: str,
        requested_start_line: int | None = None,
        requested_end_line: int | None = None,
    ) -> ToolResult:
        """Finalize edit result with dry-run, no-change, or write handling."""
        if dry_run:
            return self._build_dry_run_result(
                file_path,
                old_content,
                new_content,
                operation='edit_preview',
                target_kind=target_kind,
                requested_start_line=requested_start_line,
                requested_end_line=requested_end_line,
            )

        if old_content == new_content:
            return ToolResult(
                output='No changes applied (content unchanged).',
                old_content=old_content,
                new_content=new_content,
                operation='edit_noop',
                metadata=self._build_receipt(
                    file_path=file_path,
                    old_content=old_content,
                    new_content=new_content,
                    operation='edit_noop',
                    target_kind=target_kind,
                    verification_passed=True,
                    requested_start_line=requested_start_line,
                    requested_end_line=requested_end_line,
                ),
            )

        return self._write_edit_result(
            file_path,
            old_content,
            new_content,
            target_kind=target_kind,
            requested_start_line=requested_start_line,
            requested_end_line=requested_end_line,
        )

    def _build_dry_run_result(
        self,
        file_path: Path,
        old_content: str | None,
        new_content: str,
        *,
        operation: str,
        target_kind: str,
        requested_start_line: int | None = None,
        requested_end_line: int | None = None,
    ) -> ToolResult:
        """Build result for dry-run preview."""
        output = 'Preview generated (no changes applied)'
        if self._last_indent_warnings:
            output += '\n\n[INDENTATION WARNINGS]\n' + '\n'.join(
                self._last_indent_warnings
            )
        return ToolResult(
            output=output,
            old_content=old_content,
            new_content=new_content,
            operation=operation,
            metadata=self._build_receipt(
                file_path=file_path,
                old_content=old_content,
                new_content=new_content,
                operation=operation,
                target_kind=target_kind,
                verification_passed=False,
                requested_start_line=requested_start_line,
                requested_end_line=requested_end_line,
            ),
        )

    def _write_edit_result(
        self,
        file_path: Path,
        old_content: str | None,
        new_content: str,
        *,
        target_kind: str,
        requested_start_line: int | None = None,
        requested_end_line: int | None = None,
    ) -> ToolResult:
        """Write the result of an edit operation to disk."""
        if old_content is not None and file_path.exists():
            disk_now = self._read_file(file_path)
            if disk_now != old_content:
                return ToolResult(
                    output='',
                    error=(
                        'FILE_UNEXPECTEDLY_MODIFIED: file changed on disk since it was read. '
                        'Re-read the file and retry the edit.'
                    ),
                    old_content=old_content,
                    new_content=new_content,
                )

        # Validate syntax where possible before applying the edit to avoid
        # introducing syntax errors into the repository.
        regression_error = self._detect_introduced_syntax_error(
            file_path, old_content, new_content
        )
        if regression_error is not None:
            return ToolResult(
                output='',
                error=regression_error,
                old_content=old_content,
                new_content=new_content,
                error_code='INTRODUCED_SYNTAX_ERROR',
                retryable=True,
                operation='edit_validate',
            )

        is_valid, msg = self._maybe_validate_syntax_for_file(file_path, new_content)
        if not is_valid:
            return ToolResult(
                output='',
                error=f'Syntax validation failed: {msg}',
                old_content=old_content,
                new_content=new_content,
                error_code='SYNTAX_VALIDATION_FAILED',
                retryable=True,
                operation='edit_validate',
            )

        # Backup original if in transaction
        if self._transaction_stack:
            self._backup_file(file_path, old_content)

        self._push_undo_snapshot(file_path, old_content)

        # Write new content
        written_content = self._write_file(file_path, new_content)
        verification_error = self._verify_post_write(
            file_path=file_path,
            expected_content=written_content,
            old_content=old_content,
            operation='edit',
            target_kind=target_kind,
            requested_start_line=requested_start_line,
            requested_end_line=requested_end_line,
        )
        if verification_error is not None:
            return verification_error

        output = 'File updated successfully'

        # Add context window showing the edited region with line numbers
        if old_content is not None:
            context_window = _format_context_window(old_content, new_content)
            if context_window:
                output += '\n\n' + context_window

        # Include indentation warnings if any
        if self._last_indent_warnings:
            output += '\n\n[INDENTATION WARNINGS]\n' + '\n'.join(
                self._last_indent_warnings
            )

        if msg and msg.startswith('WARNING:'):
            output = f'{output}\n{msg}'
        return ToolResult(
            output=output,
            old_content=old_content,
            new_content=written_content,
            operation='edit',
            metadata=self._build_receipt(
                file_path=file_path,
                old_content=old_content,
                new_content=written_content,
                operation='edit',
                target_kind=target_kind,
                verification_passed=True,
                requested_start_line=requested_start_line,
                requested_end_line=requested_end_line,
            ),
        )

    def _handle_write_maybe_short_circuit(
        self,
        *,
        file_path: Path,
        content: str,
        old_content: str | None,
        file_existed: bool,
        is_create: bool,
        dry_run: bool,
        overwrite_existing: bool,
    ) -> ToolResult | None:
        """Early exits before validation / disk write."""
        if is_create and file_existed:
            return ToolResult(
                output='',
                error=(
                    'File already exists. Use edit_symbols or replace_string '
                    'for modifications.'
                ),
                old_content=old_content,
                new_content=content,
                error_code='CREATE_FILE_ALREADY_EXISTS',
                retryable=False,
                operation='create_file',
            )

        if dry_run:
            return ToolResult(
                output='Preview generated (no changes applied)',
                old_content=old_content,
                new_content=content,
                operation='create_file_preview' if is_create else 'write_preview',
                metadata=self._build_receipt(
                    file_path=file_path,
                    old_content=old_content,
                    new_content=content,
                    operation='create_file_preview' if is_create else 'write_preview',
                    target_kind='full_file',
                    verification_passed=False,
                ),
            )
        if file_existed and old_content == content:
            return ToolResult(
                output='No changes applied (content unchanged).',
                old_content=old_content,
                new_content=content,
                operation='write_noop',
            )
        if (
            file_existed
            and not is_create
            and not overwrite_existing
            and _is_large_existing_code_file(file_path, old_content)
        ):
            return ToolResult(
                output='',
                error=(
                    'LARGE_EXISTING_CODE_FILE_OVERWRITE_BLOCKED: refusing a full-file '
                    f'overwrite of {file_path.name} ({len((old_content or "").splitlines())} lines). '
                    'Use edit_symbols or replace_string for targeted changes, or set '
                    'overwrite_existing=true when a deliberate full rewrite is required.'
                ),
                old_content=old_content,
                new_content=content,
                error_code='LARGE_EXISTING_CODE_FILE_OVERWRITE_BLOCKED',
                retryable=False,
                operation='write_guard',
            )
        return None

    def _handle_write_commit(
        self,
        *,
        file_path: Path,
        content: str,
        old_content: str | None,
        file_existed: bool,
        is_create: bool,
    ) -> ToolResult:
        """Validate, detect stale disk, backup, undo snapshot, atomic write."""
        regression_error = self._detect_introduced_syntax_error(
            file_path, old_content, content
        )
        if regression_error is not None:
            return ToolResult(
                output='',
                error=regression_error,
                old_content=old_content,
                new_content=content,
                error_code='INTRODUCED_SYNTAX_ERROR',
                retryable=True,
                operation='write_validate',
            )

        is_valid, msg = self._maybe_validate_syntax_for_file(file_path, content)
        if not is_valid:
            return ToolResult(
                output='',
                error=f'Syntax validation failed: {msg}',
                old_content=old_content,
                new_content=content,
                error_code='SYNTAX_VALIDATION_FAILED',
                retryable=True,
                operation='write_validate',
            )
        soft_warning = msg if msg and msg.startswith('WARNING:') else ''

        stale = self._detect_stale_disk_on_write(
            file_path=file_path,
            file_existed=file_existed,
            old_content=old_content,
            new_content=content,
        )
        if stale is not None:
            return stale

        if self._transaction_stack:
            self._backup_file(file_path, old_content)

        self._push_undo_snapshot(file_path, old_content)

        written_content = self._write_file(file_path, content)
        verification_error = self._verify_post_write(
            file_path=file_path,
            expected_content=written_content,
            old_content=old_content,
            operation='create_file' if is_create else 'write',
            target_kind='full_file',
        )
        if verification_error is not None:
            return verification_error

        output_msg = _compose_write_success_message(
            is_create=is_create,
            content=content,
            soft_warning=soft_warning,
        )

        # Add context window for overwrites (not new files, which already have preview)
        if not is_create and old_content is not None:
            context_window = _format_context_window(old_content, content)
            if context_window:
                output_msg += '\n\n' + context_window

        return ToolResult(
            output=output_msg,
            old_content=old_content,
            new_content=written_content,
            operation='create_file' if is_create else 'write',
            metadata=self._build_receipt(
                file_path=file_path,
                old_content=old_content,
                new_content=written_content,
                operation='create_file' if is_create else 'write',
                target_kind='full_file',
                verification_passed=True,
            ),
        )

    def _detect_stale_disk_on_write(
        self,
        *,
        file_path: Path,
        file_existed: bool,
        old_content: str | None,
        new_content: str,
    ) -> ToolResult | None:
        if not file_existed or old_content is None:
            return None
        disk_now = self._read_file(file_path)
        if disk_now == old_content:
            return None
        return ToolResult(
            output='',
            error=(
                'FILE_UNEXPECTEDLY_MODIFIED: file changed on disk since it was read. '
                'Re-read the file and retry the write.'
            ),
            old_content=old_content,
            new_content=new_content,
            error_code='FILE_UNEXPECTEDLY_MODIFIED',
            retryable=True,
            operation='write_guard',
        )

    def _handle_write(
        self,
        file_path: Path,
        content: str,
        is_create: bool = False,
        *,
        dry_run: bool = False,
        overwrite_existing: bool = False,
    ) -> ToolResult:
        """Handle write command - write new file content.

        Args:
            file_path: Path to the file to write
            content: Content to write to the file
            is_create: If True, use "created" message instead of "written"
            dry_run: If True, return preview without writing changes
            overwrite_existing: If True, allow guarded full-file overwrites
        """
        try:
            old_content = None
            file_existed = file_path.exists()
            if file_existed:
                old_content = self._read_file(file_path)

            short = self._handle_write_maybe_short_circuit(
                file_path=file_path,
                content=content,
                old_content=old_content,
                file_existed=file_existed,
                is_create=is_create,
                dry_run=dry_run,
                overwrite_existing=overwrite_existing,
            )
            if short is not None:
                return short

            return self._handle_write_commit(
                file_path=file_path,
                content=content,
                old_content=old_content,
                file_existed=file_existed,
                is_create=is_create,
            )

        except Exception as e:
            return ToolResult(
                output='',
                error=f'Error writing file: {e}',
                old_content=None,
                new_content=None,
            )

    def _read_file_with_meta(self, file_path: Path) -> tuple[str, _FileReadMeta]:
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

    def _read_file(self, file_path: Path) -> str:
        """Read file content with encoding + BOM handling; remember I/O metadata."""
        text, meta = self._read_file_with_meta(file_path)
        self._remember_io_meta(file_path, meta)
        return text

    def _write_file(self, file_path: Path, content: str) -> str:
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

    def _insert_at_line(self, content: str, new_text: str, line_num: int) -> str:
        """Insert text at a specific line number (1-indexed)."""
        lines = content.splitlines(keepends=True)
        if not lines:
            lines = ['']

        if content and new_text and not new_text.endswith(('\n', '\r')):
            new_text = f'{new_text}{self._line_ending_for_content(content)}'

        # Normalize line number
        line_idx = max(0, min(line_num - 1, len(lines)))

        # Insert new text
        new_lines = new_text.splitlines(keepends=True)
        if not new_lines:
            new_lines = [new_text]

        # Insert at the specified line
        result_lines = lines[:line_idx] + new_lines + lines[line_idx:]
        return ''.join(result_lines)

    def _replace_range(
        self,
        content: str,
        new_text: str,
        start_line: int,
        end_line: int,
        expected_hash: str | None = None,
    ) -> str | ToolResult:
        """Replace a range of lines with new text."""
        # Check expected_hash (content hash) if provided
        import hashlib

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

        # Handle empty file case
        if not lines:
            if start_line == 1:
                return new_text
            # If requesting to edit range in empty file but not starting at 1, that's ambiguous or error
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

        # Validate end_line > start_line
        if end_line < start_line:
            return ToolResult(
                output='',
                error=f'end_line must be >= start_line (got start={start_line}, end={end_line})',
                new_content=content,
            )

        # 1-based to 0-based conversion
        start_idx = start_line - 1
        # end_line is inclusive, but slice end is exclusive
        end_idx = end_line

        # Validation
        if start_idx >= len(lines):
            return ToolResult(
                output='',
                error=f'Start line {start_line} is beyond file length ({len(lines)} lines)',
                new_content=content,
            )

        # Allow end_line to exceed file length (truncate/replace until end)
        end_idx = min(end_idx, len(lines))

        # Detect original file newline style and normalize new_text to match
        # First normalize all newlines to \n, then convert to target style
        original_newline = '\r\n' if '\r\n' in content else '\n'
        new_text_normalized = new_text.replace('\r\n', '\n').replace('\r', '\n')
        if original_newline == '\r\n':
            new_text_normalized = new_text_normalized.replace('\n', '\r\n')

        # Auto-append trailing newline to prevent line merging bugs.
        # Only skip if replacement deliberately targets the last line (EOF edge case).
        is_eof_replacement = end_idx >= len(lines)
        if (
            not is_eof_replacement
            and new_text_normalized
            and not new_text_normalized.endswith(original_newline)
        ):
            new_text_normalized += original_newline

        new_lines_to_insert = new_text_normalized.splitlines(keepends=True)

        result_lines = lines[:start_idx] + new_lines_to_insert + lines[end_idx:]

        # Detect indentation mismatches and store warnings
        self._last_indent_warnings = _detect_indentation_mismatch(
            lines, new_lines_to_insert, start_idx
        )

        return ''.join(result_lines)
