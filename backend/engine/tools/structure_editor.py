"""Ultimate editor providing a unified interface for structure-aware editing.

High-level interface that intelligently routes operations to the best editor backend.
Provides simple, powerful API for all code editing operations.
"""

from __future__ import annotations

import difflib
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.core.file_history import global_undo_manager
from backend.core.logger import app_logger as logger
from backend.engine.tools.atomic_refactor import (
    AtomicRefactor,
    RefactorResult,
    RefactorTransaction,
)
from backend.engine.tools.smart_errors import SmartErrorHandler
from backend.engine.tools.whitespace_handler import WhitespaceHandler
from backend.utils.treesitter.treesitter_editor import (
    EditResult,
    SymbolLocation,
    TreeSitterEditor,
)


def _find_changed_ranges(
    old_lines: list[str],
    new_lines: list[str],
) -> list[tuple[int, int]]:
    """Find ranges of changed lines in the new content."""
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
    """Generate a context window showing the edited region with line numbers."""
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


def _sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


@dataclass
class EditorConfig:
    """Configuration for the ultimate editor."""

    auto_indent: bool = True
    validate_syntax: bool = True
    clean_whitespace: bool = True
    backup_enabled: bool = True
    dry_run_first: bool = False


class StructureEditor:
    """The Ultimate File Editor - Structure-aware, language-agnostic, safe.

    Features:
    - Universal Tree-sitter parsing (40+ languages)
    - Symbol-based editing (edit by function/class name, not line numbers)
    - Intelligent whitespace handling (never breaks on tabs vs. spaces)
    - Atomic multi-file refactoring with rollback
    - Syntax validation before saving
    - Smart error messages with suggestions
    - Multi-file atomic operations

    Usage Examples:

    ```python
    editor = StructureEditor()

    # Edit a function by name (no line numbers!)
    result = editor.edit_function(
        "myfile.py",
        "process_data",
        new_body="    return data.strip().lower()"
    )

    # Multi-file refactoring (atomic - all succeed or all fail)
    with editor.begin_refactoring() as refactor:
        refactor.edit_file("file1.py", new_content="...")
        refactor.edit_file("file2.py", new_content="...")
        # Commits automatically, or rolls back on error

    # Standard file operations
    editor.create_file("new_file.py", "print('hello')")
    editor.read_file("new_file.py")
    editor.insert_code("new_file.py", 1, "import os")
    ```
    """

    def __init__(self, config: EditorConfig | None = None):
        """Initialize the ultimate editor.

        Args:
            config: Editor configuration

        """
        self.config = config or EditorConfig()

        # Initialize backends
        self.universal = TreeSitterEditor()
        self.whitespace = WhitespaceHandler()
        self.refactor = AtomicRefactor()
        self.errors = SmartErrorHandler()

        logger.info('🚀 Ultimate Editor initialized')
        logger.info(
            '   - Tree-sitter: %s languages',
            len(self.universal.get_supported_languages()),
        )
        logger.info('   - Auto-indent: %s', self.config.auto_indent)
        logger.info('   - Validation: %s', self.config.validate_syntax)

    # ========================================================================
    # HIGH-LEVEL OPERATIONS
    # ========================================================================

    def _write_text_atomically(self, path: str, content: str) -> None:
        temp_path = f'{path}.tmp'
        with open(temp_path, 'w', encoding='utf-8', newline='') as f:
            f.write(content)
        os.replace(temp_path, path)

    def _verify_disk_content(
        self, path: str, expected_content: str, *, operation: str
    ) -> tuple[bool, str]:
        try:
            with open(path, encoding='utf-8') as f:
                actual = f.read()
        except Exception as e:
            return (
                False,
                f'Edit verification failed after {operation}: could not re-read file: {e}',
            )
        if actual == expected_content:
            return True, ''
        return (
            False,
            'Edit verification failed after '
            f'{operation}: on-disk content hash {_sha256_text(actual)} '
            f'did not match intended hash {_sha256_text(expected_content)}.',
        )

    def create_file(self, path: str, content: str) -> EditResult:
        """Create a new file.

        Args:
            path: Path to the file
            content: File content

        Returns:
            EditResult
        """
        if os.path.exists(path):
            return EditResult(
                success=False,
                message=f'File already exists: {path}. Use edit_symbol or replace_string to modify it.',
            )

        try:
            # Create parent directories if needed
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

            self._write_text_atomically(path, content)
            verified, verify_msg = self._verify_disk_content(
                path, content, operation='create_file'
            )
            if not verified:
                return EditResult(success=False, message=verify_msg)

            return EditResult(
                success=True,
                message=f'Created file {path}',
                modified_code=content,
                lines_changed=content.count('\n') + 1,
            )
        except Exception as e:
            return EditResult(success=False, message=f'Failed to create file: {e}')

    def read_file(self, path: str, line_range: list[int] | None = None) -> EditResult:
        """View file content or directory listing.

        Args:
            path: Path to view
            line_range: Optional [start, end] lines (1-indexed)

        Returns:
            EditResult with content in message
        """
        if not os.path.exists(path):
            return EditResult(success=False, message=f'Path not found: {path}')

        if os.path.isdir(path):
            return self._view_directory(path)

        try:
            with open(path, encoding='utf-8') as f:
                lines = f.readlines()

            start_line, end_line = self._determine_view_range(line_range, len(lines))

            if start_line > end_line:
                return EditResult(
                    success=False,
                    message=f'Invalid line range: {start_line}-{end_line}',
                )

            # Format with line numbers (cat -n style)
            content_view = self._format_view_output(lines, start_line, end_line)

            return EditResult(
                success=True,
                message=f'Showing lines {start_line}-{end_line} of {path}:\n{content_view}',
                original_code=''.join(lines),
            )

        except Exception as e:
            return EditResult(success=False, message=f'Error reading file: {e}')

    def insert_code(self, path: str, insert_line: int, new_code: str) -> EditResult:
        """Insert code after a specific line.

        Args:
            path: Path to file
            insert_line: Line number to insert after (0 for beginning of file)
            new_code: Code to insert

        Returns:
            EditResult
        """
        return self.replace_code_range(
            path,
            start_line=insert_line + 1,
            end_line=insert_line,
            new_code=new_code,
        )

    def undo_last_edit(self, path: str) -> EditResult:
        """Undo the last edit to a file.

        Args:
            path: Path to file

        Returns:
            EditResult
        """
        if not global_undo_manager.has_history(path):
            return EditResult(success=False, message=f'No undo history for {path}')

        previous_content = global_undo_manager.pop(path)

        try:
            if previous_content is None:
                if os.path.exists(path):
                    os.remove(path)
                return EditResult(
                    success=True,
                    message=f'Undid last edit to {path} (file removed)',
                )
            with open(path, 'w', encoding='utf-8') as f:
                f.write(previous_content)

            return EditResult(
                success=True,
                message=f'Undid last edit to {path}',
                modified_code=previous_content,
            )
        except Exception as e:
            return EditResult(success=False, message=f'Failed to undo: {e}')

    def _view_directory(self, path: str, max_depth: int = 2) -> EditResult:
        """List directory contents."""
        output: list[str] = []
        base_level = path.rstrip(os.sep).count(os.sep)

        for root, dirs, files in os.walk(path):
            level = root.count(os.sep) - base_level
            if level >= max_depth:
                del dirs[:]
                continue

            # Skip hidden
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            files = [f for f in files if not f.startswith('.')]

            indent = '  ' * level
            output.append(f'{indent}{os.path.basename(root)}/')
            subindent = '  ' * (level + 1)
            for f in files:
                output.append(f'{subindent}{f}')

        return EditResult(success=True, message='\n'.join(output))

    def edit_function(
        self,
        path: str,
        function_name: str,
        new_body: str,
        line_number: int | None = None,
    ) -> EditResult:
        """Edit a function by name (works for ANY language).

        Args:
            path: Path to the file
            function_name: Name of the function to edit
            new_body: New function body
            line_number: Optional line number to disambiguate when multiple matches exist

        Returns:
            EditResult with success status

        """
        logger.info("Editing function '%s' in %s", function_name, path)

        # Detect language
        language = self.universal.detect_language(path)
        if not language:
            ext = Path(path).suffix.lower() or '(no extension)'
            supported = ', '.join(
                sorted(
                    {
                        '.py',
                        '.js',
                        '.ts',
                        '.go',
                        '.rs',
                        '.java',
                        '.c',
                        '.cpp',
                        '.rb',
                        '.php',
                        '.swift',
                        '.kt',
                        '.cs',
                        '.html',
                        '.css',
                        '.json',
                        '.yaml',
                        '.sh',
                    }
                )
            )
            return EditResult(
                success=False,
                message=f'Unsupported file type: {ext}',
            )

        # Read old content before edit for context window
        old_content = None
        try:
            with open(path, encoding='utf-8') as f:
                old_content = f.read()
        except Exception:
            pass

        # Skip auto-indent: the tree-sitter _replace_node_content already
        # handles indentation via preserve_indentation=True, so adding
        # auto-indent here would double-indent the result.

        # Perform edit
        result = self.universal.edit_function(
            path,
            function_name,
            new_body,
            validate=self.config.validate_syntax,
            line_number=line_number,
        )

        # Add context window on success
        if result.success and old_content is not None:
            try:
                with open(path, encoding='utf-8') as f:
                    new_content = f.read()
                if new_content == old_content:
                    return EditResult(
                        success=False,
                        message='Edit verification failed after symbol edit: file content did not change on disk.',
                    )
                if self.find_symbol(path, function_name) is None:
                    return EditResult(
                        success=False,
                        message=(
                            'Edit verification failed after symbol edit: '
                            f"symbol '{function_name}' could not be resolved after the write."
                        ),
                    )
                context_window = _format_context_window(old_content, new_content)
                if context_window:
                    result.message += '\n\n' + context_window
            except Exception:
                pass

        # Clean whitespace if successful and requested
        self._handle_whitespace_cleanup(path, language, result.success)

        # Provide smart error message if failed
        if not result.success and 'not found' in result.message.lower():
            self._enrich_error_with_symbol_suggestions(path, function_name, result)

        return result

    def find_symbol(
        self, path: str, symbol_name: str, symbol_type: str | None = None
    ) -> SymbolLocation | None:
        """Find a symbol in a file.

        Args:
            path: Path to the file
            symbol_name: Name of the symbol (supports "Class.method")
            symbol_type: Optional type filter ("function", "class", "method")

        Returns:
            SymbolLocation if found, None otherwise

        """
        result = self.universal.find_symbol(path, symbol_name, symbol_type)

        if not result:
            # Provide smart error
            try:
                available_symbols = self._get_available_symbols(path, symbol_type)
                suggestion = self.errors.symbol_not_found(
                    symbol_name, available_symbols
                )
                logger.warning(suggestion.message)
            except Exception:
                logger.warning("Symbol '%s' not found in %s", symbol_name, path)

        return result

    def _validate_line_range(
        self, start_line: int, end_line: int, total_lines: int
    ) -> tuple[bool, str]:
        """Validate line range is valid.

        Args:
            start_line: Start line
            end_line: End line
            total_lines: Total lines in file

        Returns:
            Tuple of (is_valid, error_message)

        """
        # Allow start_line == end_line + 1 as a pure-insert (no lines removed) operation.
        # This is used by insert_code(insert_line=0) → replace_code_range(start=1, end=0).
        is_pure_insert = start_line == end_line + 1 and end_line >= 0
        if (
            start_line < 1
            or end_line > total_lines
            or (start_line > end_line and not is_pure_insert)
        ):
            return (
                False,
                f'Invalid line range: {start_line}-{end_line} (file has {total_lines} lines)',
            )
        return True, ''

    def _apply_auto_indent(
        self, new_code: str, lines: list[str], start_line: int, path: str
    ) -> str:
        """Apply auto-indentation to new code.

        Args:
            new_code: New code to indent
            lines: Original file lines
            start_line: Line to replace
            path: File path

        Returns:
            Indented code

        """
        if not self.config.auto_indent:
            return new_code

        language = self.universal.detect_language(path)
        original_content = ''.join(lines)
        indent_config = self.whitespace.detect_indent(original_content, language)

        if start_line <= len(lines):
            base_indent = self.whitespace.get_line_indent(
                lines[start_line - 1], indent_config
            )
            return self.whitespace.auto_indent_block(
                new_code,
                base_indent=base_indent,
                config=indent_config,
                language=language,
            )
        return new_code

    def _validate_syntax_after_edit(
        self, new_content: str, original_lines: list[str], path: str
    ) -> tuple[bool, str]:
        """Validate syntax of edited content.

        Args:
            new_content: New content to validate
            original_lines: Original lines
            path: File path

        Returns:
            Tuple of (is_valid, error_message)

        """
        if not self.config.validate_syntax:
            return True, ''

        language = self.universal.detect_language(path)
        if language:
            validation = self.universal.validate_syntax(new_content, path, language)
            if not validation[0]:
                return False, f'Syntax error after edit: {validation[1]}'

        return True, ''

    def _write_and_clean_file(self, path: str, content: str) -> str:
        """Write content to file and optionally clean whitespace."""
        if self.config.backup_enabled:
            try:
                old_content = None
                if os.path.exists(path):
                    with open(path, encoding='utf-8') as f:
                        old_content = f.read()
                global_undo_manager.push(path, old_content, 'symbol_edit')
            except Exception as e:
                logger.warning('Failed to save undo history: %s', e)

        self._write_text_atomically(path, content)
        final_content = content

        if self.config.clean_whitespace:
            language = self.universal.detect_language(path)
            cleaned = self.whitespace.clean_whitespace(content, language=language)
            self._write_text_atomically(path, cleaned)
            final_content = cleaned

        return final_content

    def replace_code_range(
        self, path: str, start_line: int, end_line: int, new_code: str
    ) -> EditResult:
        """Replace a range of lines with new code.

        Args:
            path: Path to the file
            start_line: Start line (1-indexed)
            end_line: End line (1-indexed, inclusive)
            new_code: New code to insert

        Returns:
            EditResult with success status

        """
        try:
            with open(path, encoding='utf-8') as f:
                lines = f.readlines()

            is_valid, error_msg = self._validate_line_range(
                start_line, end_line, len(lines)
            )
            if not is_valid:
                return EditResult(success=False, message=error_msg)

            new_code = self._apply_auto_indent(new_code, lines, start_line, path)

            new_lines = lines[: start_line - 1] + [new_code + '\n'] + lines[end_line:]
            new_content = ''.join(new_lines)

            is_valid, error_msg = self._validate_syntax_after_edit(
                new_content, lines, path
            )
            if not is_valid:
                return EditResult(
                    success=False,
                    message=error_msg,
                    syntax_valid=False,
                    original_code=''.join(lines),
                )

            final_content = self._write_and_clean_file(path, new_content)
            verified, verify_msg = self._verify_disk_content(
                path, final_content, operation='line span replacement'
            )
            if not verified:
                return EditResult(
                    success=False,
                    message=verify_msg,
                    syntax_valid=False,
                    original_code=''.join(lines),
                )

            result = EditResult(
                success=True,
                message=f'Replaced lines {start_line}-{end_line}',
                modified_code=final_content,
                lines_changed=end_line - start_line + 1,
                original_code=''.join(lines),
            )

            # Add context window showing the edited region with line numbers
            old_content = ''.join(lines)
            context_window = _format_context_window(old_content, final_content)
            if context_window:
                result.message += '\n\n' + context_window

            return result

        except Exception as e:
            return EditResult(success=False, message=f'Error: {e}')

    # ========================================================================
    # MULTI-FILE OPERATIONS
    # ========================================================================

    def begin_refactoring(self) -> RefactorTransaction:
        """Begin a multi-file atomic refactoring transaction.

        Usage:
            transaction = editor.begin_refactoring()
            transaction.add_edit(...)
            result = editor.commit_refactoring(transaction)

        Or use context manager:
            with editor.begin_refactoring() as transaction:
                transaction.add_edit(...)
                # Auto-commits on success, rolls back on error

        Returns:
            RefactorTransaction

        """
        return self.refactor.begin_transaction()

    def commit_refactoring(self, transaction: RefactorTransaction) -> RefactorResult:
        """Commit a refactoring transaction.

        Args:
            transaction: Transaction to commit

        Returns:
            RefactorResult with success status

        """
        # Dry-run first if requested
        if self.config.dry_run_first:
            dry_result = self.refactor.dry_run(transaction)
            if not dry_result.success:
                logger.warning('Dry-run failed: %s', dry_result.message)
                return dry_result

        # Commit
        result = self.refactor.commit(transaction, validate=self.config.validate_syntax)

        # Cleanup on success
        if result.success:
            self.refactor.cleanup_transaction(transaction)

        return result

    def rollback_refactoring(self, transaction: RefactorTransaction) -> RefactorResult:
        """Rollback a refactoring transaction.

        Args:
            transaction: Transaction to rollback

        Returns:
            RefactorResult

        """
        result = self.refactor.rollback(transaction)
        self.refactor.cleanup_transaction(transaction)
        return result

    # ========================================================================
    # HELPER METHODS
    # ========================================================================

    def _get_available_symbols(
        self, path: str, symbol_type: str | None = None
    ) -> list[str]:
        """Get list of available symbols in a file."""
        try:
            parse_result = self.universal.parse_file(path)
            if not parse_result:
                return []

            tree, file_bytes, _language = parse_result
            root = tree.root_node

            symbols: list[str] = []

            def extract_symbols(node: Any, parent_name: str | None = None):
                """Recursively extract function and class symbols from AST node.

                Args:
                    node: Tree-sitter AST node to extract symbols from
                    parent_name: Name of the parent class (for methods)

                """
                # Functions
                if node.type in [
                    'function_definition',
                    'function_declaration',
                    'method_definition',
                ]:
                    name_node = self.universal.get_name_node(node)
                    if name_node:
                        name = file_bytes[
                            name_node.start_byte : name_node.end_byte
                        ].decode('utf-8')

                        full_name = f'{parent_name}.{name}' if parent_name else name

                        if not symbol_type or symbol_type == 'function':
                            symbols.append(full_name)

                # Classes
                elif node.type in ['class_definition', 'class_declaration']:
                    name_node = self.universal.get_name_node(node)
                    if name_node:
                        name = file_bytes[
                            name_node.start_byte : name_node.end_byte
                        ].decode('utf-8')
                        if not symbol_type or symbol_type == 'class':
                            symbols.append(name)

                        # Recurse into class members with parent_name
                        for child in node.children:
                            extract_symbols(child, parent_name=name)
                        return

                # Default recursion
                for child in node.children:
                    extract_symbols(child, parent_name=parent_name)

            extract_symbols(root)
            return symbols

        except Exception as e:
            logger.debug('Failed to extract symbols: %s', e)
            return []

    def get_supported_languages(self) -> list[str]:
        """Get list of all supported languages."""
        return self.universal.get_supported_languages()

    def normalize_file_indent(
        self,
        path: str,
        target_style: str | None = None,
        target_size: int | None = None,
    ) -> EditResult:
        """Normalize indentation in a file.

        Args:
            path: Path to the file
            target_style: Target style ("spaces" or "tabs", auto-detected if None)
            target_size: Target indent size (auto-detected if None)

        Returns:
            EditResult

        """
        try:
            with open(path, encoding='utf-8') as f:
                original = f.read()

            language = self.universal.detect_language(path)

            # Create target config
            if target_style or target_size:
                from backend.engine.tools.whitespace_handler import IndentStyle

                current = self.whitespace.detect_indent(original, language)
                style = (
                    IndentStyle.TABS if target_style == 'tabs' else IndentStyle.SPACES
                )
                size = target_size or current.size
                from backend.engine.tools.whitespace_handler import IndentConfig

                target_config = IndentConfig(
                    style=style, size=size, line_ending=current.line_ending
                )
            else:
                target_config = None

            # Normalize
            normalized = self.whitespace.normalize_indent(
                original, target_config, language
            )

            # Write back
            with open(path, 'w', encoding='utf-8') as f:
                f.write(normalized)

            return EditResult(
                success=True,
                message=f'Normalized indentation in {path}',
                modified_code=normalized,
                original_code=original,
            )

        except Exception as e:
            return EditResult(
                success=False, message=f'Failed to normalize indentation: {e}'
            )

    def clear_caches(self):
        """Clear all internal caches."""
        self.universal.clear_cache()
        logger.debug('Cleared editor caches')

    def _determine_view_range(
        self, line_range: list[int] | None, total_lines: int
    ) -> tuple[int, int]:
        """Determine and clamp start/end lines for viewing."""
        start_line = 1
        end_line = total_lines

        if line_range:
            if line_range:
                start_line = line_range[0]
            if len(line_range) >= 2 and line_range[1] != -1:
                end_line = line_range[1]

        # Clamp ranges
        start_line = max(1, start_line)
        end_line = min(total_lines, end_line)
        return start_line, end_line

    def _format_view_output(
        self, lines: list[str], start_line: int, end_line: int
    ) -> str:
        """Format lines with line numbers for output."""
        output: list[str] = []
        for i in range(start_line - 1, end_line):
            output.append(f'{i + 1:6d}\t{lines[i].rstrip()}')
        return '\n'.join(output)

    def _handle_auto_indent(self, path: str, language: str, code: str) -> str:
        """Apply auto-indentation if enabled."""
        if not self.config.auto_indent:
            return code
        try:
            with open(path, encoding='utf-8') as f:
                content = f.read()
            indent_config = self.whitespace.detect_indent(content, language)
            return self.whitespace.auto_indent_block(
                code, base_indent=1, config=indent_config, language=language
            )
        except Exception as e:
            logger.warning('Auto-indent failed: %s', e)
            return code

    def _handle_whitespace_cleanup(
        self, path: str, language: str, success: bool
    ) -> None:
        """Clean whitespace if edit was successful and requested."""
        if success and self.config.clean_whitespace:
            try:
                with open(path, encoding='utf-8') as f:
                    content = f.read()
                cleaned = self.whitespace.clean_whitespace(content, language=language)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(cleaned)
            except Exception as e:
                logger.warning('Whitespace cleanup failed: %s', e)

    def _enrich_error_with_symbol_suggestions(
        self, path: str, symbol_name: str, result: EditResult
    ) -> None:
        """Add symbol suggestions to error message if applicable."""
        try:
            available_symbols = self._get_available_symbols(path, 'function')
            suggestion = self.errors.symbol_not_found(symbol_name, available_symbols)
            result.message += f'\n\n{suggestion.message}'
        except Exception as e:
            logger.debug('Failed to enrich error with suggestions: %s', e)
