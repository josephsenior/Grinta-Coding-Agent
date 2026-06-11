"""Universal Tree-sitter-based editor supporting all major languages.

Language-agnostic editor using Tree-sitter for structure-aware editing.
Works with Python, JavaScript, TypeScript, Go, Rust, Java, C++, Ruby, PHP, and 40+ more.

The implementation is split across several helpers:

- :mod:`backend.utils._tse_runtime` — runtime detection of tree-sitter
  (``TREE_SITTER_AVAILABLE``, ``_get_language``, ``_get_parser``, ``_RuntimeParser``).
- :mod:`backend.utils._tse_types` — public types (``SymbolLocation``,
  ``AmbiguousSymbolError``, ``EditResult``).
- :mod:`backend.utils._tse_languages` — ``LANGUAGE_EXTENSIONS`` and per-language
  node-type lookup helpers.
- :mod:`backend.utils._tse_errors` — syntax-error renderers.
- :mod:`backend.utils._tse_query` — tree-walking helpers.

This module keeps the ``TreeSitterEditor`` class (with a one-line forwarder
per public method) and re-exports the public API for callers and tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from backend.core.logger import app_logger as logger
from backend.utils._tse_errors import (  # noqa: F401
    _format_python_ast_syntax_error,
    _format_treesitter_error_block,
    _render_python_syntax_error,
)
from backend.utils._tse_languages import (
    LANGUAGE_EXTENSIONS,
    get_function_node_types,
)
from backend.utils._tse_query import (
    expand_body_range,
    find_all_nodes_by_name,
    find_class_node,
    find_method_in_class,
    find_method_node_in_class,
    find_node_by_name,
    get_function_body_node,
    get_name_node,
    has_syntax_errors,
    replace_node_content,
    search_tree_for_symbol,
)
from backend.utils._tse_runtime import (
    TREE_SITTER_AVAILABLE,
    _get_language,
    _get_parser,
    _RuntimeParser,
)
from backend.utils._tse_types import (
    AmbiguousSymbolError,
    EditResult,
    SymbolLocation,
)

__all__ = [
    'AmbiguousSymbolError',
    'EditResult',
    'LANGUAGE_EXTENSIONS',
    'SymbolLocation',
    'TREE_SITTER_AVAILABLE',
    'TreeSitterEditor',
    '_get_language',
    '_get_parser',
]


class TreeSitterEditor:
    """Universal editor powered by Tree-sitter.

    🎯 Supports 45+ languages through unified Tree-sitter API:

    **Core Languages:**
    - Python, JavaScript, TypeScript, Go, Rust, Java, C/C++

    **JVM Ecosystem:**
    - Kotlin, Scala, Clojure

    **.NET Ecosystem:**
    - C#, F#

    **Scripting:**
    - Ruby, PHP, Perl, Lua, R

    **Web:**
    - HTML, CSS/SCSS, Vue, Svelte

    **Functional:**
    - Haskell, Elixir, Erlang, OCaml, Elm

    **Modern Systems:**
    - Swift, Objective-C, Dart

    **Data/Config:**
    - JSON, YAML, TOML, XML

    **Shell:**
    - Bash, Zsh, Fish

    **Query:**
    - SQL, GraphQL

    **Other:**
    - Protocol Buffers, Markdown, LaTeX, Julia

    ✅ Provides structure-aware editing without fragile string matching.
    """

    def __init__(self) -> None:
        """Initialize the universal editor."""
        if not TREE_SITTER_AVAILABLE:
            raise ImportError(
                '🚨 CRITICAL: Tree-sitter not available!\n\n'
                'Ultimate Editor requires Tree-sitter for structure-aware editing.\n'
                "This is Grinta's competitive advantage - without it, only basic editing works.\n\n"
                'PRODUCTION DEPLOYMENT ERROR:\n'
                '  Tree-sitter should be a required dependency in pyproject.toml.\n'
                '  Check that your runtime environment has the latest dependencies installed.\n\n'
                'Quick fix (temporary): pip install tree-sitter tree-sitter-language-pack\n'
                'Permanent fix: Ensure pyproject.toml has tree_sitter in main dependencies (not optional)'
            )

        self.parsers: dict[str, Any] = {}
        self.tree_cache: dict[str, Any] = {}
        self.file_cache: dict[str, bytes] = {}

        logger.info('Universal Editor initialized with Tree-sitter support')

    def detect_language(self, file_path: str) -> str | None:
        """Detect programming language from file extension.

        Args:
            file_path: Path to the file

        Returns:
            Language name (e.g., "python", "javascript", "go") or None

        """
        ext = Path(file_path).suffix.lower()
        return LANGUAGE_EXTENSIONS.get(ext)

    def get_parser(self, language: str) -> Any:
        """Get or create a Tree-sitter parser for a language.

        Args:
            language: Language name (python, javascript, go, etc.)

        Returns:
            Parser instance or None if language not supported

        """
        if language in self.parsers:
            return self.parsers[language]

        if _get_language is None or _RuntimeParser is None:
            logger.error('Tree-sitter language pack is not available')
            return None

        try:
            lang = cast(Any, _get_language)(language)
            parser = _RuntimeParser(lang)
        except Exception as e:  # pragma: no cover - dependent on runtime env
            logger.error('Failed to create parser for %s: %s', language, e)
            return None

        self.parsers[language] = parser
        return parser

    def parse_file(
        self, file_path: str, use_cache: bool = True
    ) -> tuple[Any, bytes, str] | None:
        """Parse a file using Tree-sitter.

        Args:
            file_path: Path to the file
            use_cache: Whether to use cached tree

        Returns:
            Tuple of (Tree, file_bytes, language) or None if parsing fails

        """
        if use_cache and file_path in self.tree_cache:
            return (
                self.tree_cache[file_path],
                self.file_cache[file_path],
                self.detect_language(file_path) or '',
            )

        try:
            # Detect language
            language = self.detect_language(file_path)
            if not language:
                logger.warning('Unknown file type: %s', file_path)
                return None

            # Get parser
            parser = self.get_parser(language)
            if not parser:
                return None

            # Read file as bytes (Tree-sitter requires bytes)
            with open(file_path, 'rb') as f:
                file_bytes = f.read()

            # Parse
            tree = parser.parse(file_bytes)

            if use_cache:
                self.tree_cache[file_path] = tree
                self.file_cache[file_path] = file_bytes

            return tree, file_bytes, language

        except FileNotFoundError:
            logger.error('File not found: %s', file_path)
            return None

    def find_symbol(
        self,
        file_path: str,
        symbol_name: str,
        symbol_type: str | None = None,
        line_number: int | None = None,
    ) -> SymbolLocation | None:
        """Find a symbol in any language file.

        Args:
            file_path: Path to the file
            symbol_name: Name of the symbol (supports "Class.method" for methods)
            symbol_type: Optional filter (e.g., "function", "class", "method")
            line_number: Optional line number to disambiguate when multiple matches exist

        Returns:
            SymbolLocation if found, None otherwise
            Raises AmbiguousSymbolError if multiple matches and no line_number provided

        """
        parse_result = self.parse_file(file_path, use_cache=True)
        if not parse_result:
            return None

        tree, file_bytes, language = parse_result

        # Handle dot notation for methods
        if '.' in symbol_name:
            parts = symbol_name.split('.')
            if len(parts) == 2:
                try:
                    return find_method_in_class(
                        self,
                        tree,
                        file_bytes,
                        parts[0],
                        parts[1],
                        file_path,
                        language,
                    )
                except AmbiguousSymbolError:
                    raise

        # Search for symbol
        try:
            return search_tree_for_symbol(
                self,
                tree,
                file_bytes,
                symbol_name,
                file_path,
                language,
                symbol_type,
            )
        except AmbiguousSymbolError as e:
            if line_number:
                for match in e.matches:
                    if match.line_start == line_number:
                        return match
                return None
            raise

    def edit_function(
        self,
        file_path: str,
        function_name: str,
        new_body: str,
        validate: bool = True,
        line_number: int | None = None,
    ) -> EditResult:
        """Edit a function's body (works for ANY language).

        Args:
            file_path: Path to the file
            function_name: Name of the function
            new_body: New function body
            validate: Whether to validate after editing
            line_number: Optional line number to disambiguate when multiple matches exist

        Returns:
            EditResult with success status

        """
        parse_result = self.parse_file(file_path, use_cache=False)
        if not parse_result:
            return EditResult(success=False, message=f'Failed to parse {file_path}')

        tree, file_bytes, language = parse_result
        original_code = file_bytes.decode('utf-8')

        # Find the function or class node
        logger.info(f"Looking for symbol '{function_name}' in {file_path}")
        try:
            func_node = self._find_function_node(
                tree, file_bytes, function_name, language, line_number=line_number
            )
        except AmbiguousSymbolError as e:
            if line_number:
                for match in e.matches:
                    if match.line_start == line_number:
                        break
                else:
                    logger.warning(
                        f"Symbol '{function_name}' not found at line {line_number} in {file_path}"
                    )
                    return EditResult(
                        success=False,
                        message=f"Function '{function_name}' not found at line {line_number} in {file_path}",
                    )
                func_node = None
            else:
                logger.warning(f"Ambiguous symbol '{function_name}': {e}")
                return EditResult(
                    success=False,
                    message=str(e),
                )
        if not func_node:
            class_node = self._find_class_node(
                tree, file_bytes, function_name, language
            )
            if class_node is not None:
                func_node = class_node

        if not func_node:
            # Check if tree has syntax errors (parse was partially successful but broken)
            if has_syntax_errors(tree.root_node):
                logger.info(
                    f"AST contains errors, attempting text-based fallback for '{function_name}'"
                )
                return self._edit_function_text_fallback(
                    file_path,
                    function_name,
                    new_body,
                    original_code,
                    language,
                    validate,
                )
            logger.warning(f"Symbol '{function_name}' not found in {file_path}")
            return EditResult(
                success=False,
                message=f"Function '{function_name}' not found in {file_path}",
            )

        logger.debug(f"Found node for '{function_name}' (type: {func_node.type})")

        # Extract function body node (language-specific)
        body_node = get_function_body_node(func_node, language)
        if not body_node:
            return EditResult(
                success=False,
                message=f"Could not locate function body for '{function_name}'",
            )

        # Expand body range to include comments/decorators between ':' and block
        effective_body = expand_body_range(func_node, body_node)

        # Replace the body
        try:
            new_code = replace_node_content(
                original_code,
                cast(Any, effective_body),
                new_body,
                preserve_indentation=True,
            )

            # Normalize CRLF -> LF early so validation sees a consistent EOL style
            new_code = new_code.replace('\r\n', '\n').replace('\r', '\n')

            # Validate if requested against normalized content
            if validate:
                validation_result = self.validate_syntax(new_code, file_path, language)
                if not validation_result[0]:
                    return EditResult(
                        success=False,
                        message=f'Syntax error after edit: {validation_result[1]}',
                        syntax_valid=False,
                        original_code=original_code,
                    )

            # Write back
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_code)

            # Clear cache
            self.tree_cache.pop(file_path, None)
            self.file_cache.pop(file_path, None)

            lines_changed = new_body.count('\n') + 1

            return EditResult(
                success=True,
                message=f"✓ Edited function '{function_name}' in {language} ({lines_changed} lines)",
                modified_code=new_code,
                lines_changed=lines_changed,
                original_code=original_code,
            )

        except Exception as e:
            logger.error('Error editing function: %s', e)
            return EditResult(
                success=False, message=f'Error: {e}', original_code=original_code
            )

    def _find_function_node(
        self,
        tree: Any,
        file_bytes: bytes,
        function_name: str,
        language: str,
        line_number: int | None = None,
    ) -> Any | None:
        """Find function node (language-agnostic using Tree-sitter queries)."""
        root = tree.root_node

        # Handle dot notation for methods (e.g., MyClass.my_method)
        if '.' in function_name:
            parts = function_name.split('.')
            if len(parts) == 2:
                class_name, method_name = parts
                logger.debug(
                    f"Qualified name detected: class='{class_name}', method='{method_name}'"
                )
                class_node = self._find_class_node(
                    tree, file_bytes, class_name, language
                )
                if class_node:
                    return self._find_method_node_in_class(
                        class_node, file_bytes, method_name, language
                    )
                logger.debug(
                    f"Class '{class_name}' not found; falling back to direct lookup for '{function_name}'"
                )

        target_types = get_function_node_types(language)

        # Find ALL matching nodes to detect ambiguity
        all_nodes = find_all_nodes_by_name(
            self, root, file_bytes, function_name, target_types
        )
        if not all_nodes:
            return None

        # Check for ambiguity - multiple matches
        if len(all_nodes) > 1:
            matches = [
                SymbolLocation(
                    file_path='',
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    byte_start=node.start_byte,
                    byte_end=node.end_byte,
                    node_type=node.type,
                    symbol_name=function_name,
                    parent_name=None,
                )
                for node in all_nodes
            ]
            raise AmbiguousSymbolError(function_name, matches)

        return all_nodes[0]

    def _find_class_node(
        self, tree: Any, file_bytes: bytes, class_name: str, language: str
    ) -> Any | None:
        """Find a class node by name."""
        return find_class_node(self, tree, file_bytes, class_name, language)

    def _find_method_node_in_class(
        self,
        class_node: Any,
        file_bytes: bytes,
        method_name: str,
        language: str,
    ) -> Any | None:
        """Find a method node within a class node."""
        return find_method_node_in_class(
            self, class_node, file_bytes, method_name, language
        )

    def _find_node_by_name(
        self,
        node: Any,
        file_bytes: bytes,
        target_name: str,
        node_types: list[str],
    ) -> Any | None:
        """Recursively find a node by name and type."""
        return find_node_by_name(self, node, file_bytes, target_name, node_types)

    def _find_all_nodes_by_name(
        self,
        node: Any,
        file_bytes: bytes,
        target_name: str,
        node_types: list[str],
    ) -> list[Any]:
        """Recursively find ALL nodes matching the name and types (not just first)."""
        return find_all_nodes_by_name(self, node, file_bytes, target_name, node_types)

    def get_name_node(self, node: Any) -> Any | None:
        """Extract the name identifier node from a definition node."""
        return get_name_node(node)

    def _find_method_in_class(
        self,
        tree: Any,
        file_bytes: bytes,
        class_name: str,
        method_name: str,
        file_path: str,
        language: str,
    ) -> SymbolLocation | None:
        """Find a method within a class (language-agnostic)."""
        return find_method_in_class(
            self, tree, file_bytes, class_name, method_name, file_path, language
        )

    def _search_tree_for_symbol(
        self,
        tree: Any,
        file_bytes: bytes,
        symbol_name: str,
        file_path: str,
        language: str,
        symbol_type: str | None = None,
    ) -> SymbolLocation | None:
        """Search tree for any symbol."""
        return search_tree_for_symbol(
            self, tree, file_bytes, symbol_name, file_path, language, symbol_type
        )

    def _get_function_body_node(self, func_node: Any, language: str) -> Any | None:
        """Get the body node of a function (language-specific)."""
        return get_function_body_node(func_node, language)

    def _replace_node_content(
        self,
        original_code: str,
        node: Any,
        new_content: str,
        preserve_indentation: bool = True,
    ) -> str:
        """Replace a node's content while preserving indentation."""
        return replace_node_content(
            original_code, node, new_content, preserve_indentation
        )

    def validate_syntax(
        self, code: str, file_path: str, language: str
    ) -> tuple[bool, str]:
        """Validate syntax by parsing with Tree-sitter.

        Returns:
            Tuple of (is_valid, error_message)

        """
        try:
            # Python: prefer the interpreter's SyntaxError (expected token hints).
            if language == 'python':
                py_msg = _format_python_ast_syntax_error(code, file_path)
                if py_msg is not None:
                    return False, py_msg
                return True, 'Syntax valid'

            parser = self.get_parser(language)
            if not parser:
                return True, 'Parser not available, skipping validation'

            tree = parser.parse(code.encode('utf-8'))

            error_nodes: list[Any] = []

            def _collect_errors(node: Any) -> None:
                if getattr(node, 'type', None) == 'ERROR' or getattr(
                    node, 'is_missing', False
                ):
                    error_nodes.append(node)
                for child in getattr(node, 'children', []) or []:
                    _collect_errors(child)

            _collect_errors(tree.root_node)

            if error_nodes:
                max_show = 3
                lines = code.splitlines()
                parts: list[str] = []
                for node in error_nodes[:max_show]:
                    parts.extend(
                        _format_treesitter_error_block(
                            node, file_path, code, lines, language
                        )
                    )
                    parts.append('')  # blank between error sites
                if parts and parts[-1] == '':
                    parts.pop()
                if len(error_nodes) > max_show:
                    parts.append(
                        f'(and {len(error_nodes) - max_show} more syntax error location(s))'
                    )

                return False, '\n'.join(parts)

            return True, 'Syntax valid'

        except Exception as e:
            logger.warning('Validation failed: %s', e)
            return True, f'Validation skipped: {e}'

    def _has_syntax_errors(self, node: Any) -> bool:
        """Check if tree contains ERROR or MISSING nodes."""
        return has_syntax_errors(node)

    def get_supported_languages(self) -> list[str]:
        """Get list of all supported languages."""
        return list(set(LANGUAGE_EXTENSIONS.values()))

    def _edit_function_text_fallback(
        self,
        file_path: str,
        function_name: str,
        new_body: str,
        original_code: str,
        language: str,
        validate: bool,
    ) -> EditResult:
        """Fallback to text-based function editing when AST has errors."""
        import re

        pattern = _get_fallback_pattern(language, function_name)
        regex = re.compile(pattern, re.MULTILINE)
        match = regex.search(original_code)
        if not match:
            return EditResult(
                success=False,
                message=f"Function '{function_name}' not found in {file_path} (text fallback failed)",
            )

        indent = match.group(1)
        body_start = match.end()
        body_end = _find_fallback_body_end(original_code, body_start, indent, language)
        return _apply_fallback_edit(
            self,
            file_path,
            function_name,
            new_body,
            original_code,
            language,
            validate,
            body_start,
            body_end,
        )

    def clear_cache(self) -> None:
        self.tree_cache.clear()
        self.file_cache.clear()


