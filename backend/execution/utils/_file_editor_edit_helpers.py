"""Edit/write method bodies for FileEditor.

These module functions are the extracted method bodies for the
high-level edit, write, and verification methods on
``_FileEditorOpsMixin``. They are called as one-line forwarders
from the mixin class. Module functions invoke other methods via
``self._method(...)`` so that monkey-patching of the class
methods in tests still works.

Extracted from ``backend.execution.utils._file_editor_ops_mixin`` to
keep that module focused on the ops mixin class.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.execution.utils._file_editor_diff_helpers import (
    _format_context_window,
    _to_changed_line_spans,
)
from backend.execution.utils._file_editor_io_helpers import (
    _compose_write_success_message,
    _is_large_existing_code_file,
)
from backend.execution.utils._file_editor_types import ToolResult


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
            base_error = (
                'replace_string old_string was not found exactly. '
                'Re-read the file and retry the edit with a verified '
                'old_string.'
            )
            if self._was_recently_written(file_path):
                base_error += (
                    " (The file was modified by a previous edit in this "
                    "turn — re-read it before retrying, the model's "
                    'working copy is now stale.)'
                )
            return ToolResult(
                output='',
                error=base_error,
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


def verify_post_write_impl(
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

    if self._transaction_stack:
        self._backup_file(file_path, old_content)

    self._push_undo_snapshot(file_path, old_content)

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

    self._record_recent_write(file_path)

    output = 'File updated successfully'

    if old_content is not None:
        context_window = _format_context_window(old_content, new_content)
        if context_window:
            output += '\n\n' + context_window

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


def handle_write_maybe_short_circuit_impl(
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
    if is_create and file_existed and not overwrite_existing:
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


def handle_write_commit_impl(
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


def handle_write_impl(
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
        self: FileEditor instance (mixin dispatch).
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
