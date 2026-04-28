"""Production-grade low-level file editor for runtime operations.

Provides robust file editing capabilities with proper error handling,
validation, and atomic operations. Designed for production agent environments.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from backend.execution.utils.file_editor_edit_mixin import FileEditorEditOpsMixin
from backend.execution.utils.file_editor_edit_ops import (
    apply_edit_logic as _apply_edit_logic_impl,
    apply_format_edit as _apply_format_edit_impl,
    apply_section_edit as _apply_section_edit_impl,
    apply_str_replace as _apply_str_replace_impl,
    apply_unified_patch as _apply_unified_patch_impl,
    build_no_match_error as _build_no_match_error_impl,
    closest_match_candidates as _closest_match_candidates_impl,
    find_actual_substring_for_replace as _find_actual_substring_for_replace_impl,
    find_actual_substring_regex as _find_actual_substring_regex_impl,
    flex_quote_pattern as _flex_quote_pattern_impl,
    fuzzy_safe_replace as _fuzzy_safe_replace_impl,
    line_ending_for_content as _line_ending_for_content_impl,
    map_normalized_offset_to_original as _map_normalized_offset_to_original_impl,
    mutate_structured_data as _mutate_structured_data_impl,
    normalize_whitespace_for_match as _normalize_whitespace_for_match_impl,
    parse_structured_content as _parse_structured_content_impl,
    preserve_quote_style_in_new_string as _preserve_quote_style_in_new_string_impl,
    replace_range_guarded as _replace_range_guarded_impl,
    resolve_edit_content as _resolve_edit_content_impl,
    serialize_structured_content as _serialize_structured_content_impl,
    sha256_text as _sha256_text_impl,
    slice_text_by_line_range as _slice_text_by_line_range_impl,
    structured_path_tokens as _structured_path_tokens_impl,
    ws_tolerant_replace as _ws_tolerant_replace_impl,
)

from backend.core.type_safety.path_validation import (
    PathValidationError,
    SafePath,
)
from backend.core.type_safety.sentinels import MISSING, Sentinel, is_missing


@dataclass
class ToolResult:
    """Result of a file editor operation."""

    output: str
    error: str | None = None
    old_content: str | None = None
    new_content: str | None = None


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


class ToolError(Exception):
    """Exception raised by file editor operations."""

    def __init__(self, message: str = '') -> None:
        """Initialize tool error with message."""
        super().__init__(message)
        self.message = message


class FileEditor(FileEditorEditOpsMixin):
    """Production-grade low-level file editor.

    Provides basic file operations (view, edit, write) with proper
    error handling and validation. Used by runtime for file I/O operations.
    """

    _UNDO_MAX_PER_FILE = 32

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
        self._undo_history: dict[str, deque[str | None]] = defaultdict(
            lambda: deque(maxlen=self._UNDO_MAX_PER_FILE)
        )
        # Last read encoding/newline per path (for CRLF/BOM round-trip on write)
        self._file_io_meta: dict[str, _FileReadMeta] = {}
        # Path validator for security
        self._path_validator = None  # Lazy initialization

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

    def _handle_undo_last_edit(self, file_path: Path, display_path: str) -> ToolResult:
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
            if snapshot is None:
                if file_path.exists():
                    file_path.unlink()
                return ToolResult(
                    output='Undid last edit (file removed; it did not exist before that edit).',
                    old_content=None,
                    new_content=None,
                )
            self._write_file(file_path, snapshot)
            return ToolResult(
                output='Undid last edit; restored previous file contents.',
                old_content=snapshot,
                new_content=snapshot,
            )
        except Exception as e:
            hist.append(snapshot)
            if key not in self._undo_history:
                self._undo_history[key] = hist
            return ToolResult(output='', error=f'Failed to undo: {e}')

    def __call__(
        self,
        *,
        command: str,
        path: str,
        file_text: str | Sentinel | None = MISSING,
        view_range: list[int] | None = None,
        old_str: str | Sentinel | None = MISSING,
        new_str: str | Sentinel | None = MISSING,
        insert_line: int | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
        enable_linting: bool = False,
        dry_run: bool = False,
        edit_mode: str | None = None,
        format_kind: str | None = None,
        format_op: str | None = None,
        format_path: str | None = None,
        format_value: Any = None,
        anchor_type: str | None = None,
        anchor_value: str | None = None,
        anchor_occurrence: int | None = None,
        section_action: str | None = None,
        section_content: str | None = None,
        patch_text: str | None = None,
        expected_hash: str | None = None,
        expected_file_hash: str | None = None,
        **_: Any,
    ) -> ToolResult:
        """Execute a file editor command.

        Args:
            command: Command to execute ("read_file", "replace_text" [internal substring replace], "insert_text", "create_file", "undo_last_edit", "edit", "write").
            path: File path (relative to workspace_root or absolute)
            file_text: Optional file content for write/edit operations (use MISSING if not provided)
            view_range: Optional [start_line, end_line] for view command (1-indexed)
            old_str: Optional string to replace (for edit operations, use MISSING if not provided)
            new_str: Optional replacement string (for edit operations, use MISSING if not provided)
            insert_line: Optional line number to insert at (1-indexed)
            start_line: Optional start line number for range edit (1-indexed)
            end_line: Optional end line number for range edit (1-indexed)
            enable_linting: Whether to enable linting (currently not implemented)
            dry_run: If True, compute preview result without writing changes
            edit_mode: Sub-command mode when ``command`` is ``edit`` (e.g. format patch)
            format_kind: Which structured format op applies (e.g. CSS, Prettier)
            format_op: Format operation name (e.g. insert_rule)
            format_path: JSON pointer or path within a structured file
            format_value: New value for the format operation
            anchor_type: Anchor strategy for section edits (e.g. line, regex)
            anchor_value: Anchor string or pattern
            anchor_occurrence: Which match to use when multiple anchors match
            section_action: For section flow: add, remove, or replace
            section_content: Replacement or inserted section text
            patch_text: Full-file or diff patch when using patch-based flows
            expected_hash: Optional client-supplied content hash (legacy)
            expected_file_hash: Optional per-file content hash for compare-and-swap
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

            if command == 'read_file':
                return self._handle_view(file_path, view_range, path)
            if command in (
                'edit',
                'replace_text',
                'insert_text',
            ):
                return self._handle_edit(
                    file_path,
                    file_text,
                    old_str,
                    new_str,
                    insert_line,
                    start_line,
                    end_line,
                    edit_mode=edit_mode,
                    format_kind=format_kind,
                    format_op=format_op,
                    format_path=format_path,
                    format_value=format_value,
                    anchor_type=anchor_type,
                    anchor_value=anchor_value,
                    anchor_occurrence=anchor_occurrence,
                    section_action=section_action,
                    section_content=section_content,
                    patch_text=patch_text,
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

    def _handle_view(
        self, file_path: Path, view_range: list[int] | None, display_path: str
    ) -> ToolResult:
        """Handle view command - read file or specific line range."""
        try:
            content = self._prepare_view_content(file_path)
            if isinstance(content, ToolResult):
                return content

            lines = content.splitlines(keepends=True)
            header = f"Here's the result of running `cat -n` on {display_path}:"

            if view_range and len(view_range) >= 2:
                return self._apply_view_range(content, lines, view_range, header)

            formatted_output = self._format_view_output(lines)
            return ToolResult(
                output=f'{header}\n{formatted_output}',
                old_content=content,
                new_content=content,
            )

        except Exception as e:
            return ToolResult(output='', error=f'Error reading file: {e}')

    def _prepare_view_content(self, file_path: Path) -> str | ToolResult:
        """Prepare content for viewing, handling basic path checks."""
        if not file_path.exists():
            return ToolResult(
                output='',
                error=f'File not found: {file_path}',
                old_content=None,
                new_content=None,
            )

        if file_path.is_dir():
            return self._view_directory(file_path)

        return self._read_file(file_path)

    def _view_directory(self, path: Path, max_depth: int = 2) -> ToolResult:
        """List directory contents."""
        import os

        output = [f'Directory contents of {path}:']
        path_str = str(path)
        base_level = path_str.rstrip(os.sep).count(os.sep)

        for root, dirs, files in os.walk(path_str):
            level = root.count(os.sep) - base_level
            if level >= max_depth:
                del dirs[:]
                continue

            # Skip hidden and __pycache__
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
            files = [f for f in files if not f.startswith('.')]

            indent = '  ' * level
            output.append(f'{indent}{os.path.basename(root)}/')
            subindent = '  ' * (level + 1)
            for f in files:
                output.append(f'{subindent}{f}')

        return ToolResult(
            output='\n'.join(output),
            error=None,
            old_content=None,
            new_content=None,
        )

    def _format_view_output(self, lines: list[str]) -> str:
        """Format lines with line numbers (cat -n style)."""
        numbered_lines = []
        for i, line in enumerate(lines, 1):
            line_content = line.rstrip('\n\r')
            numbered_lines.append(f'{i}\t{line_content}')

        formatted_output = '\n'.join(numbered_lines)
        if lines and any(line.endswith(('\n', '\r')) for line in lines):
            formatted_output += '\n'
        return formatted_output

    def _apply_view_range(
        self, content: str, lines: list[str], view_range: list[int], header: str
    ) -> ToolResult:
        """Apply a line range filter to the view output."""
        start, end = view_range[0], view_range[1]
        start_idx = max(0, start - 1)
        if end < 0:
            end_idx = len(lines)
        else:
            end_idx = min(len(lines), end)

        # Re-format only the selected lines
        selected_lines = []
        for i in range(start_idx, end_idx):
            line_content = lines[i].rstrip('\n\r')
            selected_lines.append(f'{i + 1}\t{line_content}')

        selected_output = '\n'.join(selected_lines)
        if lines and any(
            line.endswith(('\n', '\r')) for line in lines[start_idx:end_idx]
        ):
            selected_output += '\n'

        return ToolResult(
            output=f'{header}\n{selected_output}',
            old_content=content,
            new_content=content,
        )

    def _handle_edit(
        self,
        file_path: Path,
        file_text: str | Sentinel | None,
        old_str: str | Sentinel | None,
        new_str: str | Sentinel | None,
        insert_line: int | None,
        start_line: int | None,
        end_line: int | None,
        *,
        edit_mode: str | None = None,
        format_kind: str | None = None,
        format_op: str | None = None,
        format_path: str | None = None,
        format_value: Any = None,
        anchor_type: str | None = None,
        anchor_value: str | None = None,
        anchor_occurrence: int | None = None,
        section_action: str | None = None,
        section_content: str | None = None,
        patch_text: str | None = None,
        expected_hash: str | None = None,
        expected_file_hash: str | None = None,
        dry_run: bool = False,
    ) -> ToolResult:
        """Handle edit command - modify file content."""
        try:
            # Read existing content
            old_content = self._read_file(file_path) if file_path.exists() else None
            old_content_str = old_content or ''

            if expected_file_hash and file_path.exists():
                digest = self._sha256_text(old_content_str)
                if digest != expected_file_hash:
                    return ToolResult(
                        output='',
                        error=(
                            'File hash guard failed: expected_file_hash does not match '
                            'current file contents (re-read the file and refresh the hash).'
                        ),
                        old_content=old_content,
                        new_content=old_content,
                    )

            # Extract params
            file_text_val, old_str_val, new_str_val = self._extract_edit_params(
                file_text, old_str, new_str
            )

            # Apply edit logic
            new_content = self._apply_edit_logic(
                old_content_str,
                file_text_val,
                old_str_val,
                new_str_val,
                insert_line,
                start_line,
                end_line,
                edit_mode=edit_mode,
                format_kind=format_kind,
                format_op=format_op,
                format_path=format_path,
                format_value=format_value,
                anchor_type=anchor_type,
                anchor_value=anchor_value,
                anchor_occurrence=anchor_occurrence,
                section_action=section_action,
                section_content=section_content,
                patch_text=patch_text,
                expected_hash=expected_hash,
                file_path=file_path,
            )
            if isinstance(new_content, ToolResult):
                new_content.old_content = old_content
                return new_content

            if dry_run:
                return ToolResult(
                    output='Preview generated (no changes applied)',
                    old_content=old_content,
                    new_content=new_content,
                )

            if old_content == new_content:
                return ToolResult(
                    output='No changes applied (content unchanged).',
                    old_content=old_content,
                    new_content=new_content,
                )

            # Write results
            return self._write_edit_result(file_path, old_content, new_content)

        except Exception as e:
            return ToolResult(
                output='',
                error=f'Error editing file: {e}',
                old_content=None,
                new_content=None,
            )

    def _write_edit_result(
        self, file_path: Path, old_content: str | None, new_content: str
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
        is_valid, msg = self._maybe_validate_syntax_for_file(file_path, new_content)
        if not is_valid:
            return ToolResult(
                output='',
                error=f'Syntax validation failed: {msg}',
                old_content=old_content,
                new_content=new_content,
            )

        # Backup original if in transaction
        if self._transaction_stack:
            self._backup_file(file_path, old_content)

        self._push_undo_snapshot(file_path, old_content)

        # Write new content
        self._write_file(file_path, new_content)

        output = 'File updated successfully'
        if msg and msg.startswith('WARNING:'):
            output = f'{output}\n{msg}'
        return ToolResult(
            output=output,
            old_content=old_content,
            new_content=new_content,
        )

    def _handle_write(
        self,
        file_path: Path,
        content: str,
        is_create: bool = False,
        *,
        dry_run: bool = False,
    ) -> ToolResult:
        """Handle write command - write new file content.

        Args:
            file_path: Path to the file to write
            content: Content to write to the file
            is_create: If True, use "created" message instead of "written"
            dry_run: If True, return preview without writing changes
        """
        try:
            old_content = None
            file_existed = file_path.exists()
            if file_existed:
                old_content = self._read_file(file_path)

            if is_create and file_existed:
                # ``create_file`` on an already-existing file always returns
                # silent success WITHOUT overwriting.  Agents should use
                # ``str_replace`` to edit existing files.  Returning
                # old==new lets the stuck-detector recognise repeated
                # no-change create attempts and nudge the model forward.
                return ToolResult(
                    output='File created successfully',
                    old_content=old_content,
                    new_content=old_content,
                )

            if dry_run:
                output_msg = 'Preview generated (no changes applied)'
                return ToolResult(
                    output=output_msg,
                    old_content=old_content,
                    new_content=content,
                )

            if file_existed and old_content == content:
                return ToolResult(
                    output='No changes applied (content unchanged).',
                    old_content=old_content,
                    new_content=content,
                )

            # Validate syntax where possible before writing to avoid introducing
            # syntax errors into the repository.
            is_valid, msg = self._maybe_validate_syntax_for_file(file_path, content)
            if not is_valid:
                return ToolResult(
                    output='',
                    error=f'Syntax validation failed: {msg}',
                    old_content=old_content,
                    new_content=content,
                )
            soft_warning = msg if msg and msg.startswith('WARNING:') else ''

            if file_existed and old_content is not None:
                disk_now = self._read_file(file_path)
                if disk_now != old_content:
                    return ToolResult(
                        output='',
                        error=(
                            'FILE_UNEXPECTEDLY_MODIFIED: file changed on disk since it was read. '
                            'Re-read the file and retry the write.'
                        ),
                        old_content=old_content,
                        new_content=content,
                    )

            # Backup original if in transaction
            if self._transaction_stack:
                self._backup_file(file_path, old_content)

            self._push_undo_snapshot(file_path, old_content)

            self._write_file(file_path, content)

            # Use appropriate message based on command and whether file existed
            if is_create:
                preview_lines = content.splitlines()[:20]
                preview_str = '\n'.join(
                    f'{i + 1}\t{line}' for i, line in enumerate(preview_lines)
                )
                if len(content.splitlines()) > 20:
                    preview_str += '\n...\n(File truncated)'
                le = '\\r\\n' if '\r\n' in content else '\\n'
                output_msg = f'File created successfully. Line endings: {le}. File preview:\n{preview_str}'
            else:
                output_msg = 'File written successfully'

            if soft_warning:
                output_msg = f'{output_msg}\n{soft_warning}'

            return ToolResult(
                output=output_msg,
                old_content=old_content,
                new_content=content,
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

    def _write_file(self, file_path: Path, content: str) -> None:
        """Write file atomically, preserving prior encoding/newline style when known."""
        file_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = file_path.with_suffix(file_path.suffix + '.tmp')
        meta = self._take_io_meta(file_path)
        if meta is None:
            meta = _FileReadMeta(encoding='utf-8', newline='lf', had_bom=False)

        # Last-chance safety net: if any tool path that bypassed the
        # tool-handler-level repair (e.g. a non-standard entry point, or
        # content assembled in-process) still has literal escape residue,
        # scrub it here before the bytes hit disk. No-op on unaffected
        # content / file types.
        try:
            from backend.core.content_escape_repair import repair_literal_escapes
            from backend.core.logger import app_logger as _disk_logger

            report = repair_literal_escapes(content, file_path)
            if report.changed:
                _disk_logger.warning(
                    '[escape_repair:disk] %s: scrubbed %d literal escape sequences '
                    'at write time (upstream repair missed this path)',
                    file_path,
                    report.replacements,
                )
                content = report.content
        except Exception:
            try:
                from backend.core.logger import app_logger as _disk_logger

                _disk_logger.debug(
                    'escape_repair disk safety-net failed', exc_info=True
                )
            except Exception:
                pass

        if meta.newline == 'crlf':
            content = content.replace('\r\n', '\n').replace('\n', '\r\n')

        try:
            if meta.encoding == 'utf-16-le':
                data = b'\xff\xfe' + content.encode('utf-16-le')
            elif meta.encoding == 'utf-16-be':
                data = b'\xfe\xff' + content.encode('utf-16-be')
            elif meta.encoding == 'utf-8-sig' or (
                meta.had_bom and meta.encoding == 'utf-8'
            ):
                data = b'\xef\xbb\xbf' + content.encode('utf-8')
            elif meta.encoding == 'latin-1':
                data = content.encode('latin-1')
            else:
                data = content.encode('utf-8')

            temp_path.write_bytes(data)
            temp_path.replace(file_path)
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

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
        self, content: str, new_text: str, start_line: int, end_line: int
    ) -> str | ToolResult:
        """Replace a range of lines with new text."""
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

        # Prepare replacement
        new_lines_to_insert = new_text.splitlines(keepends=True)
        # If input text doesn't end with newline but we are inserting blocks, usually we want consistency
        # But 'lines' have keepends=True.
        # If new_text is "foo" and we replace a line "bar\n", we get "foo".
        # If there are subsequent lines, they will be attached: "foobaz\n" if next line is "baz\n".
        # This is expected behavior for raw string replacement.

        result_lines = lines[:start_idx] + new_lines_to_insert + lines[end_idx:]
        return ''.join(result_lines)

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

    @contextmanager
    def transaction(self):
        """Context manager for atomic multi-file operations.

        All file operations within this context are atomic - if any operation
        fails, all changes are automatically rolled back.

        Example:
            >>> editor = FileEditor()
            >>> with editor.transaction():
            ...     editor(command="write", path="file1.txt", new_str="content1")
            ...     editor(command="write", path="file2.txt", new_str="content2")
            ...     # If any operation fails, both files are restored
        """
        # Create new backup layer
        backup: dict[str, str | None] = {}
        self._transaction_stack.append(backup)

        try:
            yield self
            # All operations succeeded, commit (just remove backup layer)
            self._transaction_stack.pop()
        except Exception:
            # Rollback all changes in this transaction
            self._rollback_transaction(backup)
            self._transaction_stack.pop()
            raise

    def _rollback_transaction(self, backup: dict[str, str | None]) -> None:
        """Rollback all file changes in a transaction.

        Args:
            backup: Dictionary mapping file paths to their original content
        """
        for file_path_str, original_content in backup.items():
            file_path = Path(file_path_str)
            try:
                if original_content is None:
                    # File was created, delete it
                    if file_path.exists():
                        file_path.unlink()
                else:
                    # Restore original content
                    self._write_file(file_path, original_content)
            except Exception as e:
                # Log but continue rollback for other files
                from backend.core.logger import app_logger as logger

                logger.warning('Failed to rollback %s: %s', file_path, e)