def _get_fallback_pattern(language: str, function_name: str) -> str:
    import re

    patterns = {
        'python': rf'^(\s*)def\s+{re.escape(function_name)}\s*\([^)]*\)\s*(?::)',
        'javascript': rf'^(\s*)function\s+{re.escape(function_name)}\s*\([^)]*\)',
        'typescript': rf'^(\s*)function\s+{re.escape(function_name)}\s*\([^)]*\)',
        'go': rf'^(\s*)func\s+(?:[^\(]+\.)?{re.escape(function_name)}\s*\([^)]*\)',
        'rust': rf'^(\s*)fn\s+{re.escape(function_name)}\s*\([^)]*\)',
        'java': rf'^(\s*)(?:public|private|protected)?\s*(?:static)?\s*\w+\s+{re.escape(function_name)}\s*\([^)]*\)',
        'cpp': rf'^(\s*)\w+(?:\s+\w+)*\s+{re.escape(function_name)}\s*\([^)]*\)',
    }
    return patterns.get(language, patterns['python'])


def _find_fallback_body_end(
    original_code: str, body_start: int, indent: str, language: str
) -> int:
    if language in ('javascript', 'typescript', 'java', 'cpp', 'go'):
        return _find_brace_body_end(original_code, body_start)
    return _find_indent_body_end(original_code, body_start, indent)


