"""Production-grade low-level file editor for runtime operations.

Provides robust file editing capabilities with proper error handling,
validation, and atomic operations. Designed for production agent environments.

Split into sibling mixin modules in 2026-06 to keep this file under the 40 KB cap:
  - backend.execution.utils._file_editor_view_mixin      (read-only view)
  - backend.execution.utils._file_editor_ops_mixin       (edit/write/read-write)
  - backend.execution.utils._file_editor_rollback_mixin  (undo/backup/rollback/transaction)
Pure code motion: no logic changes. The flat re-export shim at the bottom
preserves back-compat with callers using ``from backend.execution.utils.file_editor
import ...``.
"""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from backend.core.type_safety.path_validation import (
    PathValidationError,
    SafePath,
)
from backend.core.type_safety.sentinels import MISSING, Sentinel, is_missing
from backend.execution.utils._file_editor_ops_mixin import (
    _FileEditorOpsMixin,
    _FileReadMeta,
)
from backend.execution.utils._file_editor_types import ToolResult
from backend.execution.utils._file_editor_rollback_mixin import (
    ToolError,
    _FileEditorRollbackMixin,
)
from backend.execution.utils._file_editor_view_mixin import _FileEditorViewMixin
from backend.execution.utils.file_editor_edit_mixin import FileEditorEditOpsMixin


_GLOBAL_UNDO_HISTORY: dict[str, deque[str | None]] = defaultdict(
    lambda: deque(maxlen=32)
)
_GLOBAL_FILE_LOCKS: dict[str, threading.RLock] = {}
_GLOBAL_FILE_LOCKS_GUARD = threading.Lock()
def _canonical_lock_key(file_path: Path) -> str:
    try:
        return str(file_path.resolve())
    except OSError:
        return str(file_path)
def _file_lock_for_path(file_path: Path) -> threading.RLock:
    key = _canonical_lock_key(file_path)
    with _GLOBAL_FILE_LOCKS_GUARD:
        lock = _GLOBAL_FILE_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _GLOBAL_FILE_LOCKS[key] = lock
        return lock



