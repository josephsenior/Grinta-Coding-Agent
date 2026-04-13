"""Production-grade low-level file editor for runtime operations.

Provides robust file editing capabilities with proper error handling,
validation, and atomic operations. Designed for production agent environments.
"""

from __future__ import annotations

from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


class ToolError(Exception):
    """Exception raised by file editor operations."""

    def __init__(self, message: str = '') -> None:
        """Initialize tool error with message."""
        super().__init__(message)
        self.message = message


class FileEditor:
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
        # Path validator for security
        self._path_validator = None  # Lazy initialization

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
        normalize_ws: bool | None = None,
        enable_linting: bool = False,
        dry_run: bool = False,
        **_: Any,
    ) -> ToolResult:
        """Execute a file editor command.

        Args:
            command: Command to execute ("view_file", "replace_text", "insert_text", "create_file", "undo_last_edit", "view_and_replace", "edit", "write").
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

            if command == 'view_file':
                return self._handle_view(file_path, view_range, path)
            if command in (
                'edit',
                'replace_text',
                'insert_text',
                'view_and_replace',
            ):
                return self._handle_edit(
                    file_path,
                    file_text,
                    old_str,
                    new_str,
                    insert_line,
                    start_line,
                    end_line,
                    normalize_ws,
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
        output = [f"Directory contents of {path}:"]
        path_str = str(path)
        base_level = path_str.rstrip(os.sep).count(os.sep)

        for root, dirs, files in os.walk(path_str):
            level = root.count(os.sep) - base_level
            if level >= max_depth:
                del dirs[:]
                continue

            # Skip hidden and __pycache__
            dirs[:] = [
                d for d in dirs if not d.startswith('.') and d != '__pycache__'
            ]
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
        normalize_ws: bool | None,
        *,
        dry_run: bool = False,
    ) -> ToolResult:
        """Handle edit command - modify file content."""
        try:
            # Read existing content
            old_content = self._read_file(file_path) if file_path.exists() else None
            old_content_str = old_content or ''

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
                normalize_ws,
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

    def _extract_edit_params(
        self,
        file_text: str | Sentinel | None,
        old_str: str | Sentinel | None,
        new_str: str | Sentinel | None,
    ) -> tuple[str | None, str | None, str | None]:
        """Extract actual values from sentinel-aware edit parameters."""
        file_text_val = (
            str(file_text)
            if not is_missing(file_text) and file_text is not None
            else None
        )
        old_str_val = (
            str(old_str) if not is_missing(old_str) and old_str is not None else None
        )
        new_str_val = (
            str(new_str) if not is_missing(new_str) and new_str is not None else None
        )
        return file_text_val, old_str_val, new_str_val

    @staticmethod
    def _normalize_whitespace_for_match(text: str) -> str:
        """Normalize whitespace for tolerant matching while preserving line structure."""
        from backend.engine.tools.whitespace_handler import WhitespaceHandler

        return WhitespaceHandler.normalize_for_match(text)

    @staticmethod
    def _map_normalized_offset_to_original(original: str, norm_offset: int) -> int:
        """Map normalized-text offset back to original-text offset."""
        from backend.engine.tools.whitespace_handler import WhitespaceHandler

        return WhitespaceHandler.map_normalized_offset_to_original(
            original,
            norm_offset,
        )

    def _ws_tolerant_replace(
        self,
        file_content: str,
        old_str: str,
        new_str: str,
    ) -> str | ToolResult:
        """Try whitespace-normalized matching for replace_text."""
        norm_content = self._normalize_whitespace_for_match(file_content)
        norm_old = self._normalize_whitespace_for_match(old_str)

        count = norm_content.count(norm_old)
        if count == 0:
            return ToolResult(
                output='',
                error='No match found even with whitespace normalization.',
                new_content=file_content,
            )

        norm_start = norm_content.index(norm_old)
        norm_end = norm_start + len(norm_old)

        orig_start = self._map_normalized_offset_to_original(file_content, norm_start)
        orig_end = self._map_normalized_offset_to_original(file_content, norm_end)
        return file_content[:orig_start] + new_str + file_content[orig_end:]

    def _fuzzy_unique_replace(
        self,
        file_content: str,
        old_str: str,
        new_str: str,
    ) -> str | ToolResult:
        """Try high-confidence fuzzy block replacement when exact matching misses.

        Safety guards:
        - only for non-trivial multi-line blocks
        - require very high similarity
        - require a clearly unique best candidate
        """
        import difflib

        # Avoid risky fuzzy edits for tiny snippets.
        old_lines = old_str.splitlines(keepends=True)
        if len(old_lines) < 2 or len(old_str.strip()) < 40:
            return self._fuzzy_match_error(file_content, old_str)

        lines = file_content.splitlines(keepends=True)
        window = len(old_lines)
        if len(lines) < window:
            return self._fuzzy_match_error(file_content, old_str)

        best_ratio = 0.0
        second_ratio = 0.0
        best_block = ''
        best_line_matches = 0

        old_plain_lines = old_str.splitlines()
        old_norm_lines = [
            self._normalize_whitespace_for_match(line).strip()
            for line in old_plain_lines
        ]

        for i in range(len(lines) - window + 1):
            candidate = ''.join(lines[i : i + window])
            ratio = difflib.SequenceMatcher(None, old_str, candidate).ratio()
            cand_plain_lines = candidate.splitlines()
            cand_norm_lines = [
                self._normalize_whitespace_for_match(line).strip()
                for line in cand_plain_lines
            ]
            line_matches = sum(
                1
                for old_line, cand_line in zip(
                    old_norm_lines,
                    cand_norm_lines,
                    strict=False,
                )
                if old_line and old_line == cand_line
            )
            if ratio > best_ratio:
                second_ratio = best_ratio
                best_ratio = ratio
                best_block = candidate
                best_line_matches = line_matches
            elif ratio > second_ratio:
                second_ratio = ratio

        if best_ratio < 0.80:
            return self._fuzzy_match_error(file_content, old_str)

        return file_content.replace(best_block, new_str, 1)

    def _apply_str_replace(
        self,
        old_content: str,
        old_str: str,
        new_str: str,
        file_path: Path | None = None,
        *,
        normalize_ws: bool | None = None,
    ) -> str | ToolResult:
        """Apply old_str -> new_str replace with relaxed tolerant whitespace fallback, but validate tree-sitter syntax."""
        exact_count = old_content.count(old_str)
        
        if exact_count == 1:
            new_content = old_content.replace(old_str, new_str, 1)
        elif exact_count > 1:
            return ToolResult(
                output='',
                error=f"ERROR: old_str matches {exact_count} times. Must be unique.",
                new_content=old_content,
            )
        else:
            # Fall back to relaxed whitespace-tolerant match
            tolerant = self._ws_tolerant_replace(old_content, old_str, new_str)
            if isinstance(tolerant, ToolResult):
                # No match found at all
                return tolerant
            new_content = tolerant

        # Validate syntax after replacement
        if file_path:
            from backend.orchestration.middleware.auto_check import _treesitter_syntax_check
            result = _treesitter_syntax_check(str(file_path), new_content.encode('utf-8'))
            if result is not None:
                is_valid, err_msg = result
                if not is_valid:
                    return ToolResult(
                        output='',
                        error=f"ERROR: The edit introduces a Syntax Error:\n{err_msg}\nEdit rejected.",
                        new_content=old_content,
                    )

        return new_content

    def _resolve_edit_content(
        self,
        file_text_val: str | None,
        new_str_val: str | None,
    ) -> str:
        """Resolve content from file_text or new_str. Empty string if neither."""
        return new_str_val or file_text_val or ''

    def _apply_edit_logic(
        self,
        old_content_str: str,
        file_text_val: str | None,
        old_str_val: str | None,
        new_str_val: str | None,
        insert_line: int | None,
        start_line: int | None,
        end_line: int | None,
        normalize_ws: bool | None,
        file_path: Path | None = None,
    ) -> str | ToolResult:
        """Determine new content based on provided parameters."""
        if start_line is not None and end_line is not None:
            return self._replace_range(
                old_content_str,
                self._resolve_edit_content(file_text_val, new_str_val),
                start_line,
                end_line,
            )
        if insert_line is not None:
            return self._insert_at_line(
                old_content_str,
                self._resolve_edit_content(file_text_val, new_str_val),
                insert_line,
            )
        if old_str_val and new_str_val:
            return self._apply_str_replace(
                old_content_str,
                old_str_val,
                new_str_val,
                file_path=file_path,
                normalize_ws=normalize_ws,
            )
        if file_text_val:
            return file_text_val
        if new_str_val:
            return old_content_str + new_str_val
        return ToolResult(
            output='',
            error='No content provided for edit operation',
            new_content=old_content_str,
        )

    def _fuzzy_match_error(self, content: str, old_str: str) -> ToolResult:
        """Return an error with the closest matching block from the file."""
        import difflib

        lines = content.splitlines(keepends=True)
        old_lines = old_str.splitlines(keepends=True)
        window = len(old_lines)

        best_ratio = 0.0
        best_block = ''

        for i in range(max(1, len(lines) - window + 1)):
            candidate = ''.join(lines[i : i + window])
            ratio = difflib.SequenceMatcher(None, old_str, candidate).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_block = candidate

        if best_ratio > 0.6:
            return ToolResult(
                output='',
                error=(
                    f'ERROR: No exact match for old_str was found in the file. '
                    f'Did you mean this block (similarity {best_ratio:.0%})?\n\n'
                    f'<<<\n{best_block.rstrip()}\n>>>\n\n'
                    f'Please provide the exact text to replace, '
                    f'including whitespace and indentation.'
                ),
                new_content=content,
            )

        return ToolResult(
            output='',
            error=(
                'ERROR: No match for old_str was found in the file. '
                "The content you're trying to replace does not exist. "
                'Use the view command to see the current file content, '
                'then retry with the exact text.'
            ),
            new_content=content,
        )

    def _write_edit_result(
        self, file_path: Path, old_content: str | None, new_content: str
    ) -> ToolResult:
        """Write the result of an edit operation to disk."""
        # Backup original if in transaction
        if self._transaction_stack:
            self._backup_file(file_path, old_content)

        self._push_undo_snapshot(file_path, old_content)

        # Write new content
        self._write_file(file_path, new_content)

        return ToolResult(
            output='File updated successfully',
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
                # File already exists — return silent success with old==new
                # so stuck detection can recognize the re-creation.
                # Telling the LLM about the duplicate confuses weak models.
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

            # Backup original if in transaction
            if self._transaction_stack:
                self._backup_file(file_path, old_content)

            self._push_undo_snapshot(file_path, old_content)

            self._write_file(file_path, content)

            # Use appropriate message based on command and whether file existed
            if is_create:
                output_msg = 'File created successfully'
            else:
                output_msg = 'File written successfully'

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

    def _read_file(self, file_path: Path) -> str:
        """Read file content with proper encoding handling."""
        try:
            with open(file_path, encoding='utf-8') as f:
                return f.read()
        except UnicodeDecodeError:
            # Fallback to latin-1 for binary-like files
            with open(file_path, encoding='latin-1', errors='replace') as f:
                return f.read()

    def _write_file(self, file_path: Path, content: str) -> None:
        """Write file content, creating directories if needed."""
        # Ensure directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write file atomically (write to temp then rename)
        temp_path = file_path.with_suffix(file_path.suffix + '.tmp')
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                f.write(content)
            temp_path.replace(file_path)
        except Exception:
            # Clean up temp file on error
            if temp_path.exists():
                temp_path.unlink()
            raise

    def _insert_at_line(self, content: str, new_text: str, line_num: int) -> str:
        """Insert text at a specific line number (1-indexed)."""
        lines = content.splitlines(keepends=True)
        if not lines:
            lines = ['']

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
