"""Edit/write method bodies for FileEditor.

These module functions are the extracted method bodies for the
high-level edit, write, and verification methods on
``FileEditorOpsMixin``. They are called as one-line forwarders
from the mixin class. Module functions invoke other methods via
``self._method(...)`` so that monkey-patching of the class
methods in tests still works.

Extracted from ``backend.execution.utils.file_editor.file_editor_ops_mixin`` to
keep that module focused on the ops mixin class.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.execution.utils.file_editor._file_editor_diff_helpers import (
    _format_context_window,
    _to_changed_line_spans,
)
from backend.execution.utils.file_editor._file_editor_io_helpers import (
    _compose_write_success_message,
)
from backend.execution.utils.file_editor._file_editor_types import ToolResult


def handle_edit_impl(
    self,
    file_path: Path,
    file_text: str | object | None,
    new_str: str | object | None,
    insert_line: int | None,
    start_line: int | None,
    end_line: int | None,
    *,
    edit_mode: str | None = None,
    expected_hash: str | None = None,
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


def _validate_replace_string_old_string(old_string: str | None) -> ToolResult | None:
    if old_string is None or old_string == '':
        return ToolResult(
            output='',
            error='replace_string old_string must not be empty.',
            error_code='EMPTY_OLD_STRING',
            retryable=True,
            operation='replace_string',
        )
    return None


def _replace_all_with_boundary_check(content: str, old: str, new: str) -> str:
    """Replace all occurrences of *old* with *new* in *content*.

    Unlike ``str.replace``, this function guards against unintended
    substring collisions when ``replace_all`` is requested.  For each
    potential match position it checks that the characters immediately
    before and after the match are *not* identifier-tail / identifier-head
    characters respectively.  This prevents ``snap->data`` from also
    matching inside ``snap->data_size``.

    When the old string is surrounded by non-identifier characters (the
    common case for full-line or token-level replacements), the check
    passes and the replacement proceeds as normal.
    """
    import re as _re

    result_parts: list[str] = []
    last_end = 0
    len(old)

    for idx in _re.finditer(_re.escape(old), content):
        start, end = idx.start(), idx.end()

        # Guard: skip matches that are substrings of an identifier.
        # An "identifier continuation" character is alnum or '_'.
        if start > 0 and (content[start - 1].isalnum() or content[start - 1] == '_'):
            continue
        if end < len(content) and (content[end].isalnum() or content[end] == '_'):
            continue

        result_parts.append(content[last_end:start])
        result_parts.append(new)
        last_end = end

    result_parts.append(content[last_end:])
    return ''.join(result_parts)


def _check_replace_string_preflight(
    self, file_path: Path, new_string: str
) -> ToolResult | None:
    preflight = self._preflight_content_guard(file_path, new_string)
    if preflight is not None:
        return ToolResult(
            output='',
            error=preflight,
            error_code='CONTENT_APPEARS_SERIALIZED'
            if 'CONTENT_APPEARS_SERIALIZED' in preflight
            else 'CONTENT_PREFLIGHT_FAILED',
            retryable=True,
            operation='replace_string',
        )
    return None


def _normalize_replace_strings(
    old_content: str, old_string: str, new_string: str
) -> tuple[str, str]:
    newline = '\r\n' if '\r\n' in old_content else '\n'
    old_match = old_string.replace('\r\n', '\n').replace('\r', '\n')
    new_replacement = new_string.replace('\r\n', '\n').replace('\r', '\n')
    if newline == '\r\n':
        old_match = old_match.replace('\n', '\r\n')
        new_replacement = new_replacement.replace('\n', '\r\n')
    return old_match, new_replacement


def _build_old_string_not_found_result(
    self, file_path: Path, old_content: str
) -> ToolResult:
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


def handle_replace_string_impl(
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
        validation = _validate_replace_string_old_string(old_string)
        if validation is not None:
            return validation

        preflight = _check_replace_string_preflight(self, file_path, new_string)
        if preflight is not None:
            return preflight

        assert old_string is not None

        if not file_path.exists():
            return ToolResult(
                output='',
                error=f'File not found: {file_path}',
                error_code='FILE_NOT_FOUND',
                retryable=True,
                operation='replace_string',
            )

        old_content = self._read_file(file_path)
        old_match, new_replacement = _normalize_replace_strings(
            old_content, old_string, new_string
        )

        match_count = old_content.count(old_match)
        if match_count == 0:
            return _build_old_string_not_found_result(self, file_path, old_content)
        if match_count > 1 and not replace_all:
            return ToolResult(
                output='',
                error='replace_string old_string matched multiple occurrences.',
                old_content=old_content,
                new_content=old_content,
                error_code='OLD_STRING_NOT_UNIQUE',
                retryable=True,
                operation='replace_string',
                metadata={'match_count': match_count},
            )

        if replace_all:
            new_content = _replace_all_with_boundary_check(
                old_content, old_match, new_replacement
            )
        else:
            new_content = old_content.replace(old_match, new_replacement, 1)
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


def build_receipt_impl(
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


def finalize_edit_result_impl(
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


def build_dry_run_result_impl(
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
        output += '\n\n[INDENTATION WARNINGS]\n' + '\n'.join(self._last_indent_warnings)
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


def _validate_edit_before_write(
    self, file_path: Path, old_content: str | None, new_content: str
) -> tuple[ToolResult | None, str]:
    if getattr(self, '_defer_syntax_validation', False):
        return None, ''

    if old_content is not None and file_path.exists():
        disk_now = self._read_file(file_path)
        if disk_now != old_content:
            return ToolResult(
                output='',
                error='File was modified by another process. Re-read and retry.',
                old_content=old_content,
                new_content=new_content,
            ), ''

    regression_error = self._detect_introduced_syntax_error(
        file_path, old_content, new_content
    )
    warnings: list[str] = []
    if regression_error is not None:
        warnings.append(f'WARNING: {regression_error}')

    is_valid, msg = self._maybe_validate_syntax_for_file(file_path, new_content)
    if not is_valid:
        return ToolResult(
            output='',
            error=f'Syntax validation failed: {msg}',
            old_content=old_content,
            new_content=new_content,
            error_code='SYNTAX_VALIDATION_FAILED',
            retryable=True,
            operation='edit',
        ), ''
    if msg and msg.startswith('WARNING:'):
        warnings.append(msg)
    return None, '\n'.join(warnings)


def _format_edit_success_output(
    self,
    old_content: str | None,
    new_content: str,
    written_content: str,
    msg: str,
) -> str:
    output = 'File updated successfully'

    if old_content is not None:
        context_window = _format_context_window(old_content, new_content)
        if context_window:
            output += '\n\n' + context_window

    if self._last_indent_warnings:
        output += '\n\n[INDENTATION WARNINGS]\n' + '\n'.join(self._last_indent_warnings)

    if msg and msg.startswith('WARNING:'):
        output = f'{output}\n{msg}'
    return output


def write_edit_result_impl(
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
    validation_err, msg = _validate_edit_before_write(
        self, file_path, old_content, new_content
    )
    if validation_err is not None:
        return validation_err

    if self._transaction_stack:
        self._backup_file(file_path, old_content)

    self._push_undo_snapshot(file_path, old_content)

    written_content = self._write_file(file_path, new_content)

    output = _format_edit_success_output(
        self, old_content, new_content, written_content, msg
    )
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


def _check_write_dry_run(
    self,
    dry_run: bool,
    file_path: Path,
    content: str,
    old_content: str | None,
) -> ToolResult | None:
    if not dry_run:
        return None
    return ToolResult(
        output='Preview generated (no changes applied)',
        old_content=old_content,
        new_content=content,
        operation='create_file_preview',
        metadata=self._build_receipt(
            file_path=file_path,
            old_content=old_content,
            new_content=content,
            operation='create_file_preview',
            target_kind='full_file',
            verification_passed=False,
        ),
    )


def _check_write_noop(
    file_existed: bool,
    old_content: str | None,
    content: str,
) -> ToolResult | None:
    if file_existed and old_content == content:
        return ToolResult(
            output='No changes applied (content unchanged).',
            old_content=old_content,
            new_content=content,
            operation='create_file_noop',
        )
    return None


def handle_write_maybe_short_circuit_impl(
    self,
    *,
    file_path: Path,
    content: str,
    old_content: str | None,
    file_existed: bool,
    dry_run: bool,
) -> ToolResult | None:
    """Early exits before validation / disk write."""
    result = _check_write_dry_run(self, dry_run, file_path, content, old_content)
    if result is not None:
        return result

    return _check_write_noop(file_existed, old_content, content)


def _validate_write_commit(
    self, file_path: Path, old_content: str | None, content: str
) -> tuple[ToolResult | None, str]:
    regression_error = self._detect_introduced_syntax_error(
        file_path, old_content, content
    )
    warnings: list[str] = []
    if regression_error is not None:
        warnings.append(f'WARNING: {regression_error}')

    is_valid, msg = self._maybe_validate_syntax_for_file(file_path, content)
    if not is_valid:
        return ToolResult(
            output='',
            error=f'Syntax validation failed: {msg}',
            old_content=old_content,
            new_content=content,
            error_code='SYNTAX_VALIDATION_FAILED',
            retryable=True,
            operation='create_file',
        ), ''
    if msg and msg.startswith('WARNING:'):
        warnings.append(msg)
    return None, '\n'.join(warnings)


def _compose_write_commit_output(
    self,
    content: str,
    soft_warning: str,
) -> str:
    output_msg = _compose_write_success_message(
        content=content, soft_warning=soft_warning
    )
    return output_msg


def handle_write_commit_impl(
    self,
    *,
    file_path: Path,
    content: str,
    old_content: str | None,
    file_existed: bool,
) -> ToolResult:
    """Validate, detect stale disk, backup, undo snapshot, atomic write."""
    validation_err, soft_warning = _validate_write_commit(
        self, file_path, old_content, content
    )
    if validation_err is not None:
        return validation_err

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

    output_msg = _compose_write_commit_output(self, content, soft_warning)

    return ToolResult(
        output=output_msg,
        old_content=old_content,
        new_content=written_content,
        operation='create_file',
        metadata=self._build_receipt(
            file_path=file_path,
            old_content=old_content,
            new_content=written_content,
            operation='create_file',
            target_kind='full_file',
            verification_passed=True,
        ),
    )


def detect_stale_disk_on_write_impl(
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
        error='File was modified by another process. Re-read and retry.',
        old_content=old_content,
        new_content=new_content,
        error_code='FILE_UNEXPECTEDLY_MODIFIED',
        retryable=True,
        operation='write_guard',
    )


def handle_write_impl(
    self,
    file_path: Path,
    content: str,
    *,
    dry_run: bool = False,
) -> ToolResult:
    """Handle create_file command - write new or overwritten file content."""
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
            dry_run=dry_run,
        )
        if short is not None:
            return short

        return self._handle_write_commit(
            file_path=file_path,
            content=content,
            old_content=old_content,
            file_existed=file_existed,
        )

    except Exception as e:
        return ToolResult(
            output='',
            error=f'Error writing file: {e}',
            old_content=None,
            new_content=None,
        )