class FileEditor(
    FileEditorEditOpsMixin,
    _FileEditorViewMixin,
    _FileEditorOpsMixin,
    _FileEditorRollbackMixin,
):
    """Production-grade low-level file editor.

    Provides basic file operations (view, edit, write) with proper
    error handling and validation. Used by runtime for file I/O operations.
    """

    def __init__(self, workspace_root: str | None = None) -> None:
        """Initialize the file editor.

        Args:
            workspace_root: Root directory for file operations (defaults to current directory)
        """
        self.workspace_root = Path(workspace_root) if workspace_root else Path.cwd()
        # Transaction support: stack of backup dictionaries
        # Each backup dict maps file_path -> original_content (None if file didn't exist)
        self._transaction_stack: list[dict[str, str | None]] = []
        # Per-file undo: before each mutating write we append the previous snapshot
        # (None means the file did not exist). Bounded FIFO via deque maxlen.
        self._undo_history = _GLOBAL_UNDO_HISTORY
        # Last read encoding/newline per path (for CRLF/BOM round-trip on write)
        self._file_io_meta: dict[str, _FileReadMeta] = {}
        # Path validator for security
        self._path_validator = None  # Lazy initialization
        # Last indentation warnings from range edit
        self._last_indent_warnings: list[str] = []
        # Last transaction rollback results, shaped like normal editor results
        # so callers/tests can inspect the emitted before/after payloads.
        self._last_rollback_results: list[ToolResult] = []

    def _io_meta_key(self, file_path: Path) -> str:
        return self._undo_key(file_path)

    def _remember_io_meta(self, file_path: Path, meta: _FileReadMeta) -> None:
        self._file_io_meta[self._io_meta_key(file_path)] = meta

    def _take_io_meta(self, file_path: Path) -> _FileReadMeta | None:
        return self._file_io_meta.pop(self._io_meta_key(file_path), None)

    def _undo_key(self, file_path: Path) -> str:
        try:
            return str(file_path.resolve())
        except OSError:
            return str(file_path)

    def _push_undo_snapshot(self, file_path: Path, snapshot: str | None) -> None:
        """Record file state *before* a mutating write (None = file absent)."""
        self._undo_history[self._undo_key(file_path)].append(snapshot)

    def __call__(
        self,
        *,
        command: str,
        path: str,
        file_text: str | Sentinel | None = MISSING,
        view_range: list[int] | None = None,
        new_str: str | Sentinel | None = MISSING,
        old_string: str | None = None,
        replace_all: bool = False,
        insert_line: int | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
        enable_linting: bool = False,
        dry_run: bool = False,
        edit_mode: str | None = None,
        expected_hash: str | None = None,
        expected_file_hash: str | None = None,
        overwrite_existing: bool = False,
        **_: Any,
    ) -> ToolResult:
        """Execute a file editor command.

        Args:
            command: Command to execute ("read_file", "replace_string", "insert_text", "create_file", "undo_last_edit", "edit", "write").
            path: File path (relative to workspace_root or absolute)
            file_text: Optional file content for write/edit operations (use MISSING if not provided)
            view_range: Optional [start_line, end_line] for view command (1-indexed)
            new_str: Optional replacement string (for edit operations, use MISSING if not provided)
            old_string: Exact string to replace for replace_string.
            replace_all: Replace every exact old_string occurrence when true.
            insert_line: Optional line number to insert at (1-indexed)
            start_line: Optional start line number for range edit (1-indexed)
            end_line: Optional end line number for range edit (1-indexed)
            enable_linting: Whether to enable linting (currently not implemented)
            dry_run: If True, compute preview result without writing changes
            edit_mode: Sub-command mode when ``command`` is ``edit`` (range only)
            expected_hash: Optional client-supplied content hash (legacy)
            expected_file_hash: Optional per-file content hash for compare-and-swap
            overwrite_existing: Allow deliberate full-file rewrite guards to be bypassed
            **_: Additional keyword arguments (ignored)

        Returns:
            ToolResult with operation result

        Raises:
            ToolError: If operation fails
        """
        # Store command for use in handlers
        self._current_command = command
        try:
            # Validate and resolve file path with security checks
            safe_path = self._resolve_path_safe(path)
            file_path = safe_path.path

            with _file_lock_for_path(file_path):
                return self._dispatch_locked(
                    command=command,
                    path=path,
                    file_path=file_path,
                    file_text=file_text,
                    view_range=view_range,
                    new_str=new_str,
                    old_string=old_string,
                    replace_all=replace_all,
                    insert_line=insert_line,
                    start_line=start_line,
                    end_line=end_line,
                    dry_run=dry_run,
                    edit_mode=edit_mode,
                    expected_hash=expected_hash,
                    expected_file_hash=expected_file_hash,
                    overwrite_existing=overwrite_existing,
                )

        except PathValidationError as e:
            return ToolResult(output='', error=f'Path validation error: {e.message}')
        except Exception as e:
            return ToolResult(output='', error=str(e))

    def _dispatch_locked(
        self,
        *,
        command: str,
        path: str,
        file_path: Path,
        file_text: str | Sentinel | None,
        view_range: list[int] | None,
        new_str: str | Sentinel | None,
        old_string: str | None,
        replace_all: bool,
        insert_line: int | None,
        start_line: int | None,
        end_line: int | None,
        dry_run: bool,
        edit_mode: str | None,
        expected_hash: str | None,
        expected_file_hash: str | None,
        overwrite_existing: bool,
    ) -> ToolResult:
        """Dispatch a validated editor command while the target file lock is held."""
        try:
            if command == 'read_file':
                return self._handle_view(file_path, view_range, path)
            if command == 'replace_string':
                return self._handle_replace_string(
                    file_path,
                    old_string,
                    self._extract_content(MISSING, new_str),
                    replace_all=replace_all,
                    dry_run=dry_run,
                )
            if command in (
                'edit',
                'insert_text',
            ):
                return self._handle_edit(
                    file_path,
                    file_text,
                    new_str,
                    insert_line,
                    start_line,
                    end_line,
                    edit_mode=edit_mode,
                    expected_hash=expected_hash,
                    expected_file_hash=expected_file_hash,
                    dry_run=dry_run,
                )
            if command == 'undo_last_edit':
                return self._handle_undo_last_edit(file_path, path)
            if command in ('write', 'create_file'):
                # Handle sentinels for write/create_file command
                content = self._extract_content(file_text, new_str)
                return self._handle_write(
                    file_path,
                    content,
                    is_create=(command == 'create_file'),
                    dry_run=dry_run,
                    overwrite_existing=overwrite_existing,
                )

            raise ToolError(f'Unknown command: {command}')

        except PathValidationError as e:
            return ToolResult(output='', error=f'Path validation error: {e.message}')
        except Exception as e:
            return ToolResult(output='', error=str(e))

    def _resolve_path_safe(self, path: str) -> SafePath:
        """Resolve and validate file path with security checks.

        Args:
            path: File path to resolve

        Returns:
            SafePath instance with validated path

        Raises:
            PathValidationError: If path validation fails
        """
        return SafePath.validate(
            path,
            workspace_root=str(self.workspace_root),
            must_be_relative=True,
        )

    def _extract_content(
        self, file_text: str | Sentinel | None, new_str: str | Sentinel | None
    ) -> str:
        """Extract content from sentinel-aware parameters.

        Args:
            file_text: File text parameter (may be MISSING, None, or str)
            new_str: New string parameter (may be MISSING, None, or str)

        Returns:
            Extracted content string (empty string if both are MISSING/None)
        """
        # Check file_text first
        if not is_missing(file_text) and file_text is not None:
            return str(
                file_text
            )  # Type narrowing: if not MISSING and not None, it's str
        # Check new_str
        if not is_missing(new_str) and new_str is not None:
            return str(new_str)  # Type narrowing: if not MISSING and not None, it's str
        # Both are MISSING or None
        return ''



# ---------------------------------------------------------------------------
# Flat re-export shim for back-compat
# ---------------------------------------------------------------------------
# Helpers and methods previously defined in this module have been moved to:
#   - backend.execution.utils._file_editor_view_mixin      (view)
#   - backend.execution.utils._file_editor_ops_mixin       (edit/write)
#   - backend.execution.utils._file_editor_rollback_mixin  (undo/rollback/transaction/indent)
# Kept as flat re-exports for in-repo callers.
from backend.execution.utils._file_editor_ops_mixin import (  # noqa: E402, F401
    _FileEditorOpsMixin,
    _FileReadMeta,
    _LARGE_EXISTING_CODE_FILE_LINES,
    _CODE_FILE_SUFFIXES,
    _QUOTE_TRANSLATE,
    _compose_create_file_success_message,
    _compose_write_success_message,
    _encode_disk_payload,
    _find_changed_ranges,
    _format_context_window,
    _format_range_lines,
    _is_large_existing_code_file,
    _merge_ranges_with_context,
    _normalize_newlines_for_metadata,
    _to_changed_line_spans,
    normalize_quotes,
)
from backend.execution.utils._file_editor_rollback_mixin import (  # noqa: E402, F401
    _FileEditorRollbackMixin,
    ToolError,
)
from backend.execution.utils._file_editor_view_mixin import (  # noqa: E402, F401
    _FileEditorViewMixin,
    _check_block_indent_after_colon,
    _check_first_line_indent,
    _detect_indentation_mismatch,
    _get_line_indent,
)