def _find_brace_body_end(original_code: str, body_start: int) -> int:
    brace_count = 0
    in_body = False
    for i, char in enumerate(original_code[body_start:], start=body_start):
        if char == '{':
            brace_count += 1
            in_body = True
        elif char == '}':
            brace_count -= 1
            if in_body and brace_count == 0:
                return i + 1
    return body_start


def _find_indent_body_end(original_code: str, body_start: int, indent: str) -> int:
    lines = original_code[body_start:].split('\n')
    for i, line in enumerate(lines[1:], start=1):
        if (
            line.strip()
            and not line.startswith(indent)
            and not line.startswith(' ' * (len(indent) + 1))
        ):
            return body_start + sum(len(line_obj) + 1 for line_obj in lines[:i])
    return body_start


def _apply_fallback_edit(
    editor,
    file_path,
    function_name,
    new_body,
    original_code,
    language,
    validate,
    body_start,
    body_end,
) -> 'EditResult':
    try:
        new_code = original_code[:body_start] + new_body + original_code[body_end:]
        if validate:
            is_valid, error_msg = editor.validate_syntax(new_code, file_path, language)
            if not is_valid:
                return EditResult(
                    success=False,
                    message=f'Text fallback produced invalid syntax: {error_msg}',
                    original_code=original_code,
                )
        Path(file_path).write_text(new_code, encoding='utf-8')
        editor.tree_cache.pop(file_path, None)
        editor.file_cache.pop(file_path, None)
        lines_changed = new_body.count('\n') + 1
        return EditResult(
            success=True,
            message=f"✓ Edited function '{function_name}' in {language} (text fallback, {lines_changed} lines)",
            modified_code=new_code,
            lines_changed=lines_changed,
            original_code=original_code,
        )
    except Exception as e:
        logger.error(f'Text fallback failed: {e}')
        return EditResult(
            success=False,
            message=f'Text fallback error: {e}',
            original_code=original_code,
        )
