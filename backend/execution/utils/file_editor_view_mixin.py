"""Read-only view methods for FileEditor.

Pure code motion: split from ``backend.execution.utils.file_editor`` to
keep that module under the 40 KB file-size cap. No logic changes.
"""

from __future__ import annotations

import os
from pathlib import Path

from backend.execution.utils._file_editor_types import ToolResult


def _detect_indentation_mismatch(
    original_lines: list[str],
    new_lines: list[str],
    start_idx: int,
) -> list[str]:
    """Detect indentation mismatches and generate structured warnings.

    Returns a list of warning messages describing:
    1. The mismatch (expected vs actual indentation)
    2. The resulting broken line
    3. A suggested fix
    """
    warnings: list[str] = []

    if not original_lines or not new_lines or start_idx >= len(original_lines):
        return warnings

    original_indent = _get_line_indent(original_lines[start_idx])
    if original_indent is None:
        return warnings

    _check_first_line_indent(warnings, new_lines, original_indent, start_idx)
    _check_block_indent_after_colon(warnings, new_lines, start_idx)

    return warnings


def _get_line_indent(line: str) -> int | None:
    """Get indentation level of a line, or None if line is empty/whitespace."""
    stripped = line.strip()
    if not stripped:
        return None
    return len(line) - len(line.lstrip())


def _check_first_line_indent(
    warnings: list[str],
    new_lines: list[str],
    original_indent: int,
    start_idx: int,
) -> None:
    """Check if first new line's indentation matches the original."""
    if not new_lines:
        return

    new_indent = _get_line_indent(new_lines[0])
    if new_indent is None or new_indent == original_indent:
        return

    line_num = start_idx + 1
    stripped_content = new_lines[0].strip()

    warnings.append(
        f'[INDENTATION MISMATCH] Line {line_num}: '
        f'First line has {new_indent} spaces, but target block indent starts at {original_indent} spaces.'
    )
    warnings.append(
        f'[BROKEN LINE] Line {line_num} would be: "{new_lines[0].rstrip()}"'
    )
    warnings.append(
        f'[SUGGESTED FIX] Did you mean to indent with {original_indent} spaces? '
        f'Try: "{" " * original_indent}{stripped_content}"'
    )


def _check_block_indent_after_colon(
    warnings: list[str],
    new_lines: list[str],
    start_idx: int,
) -> None:
    """Check for missing indentation after lines ending with ':'."""
    for i in range(1, len(new_lines)):
        line = new_lines[i]
        if not line.strip() or line.strip().startswith('#'):
            continue

        prev_line = new_lines[i - 1]
        if not prev_line.rstrip().endswith(':'):
            continue

        if _get_line_indent(line) != 0:
            continue

        line_num = start_idx + 1 + i
        suggested_indent = 4

        warnings.append(
            f'[INDENTATION ERROR] Line {line_num}: '
            f'Expected indentation after ":" on line {line_num - 1}, but found 0 spaces.'
        )
        warnings.append(f'[BROKEN LINE] Line {line_num} would be: "{line.rstrip()}"')
        warnings.append(
            f'[SUGGESTED FIX] Did you mean to indent with {suggested_indent} spaces? '
            f'Try: "{" " * suggested_indent}{line.strip()}"'
        )


class FileEditorViewMixin:
    def _handle_view(self, file_path: Path, view_range: list[int] | None) -> ToolResult:
        """Handle view command - read file or specific line range."""
        try:
            content = self._prepare_view_content(file_path)
            if isinstance(content, ToolResult):
                return content

            lines = content.splitlines(keepends=True)

            if view_range and len(view_range) >= 2:
                return self._apply_view_range(content, lines, view_range)

            formatted_output = self._format_view_output(lines)
            return ToolResult(
                output=formatted_output,
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
        self, content: str, lines: list[str], view_range: list[int]
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
            output=selected_output,
            old_content=content,
            new_content=content,
        )
