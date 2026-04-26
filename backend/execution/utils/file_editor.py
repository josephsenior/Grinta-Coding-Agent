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
        import re

        # Strategy:
        # 1. Convert tabs to 4 spaces
        # 2. Convert all non-newline whitespace sequences to a single space
        # 3. Strip leading/trailing whitespace on every line
        # 4. Collapse multiple blank lines into one
        lines = text.splitlines()
        normalized_lines = []
        for line in lines:
            line = line.replace('\t', '    ')
            # 2. Convert all non-newline whitespace sequences to a single space
            line = re.sub(r'[ \t]+', ' ', line).strip()
            # 3. Strip leading/trailing whitespace on every line
            # 4. Collapse multiple blank lines into one
            normalized_lines.append(line)

        # Join with \n and strip overall to ignore leading/trailing empty lines in match
        result = '\n'.join(normalized_lines)
        return re.sub(r'\n+', '\n', result).strip()

    def _ws_tolerant_replace(
        self,
        file_content: str,
        old_str: str,
        new_str: str,
    ) -> str | ToolResult:
        """Try whitespace-normalized matching for substring replace (internal opcode)."""
        norm_content = self._normalize_whitespace_for_match(file_content)
        norm_old = self._normalize_whitespace_for_match(old_str)

        count = norm_content.count(norm_old)
        if count == 0:
            return ToolResult(
                output='',
                error=self._build_no_match_error(
                    file_content, old_str, mode='normalize_ws'
                ),
                new_content=file_content,
            )
        if count > 1:
            return ToolResult(
                output='',
                error=self._build_no_match_error(
                    file_content, old_str, mode='normalize_ws'
                ),
                new_content=file_content,
            )

        # sliding window
        lines_orig = file_content.splitlines(keepends=True)
        lines_norm = [
            self._normalize_whitespace_for_match(line_text) for line_text in lines_orig
        ]
        norm_old_lines = norm_old.splitlines()
        if not norm_old_lines:
            return ToolResult(
                output='',
                error='old_str contains only whitespace.',
                new_content=file_content,
            )

        first_line_matches = [
            i for i, nl in enumerate(lines_norm) if nl == norm_old_lines[0]
        ]

        valid_match = None
        for s in first_line_matches:
            found = True
            curr = s
            for target in norm_old_lines:
                while curr < len(lines_norm) and not lines_norm[curr] and target:
                    curr += 1
                if curr >= len(lines_norm) or lines_norm[curr] != target:
                    found = False
                    break
                curr += 1
            if found:
                if valid_match:
                    return ToolResult(
                        output='',
                        error=self._build_no_match_error(
                            file_content, old_str, mode='normalize_ws'
                        ),
                        new_content=file_content,
                    )
                valid_match = (s, curr)

        if valid_match:
            s, e = valid_match
            return ''.join(lines_orig[:s]) + new_str + ''.join(lines_orig[e:])

        return ToolResult(
            output='',
            error=self._build_no_match_error(
                file_content, old_str, mode='normalize_ws'
            ),
            new_content=file_content,
        )

    @staticmethod
    def _map_normalized_offset_to_original(original: str, norm_offset: int) -> int:
        return -1

    @staticmethod
    def _line_ending_for_content(content: str) -> str:
        if '\r\n' in content:
            return '\r\n'
        return '\n'

    # Languages where a Tree-sitter ERROR node is almost always a real
    # syntax error (not a parser limitation). These were historically
    # blocked pre-write; we now always downgrade to a warning and let the
    # model see the diagnostic in the next turn (matching OpenCode +
    # Claude Code behavior). Opt back in to the old veto by setting
    # ``GRINTA_STRICT_WRITE_VALIDATION=1``.
    _STRICT_VALIDATION_LANGUAGES: frozenset[str] = frozenset(
        {'html', 'css', 'scss', 'json', 'yaml', 'xml', 'svg', 'toml'}
    )

    @staticmethod
    def _strict_write_validation_enabled() -> bool:
        """Return True iff the legacy pre-write veto should block on ERROR."""
        raw = os.environ.get('GRINTA_STRICT_WRITE_VALIDATION', '').strip().lower()
        return raw in {'1', 'true', 'yes', 'on'}

    def _maybe_validate_syntax_for_file(
        self, file_path: Path, content: str
    ) -> tuple[bool, str]:
        """Attempt syntax validation using Tree-sitter for the file's language.

        Returns ``(is_valid, message)``. ``is_valid=False`` blocks the write.

        By default **we never block** — even for ``_STRICT_VALIDATION_LANGUAGES``
        we return ``True`` with a ``WARNING:`` prefix so the write proceeds
        and the model sees the diagnostic in the tool observation. This
        matches OpenCode's ``write.ts`` (which writes first, then appends LSP
        errors to the output) and Claude Code's ``FileWriteTool`` (which
        notifies LSP asynchronously after the write). Blocking traps weaker
        models in an unrecoverable loop of rewriting the same malformed file.

        Setting ``GRINTA_STRICT_WRITE_VALIDATION=1`` restores the old
        pre-write veto for HTML/CSS/JSON/... if you really want it.
        """
        try:
            # Lazy import to avoid hard dependency when tree-sitter isn't installed
            from backend.utils.treesitter_editor import TreeSitterEditor

        except Exception as exc:  # pragma: no cover - environment dependent
            return True, f'Tree-sitter unavailable: {exc}'

        try:
            editor = TreeSitterEditor()
        except Exception as exc:  # pragma: no cover - runtime import issues
            return True, f'Tree-sitter initialization failed: {exc}'

        language = editor.detect_language(str(file_path))
        if not language:
            return True, 'No parser mapping for file extension; skipping validation'

        is_valid, msg = editor.validate_syntax(content, str(file_path), language)
        if is_valid:
            return True, msg

        # Append a diagnostic hint if the failure looks like double-escape
        # residue — the single most common cause of bogus syntax errors
        # when writing from LLM output.
        enriched_msg = self._enrich_syntax_error_with_escape_hint(
            msg, content, file_path
        )

        # Attach a content excerpt around the reported error lines so the
        # model can fix the file from the observation alone, without
        # re-reading. Mirrors the rich diagnostics that LSP-backed agents
        # (OpenCode, Claude Code) surface to callers.
        enriched_msg = self._attach_content_context(enriched_msg, content)

        if (
            language in self._STRICT_VALIDATION_LANGUAGES
            and self._strict_write_validation_enabled()
        ):
            return False, enriched_msg

        # Default path: surface the diagnostic as a warning, let the write
        # proceed. The model will fix the file on the next turn using the
        # warning text as context.
        return True, f'WARNING: {enriched_msg}'

    @staticmethod
    def _attach_content_context(msg: str, content: str, *, radius: int = 2) -> str:
        """Append up to ``radius`` lines of content around any line number in ``msg``.

        Tree-sitter errors look like ``Line 17: unexpected token`` — we parse
        those line numbers out, then render a short excerpt. Does nothing if
        no line numbers are present or content is trivially short.
        """
        if not msg or not content:
            return msg
        lines = content.splitlines()
        if len(lines) < 3:
            return msg
        try:
            import re as _re

            nums = {
                int(m.group(1)) for m in _re.finditer(r'(?i)\bline\s+(\d{1,6})\b', msg)
            }
        except Exception:
            return msg
        if not nums:
            return msg

        excerpts: list[str] = []
        for n in sorted(nums)[:5]:
            start = max(1, n - radius)
            end = min(len(lines), n + radius)
            width = len(str(end))
            block = [f'  [line {n} — excerpt]']
            for i in range(start, end + 1):
                marker = '>>' if i == n else '  '
                block.append(f'  {marker} {i:>{width}} | {lines[i - 1]}')
            excerpts.append('\n'.join(block))
        if not excerpts:
            return msg
        return msg + '\n\nContent context:\n' + '\n\n'.join(excerpts)

    @staticmethod
    def _enrich_syntax_error_with_escape_hint(
        msg: str, content: str, file_path: Path
    ) -> str:
        """Append a hint to the syntax-error message when escape residue is detected."""
        try:
            from backend.core.content_escape_repair import (
                has_literal_escape_residue,
            )

            if has_literal_escape_residue(content, file_path):
                return (
                    msg + '\n\n[HINT] The content contains literal backslash-escape '
                    'sequences (e.g. \\n, \\") that appear to be double-escaped. '
                    'In your next tool call, use a single backslash for newlines '
                    '(a real newline character, not the characters "\\" + "n") '
                    'and unescaped double quotes inside strings.'
                )
        except Exception:
            pass
        return msg

    def _closest_match_candidates(
        self,
        file_content: str,
        old_str: str,
        *,
        limit: int = 3,
    ) -> list[tuple[float, int, str]]:
        target = self._normalize_whitespace_for_match(old_str).strip()
        if not target:
            return []

        # If old_str is multi-line, we look for matches of the first line to give context
        if '\n' in old_str or '\r' in old_str:
            target = self._normalize_whitespace_for_match(
                old_str.splitlines()[0]
            ).strip()

        candidates: list[tuple[float, int, str]] = []
        for idx, line in enumerate(file_content.splitlines(), 1):
            normalized = self._normalize_whitespace_for_match(line).strip()
            if not normalized:
                continue
            ratio = difflib.SequenceMatcher(None, target, normalized).ratio()
            if ratio < 0.4:
                continue
            snippet = line.strip()
            if len(snippet) > 120:
                snippet = f'{snippet[:117]}...'
            candidates.append((ratio, idx, snippet))

        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[:limit]

    def _build_no_match_error(self, file_content: str, old_str: str, mode: str) -> str:
        base = {
            'exact': 'No exact match found for old_str.',
            'normalize_ws': 'No match found even with whitespace normalization.',
            'fuzzy_safe': 'No match found for fuzzy_safe mode.',
        }.get(mode, 'No match found for old_str.')

        closest = self._closest_match_candidates(file_content, old_str)
        if not closest:
            return base

        lines = [base, 'Closest candidates:']
        for ratio, line_no, snippet in closest:
            lines.append(f'- line {line_no} (score {ratio:.2f}): {snippet}')
        return '\n'.join(lines)

    def _fuzzy_safe_replace(
        self,
        file_content: str,
        old_str: str,
        new_str: str,
    ) -> str | ToolResult:
        # Keep fuzzy matching intentionally narrow to avoid broad accidental edits.
        if not old_str.strip():
            return ToolResult(
                output='',
                error='fuzzy_safe mode requires a non-empty old_str.',
                new_content=file_content,
            )
        if '\n' in old_str or '\r' in old_str:
            return ToolResult(
                output='',
                error='fuzzy_safe mode supports only single-line old_str. Use normalize_ws for multi-line edits.',
                new_content=file_content,
            )
        if len(old_str) > 120:
            return ToolResult(
                output='',
                error='fuzzy_safe mode only supports old_str up to 120 characters.',
                new_content=file_content,
            )

        target = self._normalize_whitespace_for_match(old_str).strip()
        lines = file_content.splitlines(keepends=True)
        scored: list[tuple[float, int, str]] = []
        for idx, raw_line in enumerate(lines):
            normalized_line = self._normalize_whitespace_for_match(raw_line).strip()
            if not normalized_line:
                continue
            ratio = difflib.SequenceMatcher(None, target, normalized_line).ratio()
            if ratio >= 0.9:
                scored.append((ratio, idx, raw_line))

        if not scored:
            return ToolResult(
                output='',
                error=self._build_no_match_error(
                    file_content, old_str, mode='fuzzy_safe'
                ),
                new_content=file_content,
            )

        scored.sort(key=lambda item: item[0], reverse=True)
        best_ratio, best_idx, best_line = scored[0]

        if len(scored) > 1 and abs(best_ratio - scored[1][0]) < 0.01:
            return ToolResult(
                output='',
                error='fuzzy_safe found ambiguous matches with similar confidence. Narrow old_str and retry.',
                new_content=file_content,
            )

        line_ending = ''
        if best_line.endswith('\r\n'):
            line_ending = '\r\n'
        elif best_line.endswith('\n'):
            line_ending = '\n'

        replacement = new_str
        if line_ending and not new_str.endswith(('\n', '\r')):
            replacement = f'{new_str}{line_ending}'

        updated = list(lines)
        updated[best_idx] = replacement
        return ''.join(updated)

    @staticmethod
    def _flex_quote_pattern(needle: str) -> str:
        """Build a regex that treats straight and typographic quotes as equivalent."""
        parts: list[str] = []
        for ch in needle:
            if ch == '"':
                parts.append('(?:["\u201c\u201d])')
            elif ch == "'":
                parts.append("(?:['\u2018\u2019])")
            else:
                parts.append(re.escape(ch))
        return ''.join(parts)

    def _find_actual_substring_regex(self, haystack: str, needle: str) -> str | None:
        """Fallback: regex when normalizeQuotes + index slice cannot match."""
        try:
            rx = re.compile(self._flex_quote_pattern(needle), re.DOTALL)
        except re.error:
            return None
        matches = list(rx.finditer(haystack))
        if len(matches) == 1:
            return matches[0].group(0)
        return None

    def _find_actual_substring_for_replace(
        self, haystack: str, needle: str
    ) -> str | None:
        """Resolve model straight quotes to on-disk substring (Claude: normalizeQuotes + index slice).

        First exact match, then search in quote-normalized space; slice original by same indices
        (1:1 quote mapping preserves string length). Fall back to regex if needed.
        """
        if needle in haystack:
            return needle

        norm_needle = normalize_quotes(needle)
        norm_hay = normalize_quotes(haystack)
        if norm_needle and norm_needle in norm_hay:
            n = norm_hay.count(norm_needle)
            if n != 1:
                return None
            idx = norm_hay.index(norm_needle)
            if idx + len(needle) > len(haystack):
                return self._find_actual_substring_regex(haystack, needle)
            actual = haystack[idx : idx + len(needle)]
            if normalize_quotes(actual) != norm_needle:
                return self._find_actual_substring_regex(haystack, needle)
            return actual

        return self._find_actual_substring_regex(haystack, needle)

    @staticmethod
    def _preserve_quote_style_in_new_string(actual_old: str, new_str: str) -> str:
        """Align straight quotes in new_str with quote characters used in actual_old."""
        doubles = [c for c in actual_old if c in '"\u201c\u201d']
        singles = [c for c in actual_old if c in "'\u2018\u2019"]
        di = 0
        si = 0
        out: list[str] = []
        for ch in new_str:
            if ch == '"':
                repl = doubles[di % len(doubles)] if doubles else '"'
                di += 1
                out.append(repl)
            elif ch == "'":
                repl = singles[si % len(singles)] if singles else "'"
                si += 1
                out.append(repl)
            else:
                out.append(ch)
        return ''.join(out)

    def _apply_str_replace(
        self,
        old_content: str,
        old_str: str,
        new_str: str,
        file_path: Path | None = None,
    ) -> str | ToolResult:
        """Apply old_str -> new_str replace with relaxed tolerant whitespace fallback, but validate tree-sitter syntax."""
        exact_count = old_content.count(old_str)

        if exact_count == 1:
            new_content = old_content.replace(old_str, new_str, 1)
        elif exact_count > 1:
            return ToolResult(
                output='',
                error=f'ERROR: old_str matches {exact_count} times. Must be unique.',
                new_content=old_content,
            )
        else:
            actual = self._find_actual_substring_for_replace(old_content, old_str)
            if actual is not None:
                if old_content.count(actual) != 1:
                    return ToolResult(
                        output='',
                        error='ERROR: quote-normalized old_str is not unique.',
                        new_content=old_content,
                    )
                adjusted_new = self._preserve_quote_style_in_new_string(actual, new_str)
                new_content = old_content.replace(actual, adjusted_new, 1)
                return new_content

            tolerant = self._ws_tolerant_replace(old_content, old_str, new_str)
            if isinstance(tolerant, ToolResult):
                if '\n' not in old_str and '\r' not in old_str:
                    fuzzy_result = self._fuzzy_safe_replace(
                        old_content, old_str, new_str
                    )
                    if not isinstance(fuzzy_result, ToolResult):
                        new_content = fuzzy_result
                    else:
                        tolerant.error = tolerant.error + '\n\n' + fuzzy_result.error
                        return tolerant
                else:
                    return tolerant
            else:
                new_content = tolerant

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
        file_path: Path | None = None,
    ) -> str | ToolResult:
        """Determine new content based on provided parameters."""
        resolved_mode = (edit_mode or '').strip().lower() or None
        if resolved_mode == 'format':
            return self._apply_format_edit(
                old_content_str,
                file_path=file_path,
                format_kind=format_kind,
                format_op=format_op,
                format_path=format_path,
                format_value=format_value,
            )
        if resolved_mode == 'section':
            return self._apply_section_edit(
                old_content_str,
                anchor_type=anchor_type,
                anchor_value=anchor_value,
                anchor_occurrence=anchor_occurrence,
                section_action=section_action,
                section_content=section_content,
            )
        if resolved_mode == 'range':
            if start_line is None or end_line is None:
                return ToolResult(
                    output='',
                    error='edit_mode=range requires start_line and end_line.',
                    new_content=old_content_str,
                )
            return self._replace_range_guarded(
                old_content_str,
                self._resolve_edit_content(file_text_val, new_str_val),
                start_line,
                end_line,
                expected_hash=expected_hash,
            )
        if resolved_mode == 'patch':
            return self._apply_unified_patch(old_content_str, patch_text)
        if resolved_mode == 'replace':
            if old_str_val and new_str_val:
                return self._apply_str_replace(
                    old_content_str,
                    old_str_val,
                    new_str_val,
                    file_path=file_path,
                )
            return ToolResult(
                output='',
                error='edit_mode=replace requires old_str and new_str.',
                new_content=old_content_str,
            )

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

    @staticmethod
    def _slice_text_by_line_range(content: str, start_line: int, end_line: int) -> str:
        lines = content.splitlines(keepends=True)
        if not lines or start_line < 1:
            return ''
        start_idx = start_line - 1
        end_idx = min(len(lines), end_line)
        if start_idx >= len(lines):
            return ''
        return ''.join(lines[start_idx:end_idx])

    @staticmethod
    def _sha256_text(text: str) -> str:
        return hashlib.sha256(text.encode('utf-8')).hexdigest()

    def _replace_range_guarded(
        self,
        content: str,
        new_text: str,
        start_line: int,
        end_line: int,
        *,
        expected_hash: str | None = None,
    ) -> str | ToolResult:
        if expected_hash:
            current_slice = self._slice_text_by_line_range(
                content, start_line, end_line
            )
            if self._sha256_text(current_slice) != expected_hash:
                return ToolResult(
                    output='',
                    error='Range guard failed: expected_hash does not match target slice.',
                    new_content=content,
                )
        return self._replace_range(content, new_text, start_line, end_line)

    def _apply_format_edit(
        self,
        content: str,
        *,
        file_path: Path | None,
        format_kind: str | None,
        format_op: str | None,
        format_path: str | None,
        format_value: Any,
    ) -> str | ToolResult:
        kind = (
            format_kind or (file_path.suffix.lstrip('.') if file_path else '')
        ).lower()
        kind_map = {'yml': 'yaml'}
        kind = kind_map.get(kind, kind)
        op = (format_op or 'set').lower()
        if kind not in {'json', 'yaml', 'toml'}:
            return ToolResult(
                output='',
                error=f'Unsupported format kind for parser-based edit: {kind!r}',
                new_content=content,
            )
        if not format_path:
            return ToolResult(
                output='',
                error='edit_mode=format requires format_path.',
                new_content=content,
            )
        try:
            data = self._parse_structured_content(content, kind)
            updated = self._mutate_structured_data(data, op, format_path, format_value)
            return self._serialize_structured_content(updated, kind)
        except Exception as exc:
            return ToolResult(
                output='',
                error=f'Format edit failed: {exc}',
                new_content=content,
            )

    def _parse_structured_content(self, content: str, kind: str) -> Any:
        if kind == 'json':
            return json.loads(content or '{}')
        if kind == 'yaml':
            import yaml

            return yaml.safe_load(content) or {}
        # toml
        try:
            import tomllib

            return tomllib.loads(content or '')
        except Exception:
            import toml

            return toml.loads(content or '')

    def _serialize_structured_content(self, data: Any, kind: str) -> str:
        if kind == 'json':
            return f'{json.dumps(data, indent=2, ensure_ascii=True)}\n'
        if kind == 'yaml':
            import yaml

            return yaml.safe_dump(data, sort_keys=False)
        # toml
        try:
            import toml

            return toml.dumps(data)
        except Exception as exc:
            raise ValueError(f'TOML serialization unavailable: {exc}') from exc

    @staticmethod
    def _structured_path_tokens(path_expr: str) -> list[str]:
        cleaned = path_expr.strip()
        if cleaned.startswith('$.'):
            cleaned = cleaned[2:]
        elif cleaned.startswith('$'):
            cleaned = cleaned[1:]
        return [p for p in cleaned.split('.') if p]

    def _mutate_structured_data(
        self, data: Any, op: str, path_expr: str, value: Any
    ) -> Any:
        if not isinstance(data, dict):
            raise ValueError('Structured root must be an object/map')
        tokens = self._structured_path_tokens(path_expr)
        if not tokens:
            raise ValueError('format_path must point to a key')
        node = data
        for token in tokens[:-1]:
            if token not in node or not isinstance(node[token], dict):
                if op == 'set':
                    node[token] = {}
                else:
                    raise ValueError(f'Path segment {token!r} not found')
            node = node[token]
        leaf = tokens[-1]
        if op == 'set':
            node[leaf] = value
        elif op == 'delete':
            node.pop(leaf, None)
        elif op == 'append':
            target = node.get(leaf)
            if target is None:
                node[leaf] = [value]
            elif isinstance(target, list):
                target.append(value)
            else:
                raise ValueError('append target is not a list')
        else:
            raise ValueError(f'Unsupported format_op: {op!r}')
        return data

    def _apply_section_edit(
        self,
        content: str,
        *,
        anchor_type: str | None,
        anchor_value: str | None,
        anchor_occurrence: int | None,
        section_action: str | None,
        section_content: str | None,
    ) -> str | ToolResult:
        if not anchor_value:
            return ToolResult(
                output='',
                error='edit_mode=section requires anchor_value.',
                new_content=content,
            )
        kind = (anchor_type or 'markdown_heading').lower()
        occ = anchor_occurrence or 1
        action = (section_action or 'replace').lower()
        lines = content.splitlines(keepends=True)
        if kind == 'markdown_heading':
            heading_re = re.compile(r'^(#{1,6})\s+(.*)$')
            heading_matches: list[tuple[int, int]] = []
            for idx, line in enumerate(lines):
                m = heading_re.match(line.strip('\r\n'))
                if m and m.group(2).strip() == anchor_value.strip():
                    heading_matches.append((idx, len(m.group(1))))
            if len(heading_matches) < occ or occ < 1:
                return ToolResult(
                    output='', error='Section anchor not found.', new_content=content
                )
            start_idx, level = heading_matches[occ - 1]
            end_idx = len(lines)
            for j in range(start_idx + 1, len(lines)):
                m = heading_re.match(lines[j].strip('\r\n'))
                if m and len(m.group(1)) <= level:
                    end_idx = j
                    break
        else:
            pattern = anchor_value if kind == 'regex' else re.escape(anchor_value)
            pattern_matches = list(re.finditer(pattern, content, re.MULTILINE))
            if len(pattern_matches) < occ or occ < 1:
                return ToolResult(
                    output='', error='Section anchor not found.', new_content=content
                )
            target = pattern_matches[occ - 1]
            start_idx = content[: target.start()].count('\n')
            end_idx = len(lines)

        replacement = section_content or ''
        repl_lines = replacement.splitlines(keepends=True)
        if action == 'replace':
            result_lines = lines[:start_idx] + repl_lines + lines[end_idx:]
        elif action == 'insert_before':
            result_lines = lines[:start_idx] + repl_lines + lines[start_idx:]
        elif action == 'insert_after':
            result_lines = lines[:end_idx] + repl_lines + lines[end_idx:]
        elif action == 'delete':
            result_lines = lines[:start_idx] + lines[end_idx:]
        else:
            return ToolResult(
                output='',
                error=f'Unsupported section_action: {action!r}',
                new_content=content,
            )
        return ''.join(result_lines)

    def _apply_unified_patch(
        self, content: str, patch_text: str | None
    ) -> str | ToolResult:
        if not patch_text:
            return ToolResult(
                output='',
                error='edit_mode=patch requires patch_text.',
                new_content=content,
            )
        hunks: list[tuple[str, str]] = []
        old_lines: list[str] = []
        new_lines: list[str] = []
        in_hunk = False
        for raw_line in patch_text.splitlines():
            if raw_line.startswith('@@'):
                if in_hunk:
                    hunks.append((''.join(old_lines), ''.join(new_lines)))
                old_lines, new_lines = [], []
                in_hunk = True
                continue
            if not in_hunk:
                continue
            if raw_line.startswith(' '):
                text = raw_line[1:] + '\n'
                old_lines.append(text)
                new_lines.append(text)
            elif raw_line.startswith('-'):
                old_lines.append(raw_line[1:] + '\n')
            elif raw_line.startswith('+'):
                new_lines.append(raw_line[1:] + '\n')
        if in_hunk:
            hunks.append((''.join(old_lines), ''.join(new_lines)))

        updated = content
        for old_chunk, new_chunk in hunks:
            if not old_chunk:
                updated = f'{updated}{new_chunk}'
                continue
            count = updated.count(old_chunk)
            if count != 1:
                return ToolResult(
                    output='',
                    error='Patch hunk context did not match uniquely.',
                    new_content=content,
                )
            updated = updated.replace(old_chunk, new_chunk, 1)
        return updated

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
