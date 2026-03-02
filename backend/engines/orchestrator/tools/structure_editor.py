"""Ultimate editor providing a unified interface for structure-aware editing.

High-level interface that intelligently routes operations to the best editor backend.
Provides simple, powerful API for all code editing operations.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from backend.core.logger import forge_logger as logger

from backend.utils.treesitter_editor import EditResult, SymbolLocation, TreeSitterEditor
from .atomic_refactor import AtomicRefactor, RefactorResult, RefactorTransaction
from .smart_errors import SmartErrorHandler
from .whitespace_handler import WhitespaceHandler
from .lsp_client import get_lsp_client


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

    # Rename across the entire file
    result = editor.rename_symbol("myfile.py", "old_name", "new_name")

    # Multi-file refactoring (atomic - all succeed or all fail)
    with editor.begin_refactoring() as refactor:
        refactor.edit_file("file1.py", new_content="...")
        refactor.edit_file("file2.py", new_content="...")
        # Commits automatically, or rolls back on error

    # Standard file operations
    editor.create_file("new_file.py", "print('hello')")
    editor.view_file("new_file.py")
    editor.insert_code("new_file.py", 1, "import os")
    editor.undo_last_edit("new_file.py")
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

        self._undo_history: dict[
            str, list[tuple[str, str]]
        ] = {}  # file_path -> [(hash, content)]

        logger.info("🚀 Ultimate Editor initialized")
        logger.info(
            "   - Tree-sitter: %s languages",
            len(self.universal.get_supported_languages()),
        )
        logger.info("   - Auto-indent: %s", self.config.auto_indent)
        logger.info("   - Validation: %s", self.config.validate_syntax)

    # ========================================================================
    # HIGH-LEVEL OPERATIONS
    # ========================================================================

    def create_file(self, file_path: str, content: str) -> EditResult:
        """Create a new file.

        Args:
            file_path: Path to the file
            content: File content

        Returns:
            EditResult
        """
        if os.path.exists(file_path):
            return EditResult(
                success=False,
                message=f"File already exists: {file_path}. Use replace_range or edit_function to modify it.",
            )

        try:
            # Create parent directories if needed
            os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

            return EditResult(
                success=True,
                message=f"Created file {file_path}",
                modified_code=content,
                lines_changed=content.count("\n") + 1,
            )
        except Exception as e:
            return EditResult(success=False, message=f"Failed to create file: {e}")

    def view_file(
        self, file_path: str, line_range: list[int] | None = None
    ) -> EditResult:
        """View file content or directory listing.

        Args:
            file_path: Path to view
            line_range: Optional [start, end] lines (1-indexed)

        Returns:
            EditResult with content in message
        """
        if not os.path.exists(file_path):
            return EditResult(success=False, message=f"Path not found: {file_path}")

        if os.path.isdir(file_path):
            return self._view_directory(file_path)

        try:
            with open(file_path, encoding="utf-8") as f:
                lines = f.readlines()

            start_line, end_line = self._determine_view_range(line_range, len(lines))

            if start_line > end_line:
                return EditResult(
                    success=False,
                    message=f"Invalid line range: {start_line}-{end_line}",
                )

            # Format with line numbers (cat -n style)
            content_view = self._format_view_output(lines, start_line, end_line)

            return EditResult(
                success=True,
                message=f"Showing lines {start_line}-{end_line} of {file_path}:\n{content_view}",
                original_code="".join(lines),
            )

        except Exception as e:
            return EditResult(success=False, message=f"Error reading file: {e}")

    def insert_code(
        self, file_path: str, insert_line: int, new_code: str
    ) -> EditResult:
        """Insert code after a specific line.

        Args:
            file_path: Path to file
            insert_line: Line number to insert after (0 for beginning of file)
            new_code: Code to insert

        Returns:
            EditResult
        """
        return self.replace_code_range(
            file_path,
            start_line=insert_line + 1,
            end_line=insert_line,
            new_code=new_code,
        )

    def undo_last_edit(self, file_path: str) -> EditResult:
        """Undo the last edit to a file.

        Args:
            file_path: Path to file

        Returns:
            EditResult
        """
        if file_path not in self._undo_history or not self._undo_history[file_path]:
            return EditResult(success=False, message=f"No undo history for {file_path}")

        _, previous_content = self._undo_history[file_path].pop()

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(previous_content)

            return EditResult(
                success=True,
                message=f"Undid last edit to {file_path}",
                modified_code=previous_content,
            )
        except Exception as e:
            return EditResult(success=False, message=f"Failed to undo: {e}")

    def _view_directory(self, path: str, max_depth: int = 2) -> EditResult:
        """List directory contents."""
        output = []
        base_level = path.rstrip(os.sep).count(os.sep)

        for root, dirs, files in os.walk(path):
            level = root.count(os.sep) - base_level
            if level >= max_depth:
                del dirs[:]
                continue

            # Skip hidden
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            files = [f for f in files if not f.startswith(".")]

            indent = "  " * level
            output.append(f"{indent}{os.path.basename(root)}/")
            subindent = "  " * (level + 1)
            for f in files:
                output.append(f"{subindent}{f}")

        return EditResult(success=True, message="\n".join(output))

    def edit_function(
        self, file_path: str, function_name: str, new_body: str
    ) -> EditResult:
        """Edit a function by name (works for ANY language).

        Args:
            file_path: Path to the file
            function_name: Name of the function to edit
            new_body: New function body

        Returns:
            EditResult with success status

        """
        logger.info("Editing function '%s' in %s", function_name, file_path)

        # Detect language
        language = self.universal.detect_language(file_path)
        if not language:
            return EditResult(
                success=False, message=f"Cannot detect language for {file_path}"
            )

        # Auto-indent new body if requested
        new_body = self._handle_auto_indent(file_path, language, new_body)

        # Perform edit
        result = self.universal.edit_function(
            file_path, function_name, new_body, validate=self.config.validate_syntax
        )

        # Clean whitespace if successful and requested
        self._handle_whitespace_cleanup(file_path, language, result.success)

        # Provide smart error message if failed
        if not result.success and "not found" in result.message.lower():
            self._enrich_error_with_symbol_suggestions(file_path, function_name, result)

        # Blast Radius Hook: if successful, checking symbol references
        if result.success:
            self._check_blast_radius(file_path, function_name, result)

        return result

    def rename_symbol(self, file_path: str, old_name: str, new_name: str) -> EditResult:
        """Rename a symbol throughout a file.

        Args:
            file_path: Path to the file
            old_name: Current symbol name
            new_name: New symbol name

        Returns:
            EditResult with success status

        """
        logger.info("Renaming '%s' → '%s' in %s", old_name, new_name, file_path)

        result = self.universal.rename_symbol(file_path, old_name, new_name)

        # Clean whitespace if successful
        if result.success and self.config.clean_whitespace:
            language = self.universal.detect_language(file_path)
            try:
                with open(file_path, encoding="utf-8") as f:
                    content = f.read()

                cleaned = self.whitespace.clean_whitespace(content, language=language)

                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(cleaned)
            except Exception as e:
                logger.warning("Whitespace cleanup failed: %s", e)

        return result

    def find_symbol(
        self, file_path: str, symbol_name: str, symbol_type: str | None = None
    ) -> SymbolLocation | None:
        """Find a symbol in a file.

        Args:
            file_path: Path to the file
            symbol_name: Name of the symbol (supports "Class.method")
            symbol_type: Optional type filter ("function", "class", "method")

        Returns:
            SymbolLocation if found, None otherwise

        """
        result = self.universal.find_symbol(file_path, symbol_name, symbol_type)

        if not result:
            # Provide smart error
            try:
                available_symbols = self._get_available_symbols(file_path, symbol_type)
                suggestion = self.errors.symbol_not_found(
                    symbol_name, available_symbols
                )
                logger.warning(suggestion.message)
            except Exception:
                logger.warning("Symbol '%s' not found in %s", symbol_name, file_path)

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
                f"Invalid line range: {start_line}-{end_line} (file has {total_lines} lines)",
            )
        return True, ""

    def _apply_auto_indent(
        self, new_code: str, lines: list[str], start_line: int, file_path: str
    ) -> str:
        """Apply auto-indentation to new code.

        Args:
            new_code: New code to indent
            lines: Original file lines
            start_line: Line to replace
            file_path: File path

        Returns:
            Indented code

        """
        if not self.config.auto_indent:
            return new_code

        language = self.universal.detect_language(file_path)
        original_content = "".join(lines)
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
        self, new_content: str, original_lines: list[str], file_path: str
    ) -> tuple[bool, str]:
        """Validate syntax of edited content.

        Args:
            new_content: New content to validate
            original_lines: Original lines
            file_path: File path

        Returns:
            Tuple of (is_valid, error_message)

        """
        if not self.config.validate_syntax:
            return True, ""

        language = self.universal.detect_language(file_path)
        if language:
            validation = self.universal._validate_syntax(
                new_content, file_path, language
            )
            if not validation[0]:
                return False, f"Syntax error after edit: {validation[1]}"

        return True, ""

    def _write_and_clean_file(self, file_path: str, content: str) -> None:
        """Write content to file and optionally clean whitespace."""
        # Save to undo history before writing
        if self.config.backup_enabled:
            try:
                if os.path.exists(file_path):
                    with open(file_path, encoding="utf-8") as f:
                        old_content = f.read()
                    if file_path not in self._undo_history:
                        self._undo_history[file_path] = []
                    self._undo_history[file_path].append(("hash", old_content))
                    # Keep history limited
                    if len(self._undo_history[file_path]) > 10:
                        self._undo_history[file_path].pop(0)
            except Exception as e:
                logger.warning("Failed to save undo history: %s", e)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        if self.config.clean_whitespace:
            language = self.universal.detect_language(file_path)
            cleaned = self.whitespace.clean_whitespace(content, language=language)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(cleaned)

    def replace_code_range(
        self, file_path: str, start_line: int, end_line: int, new_code: str
    ) -> EditResult:
        """Replace a range of lines with new code.

        Args:
            file_path: Path to the file
            start_line: Start line (1-indexed)
            end_line: End line (1-indexed, inclusive)
            new_code: New code to insert

        Returns:
            EditResult with success status

        """
        try:
            with open(file_path, encoding="utf-8") as f:
                lines = f.readlines()

            is_valid, error_msg = self._validate_line_range(
                start_line, end_line, len(lines)
            )
            if not is_valid:
                return EditResult(success=False, message=error_msg)

            new_code = self._apply_auto_indent(new_code, lines, start_line, file_path)

            new_lines = lines[: start_line - 1] + [new_code + "\n"] + lines[end_line:]
            new_content = "".join(new_lines)

            is_valid, error_msg = self._validate_syntax_after_edit(
                new_content, lines, file_path
            )
            if not is_valid:
                return EditResult(
                    success=False,
                    message=error_msg,
                    syntax_valid=False,
                    original_code="".join(lines),
                )

            self._write_and_clean_file(file_path, new_content)

            result = EditResult(
                success=True,
                message=f"Replaced lines {start_line}-{end_line}",
                modified_code=new_content,
                lines_changed=end_line - start_line + 1,
                original_code="".join(lines),
            )

            # Blast Radius Hook: best-effort check using the first few symbols found in the new code
            self._check_blast_radius_from_code(file_path, new_code, result)

            return result

        except Exception as e:
            return EditResult(success=False, message=f"Error: {e}")

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
                logger.warning("Dry-run failed: %s", dry_result.message)
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
        self, file_path: str, symbol_type: str | None = None
    ) -> list[str]:
        """Get list of available symbols in a file."""
        try:
            parse_result = self.universal.parse_file(file_path)
            if not parse_result:
                return []

            tree, file_bytes, language = parse_result
            root = tree.root_node

            symbols = []

            def extract_symbols(node):
                """Recursively extract function and class symbols from AST node.

                Args:
                    node: Tree-sitter AST node to extract symbols from

                """
                # Functions
                if node.type in [
                    "function_definition",
                    "function_declaration",
                    "method_definition",
                ]:
                    name_node = self.universal._get_name_node(node)
                    if name_node:
                        name = file_bytes[
                            name_node.start_byte : name_node.end_byte
                        ].decode("utf-8")
                        if not symbol_type or symbol_type == "function":
                            symbols.append(name)

                # Classes
                elif node.type in ["class_definition", "class_declaration"]:
                    name_node = self.universal._get_name_node(node)
                    if name_node:
                        name = file_bytes[
                            name_node.start_byte : name_node.end_byte
                        ].decode("utf-8")
                        if not symbol_type or symbol_type == "class":
                            symbols.append(name)

                # Recurse
                for child in node.children:
                    extract_symbols(child)

            extract_symbols(root)
            return symbols

        except Exception as e:
            logger.debug("Failed to extract symbols: %s", e)
            return []

    def get_supported_languages(self) -> list[str]:
        """Get list of all supported languages."""
        return self.universal.get_supported_languages()

    def normalize_file_indent(
        self,
        file_path: str,
        target_style: str | None = None,
        target_size: int | None = None,
    ) -> EditResult:
        """Normalize indentation in a file.

        Args:
            file_path: Path to the file
            target_style: Target style ("spaces" or "tabs", auto-detected if None)
            target_size: Target indent size (auto-detected if None)

        Returns:
            EditResult

        """
        try:
            with open(file_path, encoding="utf-8") as f:
                original = f.read()

            language = self.universal.detect_language(file_path)

            # Create target config
            if target_style or target_size:
                from .whitespace_handler import IndentStyle

                current = self.whitespace.detect_indent(original, language)
                style = (
                    IndentStyle.TABS if target_style == "tabs" else IndentStyle.SPACES
                )
                size = target_size or current.size
                from .whitespace_handler import IndentConfig

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
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(normalized)

            return EditResult(
                success=True,
                message=f"Normalized indentation in {file_path}",
                modified_code=normalized,
                original_code=original,
            )

        except Exception as e:
            return EditResult(
                success=False, message=f"Failed to normalize indentation: {e}"
            )

    def clear_caches(self):
        """Clear all internal caches."""
        self.universal.clear_cache()
        logger.debug("Cleared editor caches")

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
        output = []
        for i in range(start_line - 1, end_line):
            output.append(f"{i + 1:6d}\t{lines[i].rstrip()}")
        return "\n".join(output)

    def _handle_auto_indent(self, file_path: str, language: str, code: str) -> str:
        """Apply auto-indentation if enabled."""
        if not self.config.auto_indent:
            return code
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()
            indent_config = self.whitespace.detect_indent(content, language)
            return self.whitespace.auto_indent_block(
                code, base_indent=1, config=indent_config, language=language
            )
        except Exception as e:
            logger.warning("Auto-indent failed: %s", e)
            return code

    def _handle_whitespace_cleanup(
        self, file_path: str, language: str, success: bool
    ) -> None:
        """Clean whitespace if edit was successful and requested."""
        if success and self.config.clean_whitespace:
            try:
                with open(file_path, encoding="utf-8") as f:
                    content = f.read()
                cleaned = self.whitespace.clean_whitespace(content, language=language)
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(cleaned)
            except Exception as e:
                logger.warning("Whitespace cleanup failed: %s", e)

    def _enrich_error_with_symbol_suggestions(
        self, file_path: str, symbol_name: str, result: EditResult
    ) -> None:
        """Add symbol suggestions to error message if applicable."""
        try:
            available_symbols = self._get_available_symbols(file_path, "function")
            suggestion = self.errors.symbol_not_found(symbol_name, available_symbols)
            result.message += f"\n\n{suggestion.message}"
        except Exception:
            pass

    def _check_blast_radius(
        self, file_path: str, symbol_name: str, result: EditResult, threshold: int = 10
    ) -> None:
        """Query LSP for references to the edited symbol and append a warning if it exceeds the threshold."""
        try:
            # First find where the symbol actually is so we can query LSP
            loc = self.universal.find_symbol(file_path, symbol_name)
            if not loc:
                return

            lsp = get_lsp_client()

            lsp_result = lsp.query(
                "find_references",
                file=file_path,
                line=loc.line_start,
                column=1,
            )
            refs = lsp_result.locations

            if len(refs) > threshold:
                warning = f"\n\n[WARNING: BLAST RADIUS EXCEEDS {threshold}] The symbol '{symbol_name}' is referenced in {len(refs)} other locations. Please consider if those call sites need updating."
                result.message += warning
                logger.info(
                    "Blast radius warning added for %s (%d references)",
                    symbol_name,
                    len(refs),
                )
        except Exception as e:
            logger.debug("Blast radius check failed for %s: %s", symbol_name, e)

    def _check_blast_radius_from_code(
        self, file_path: str, code_snippet: str, result: EditResult, threshold: int = 10
    ) -> None:
        """Extract a primary symbol from the snippet and check its blast radius."""
        try:
            # Very basic heuristic: if they're defining a function/class, check that.
            import re

            match = re.search(
                r"^\s*(?:async\s+)?(?:def|class)\s+([a-zA-Z_]\w*)",
                code_snippet,
                re.MULTILINE,
            )
            if match:
                symbol_name = match.group(1)
                self._check_blast_radius(file_path, symbol_name, result, threshold)
        except Exception:
            pass
