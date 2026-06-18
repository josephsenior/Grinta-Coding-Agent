"""Undo, backup, rollback, and transaction methods for FileEditor.

Pure code motion: split from ``backend.execution.utils.file_editor`` to
keep that module under the 40 KB file-size cap. No logic changes.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from backend.core.type_safety.path_validation import PathValidationError
from backend.execution.utils.file_editor._file_editor_types import ToolResult


class ToolError(Exception):
    """Exception raised by file editor operations."""

    def __init__(self, message: str = '') -> None:
        """Initialize tool error with message."""
        super().__init__(message)
        self.message = message


class FileEditorRollbackMixin:
    def _handle_undo_last_edit(self, file_path: Path, display_path: str) -> ToolResult:
        try:
            file_path = self._validate_rollback_target(file_path)
        except ToolError as e:
            return ToolResult(output='', error=e.message)

        key = self._undo_key(file_path)
        hist = self._undo_history.get(key)
        if not hist:
            return ToolResult(
                output='',
                error=f'No undo history for {display_path}',
            )
        snapshot = hist.pop()
        if not hist:
            del self._undo_history[key]
        try:
            current_content = self._read_current_content_for_rollback(file_path)
            if snapshot is None:
                self._guard_rollback_disk_unchanged(file_path, current_content)
                self._delete_file_for_rollback(file_path)
                return ToolResult(
                    output='Undid last edit (file removed; it did not exist before that edit).',
                    old_content=current_content,
                    new_content=None,
                )
            warning = self._validate_rollback_restore_content(file_path, snapshot)
            self._guard_rollback_disk_unchanged(file_path, current_content)
            self._write_file(file_path, snapshot)
            output = 'Undid last edit; restored previous file contents.'
            if warning:
                output = f'{output}\n{warning}'
            return ToolResult(
                output=output,
                old_content=current_content,
                new_content=snapshot,
            )
        except Exception as e:
            hist.append(snapshot)
            if key not in self._undo_history:
                self._undo_history[key] = hist
            return ToolResult(output='', error=f'Failed to undo: {e}')

    def _backup_file(self, file_path: Path, content: str | None) -> None:
        """Backup file content for transaction rollback.

        Args:
            file_path: Path to file being modified
            content: Current content (None if file doesn't exist)
        """
        if self._transaction_stack:
            file_str = str(file_path)
            # Only backup once per transaction
            if file_str not in self._transaction_stack[-1]:
                self._transaction_stack[-1][file_str] = content

    def _validate_rollback_target(self, file_path: Path) -> Path:
        """Re-validate a resolved rollback target against the workspace boundary."""
        try:
            workspace = self.workspace_root.resolve()
            resolved = file_path.resolve()
            relative_path = str(resolved.relative_to(workspace))
        except ValueError as e:
            raise ToolError(f'Rollback target outside workspace: {file_path}') from e
        except OSError as e:
            raise ToolError(f'Invalid rollback target {file_path}: {e}') from e

        try:
            return self._resolve_path_safe(relative_path).path
        except PathValidationError as e:
            raise ToolError(f'Rollback path validation error: {e.message}') from e

    def _read_current_content_for_rollback(self, file_path: Path) -> str | None:
        """Read current file content for rollback event payloads."""
        if not file_path.exists() or not file_path.is_file():
            return None
        return self._read_file(file_path)

    def _validate_rollback_restore_content(self, file_path: Path, content: str) -> str:
        """Apply the same syntax validation used by normal write/edit restores."""
        is_valid, msg = self._maybe_validate_syntax_for_file(file_path, content)
        if not is_valid:
            raise ToolError(f'Syntax validation failed: {msg}')
        return msg if msg and msg.startswith('WARNING:') else ''

    def _guard_rollback_disk_unchanged(
        self, file_path: Path, expected_content: str | None
    ) -> None:
        """Avoid rollback clobbering concurrent filesystem changes."""
        if expected_content is None:
            if file_path.exists() and file_path.is_file():
                raise ToolError(
                    'FILE_UNEXPECTEDLY_MODIFIED: file appeared during rollback.'
                )
            return

        if not file_path.exists() or not file_path.is_file():
            raise ToolError('FILE_UNEXPECTEDLY_MODIFIED: file missing during rollback.')
        disk_now = self._read_file(file_path)
        if disk_now != expected_content:
            raise ToolError(
                'FILE_UNEXPECTEDLY_MODIFIED: file changed on disk during rollback.'
            )

    def _delete_file_for_rollback(self, file_path: Path) -> None:
        """Delete a rollback-created file after safety validation."""
        if not file_path.exists():
            self._take_io_meta(file_path)
            return
        if not file_path.is_file():
            raise ToolError(f'Rollback delete refused for non-file path: {file_path}')
        file_path.unlink()
        self._take_io_meta(file_path)

    @contextmanager
    def transaction(self):
        """Context manager for atomic multi-file operations.

        All file operations within this context are atomic - if any operation
        fails, all changes are automatically rolled back.

        Example:
            >>> editor = FileEditor()
            >>> with editor.transaction():
            ...     editor(command="create_file", path="file1.txt", new_str="content1")
            ...     editor(command="create_file", path="file2.txt", new_str="content2")
            ...     # If any operation fails, both files are restored
        """
        # Create new backup layer
        backup: dict[str, str | None] = {}
        self._transaction_stack.append(backup)
        self._last_rollback_results = []

        try:
            yield self
            # All operations succeeded, commit (just remove backup layer)
            self._transaction_stack.pop()
        except Exception:
            # Rollback all changes in this transaction
            self._last_rollback_results = self._rollback_transaction(backup)
            self._transaction_stack.pop()
            raise

    def _rollback_transaction(self, backup: dict[str, str | None]) -> list[ToolResult]:
        """Rollback all file changes in a transaction.

        Args:
            backup: Dictionary mapping file paths to their original content
        """
        results: list[ToolResult] = []
        for file_path_str, original_content in reversed(list(backup.items())):
            file_path = Path(file_path_str)
            try:
                file_path = self._validate_rollback_target(file_path)
                current_content = self._read_current_content_for_rollback(file_path)
                if original_content is None:
                    # File was created, delete it
                    self._guard_rollback_disk_unchanged(file_path, current_content)
                    self._delete_file_for_rollback(file_path)
                    results.append(
                        ToolResult(
                            output='Rolled back file creation; file removed.',
                            old_content=current_content,
                            new_content=None,
                        )
                    )
                else:
                    # Restore original content
                    warning = self._validate_rollback_restore_content(
                        file_path, original_content
                    )
                    self._guard_rollback_disk_unchanged(file_path, current_content)
                    self._write_file(file_path, original_content)
                    output = 'Rolled back file change; restored previous contents.'
                    if warning:
                        output = f'{output}\n{warning}'
                    results.append(
                        ToolResult(
                            output=output,
                            old_content=current_content,
                            new_content=original_content,
                        )
                    )
            except Exception as e:
                # Log but continue rollback for other files
                from backend.core.logger import app_logger as logger

                logger.warning('Failed to rollback %s: %s', file_path, e)
                results.append(
                    ToolResult(
                        output='',
                        error=f'Failed to rollback {file_path}: {e}',
                        old_content=None,
                        new_content=original_content,
                    )
                )
        return results
