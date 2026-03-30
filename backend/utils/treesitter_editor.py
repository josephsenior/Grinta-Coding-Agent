"""Universal Tree-sitter-based editor supporting all major languages.

Language-agnostic editor using Tree-sitter for structure-aware editing.
Works with Python, JavaScript, TypeScript, Go, Rust, Java, C++, Ruby, PHP, and 40+ more.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from tree_sitter import (
        Language as LanguageType,
    )
    from tree_sitter import (
        Node as NodeType,
    )
    from tree_sitter import (
        Parser as ParserType,
    )
    from tree_sitter import (
        Tree as TreeType,
    )
else:  # pragma: no cover - runtime import with graceful fallback
    LanguageType = ParserType = NodeType = TreeType = Any

TREE_SITTER_AVAILABLE = False
_RuntimeLanguage: Any | None = None
_RuntimeParser: Any | None = None
_RuntimeNode: Any | None = None
_RuntimeTree: Any | None = None
_get_language: Callable[[str], Any] | None = None
_get_parser: Callable[[str], Any] | None = None
try:  # pragma: no cover - exercised in integration tests
    from tree_sitter import (  # type: ignore[no-redef]
        Language as _RuntimeLanguageModule,
    )
    from tree_sitter import (
        Node as _RuntimeNodeModule,
    )
    from tree_sitter import (
        Parser as _RuntimeParserModule,
    )
    from tree_sitter import (
        Tree as _RuntimeTreeModule,
    )
    from tree_sitter_language_pack import (  # type: ignore[no-redef]
        get_language as _runtime_get_language,
    )
    from tree_sitter_language_pack import (
        get_parser as _runtime_get_parser,
    )

    _RuntimeLanguage = _RuntimeLanguageModule
    _RuntimeParser = _RuntimeParserModule
    _RuntimeNode = _RuntimeNodeModule
    _RuntimeTree = _RuntimeTreeModule
    _get_language = cast(Callable[[str], Any], _runtime_get_language)
    _get_parser = cast(Callable[[str], Any], _runtime_get_parser)
    TREE_SITTER_AVAILABLE = True
except ImportError:  # pragma: no cover - handled in __init__
    TREE_SITTER_AVAILABLE = False

from backend.core.logger import app_logger as logger  # noqa: E402


@dataclass
class SymbolLocation:
    """Universal symbol location (works for any language)."""

    file_path: str
    line_start: int
    line_end: int
    byte_start: int
    byte_end: int
    node_type: str  # "function_definition", "class_declaration", etc.
    symbol_name: str
    parent_name: str | None = None


@dataclass
class EditResult:
    """Result of an edit operation."""

    success: bool
    message: str
    modified_code: str | None = None
    lines_changed: int = 0
    syntax_valid: bool = True
    original_code: str | None = None


# Language extension mapping - 45+ languages supported!
# Tree-sitter provides robust parsing for all these languages
LANGUAGE_EXTENSIONS = {
    # Core languages (most popular)
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".hxx": "cpp",
    # JVM languages
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".clj": "clojure",
    ".cljs": "clojure",
    ".cljc": "clojure",
    # .NET languages
    ".cs": "c_sharp",
    ".fs": "f_sharp",
    ".fsx": "f_sharp",
    # Scripting languages
    ".rb": "ruby",
    ".php": "php",
    ".pl": "perl",
    ".pm": "perl",
    ".lua": "lua",
    ".r": "r",
    ".R": "r",
    # Web languages
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "scss",
    ".less": "css",
    ".vue": "vue",
    ".svelte": "svelte",
    # Functional languages
    ".hs": "haskell",
    ".lhs": "haskell",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hrl": "erlang",
    ".ml": "ocaml",
    ".mli": "ocaml",
    ".elm": "elm",
    # Modern systems languages
    ".zig": "zig",
    ".nim": "nim",
    ".nims": "nim",
    ".v": "v",
    ".d": "d",
    # Mobile/App development
    ".swift": "swift",
    ".m": "objective_c",
    ".mm": "objective_c",
    ".dart": "dart",
    # Data/Config languages
    ".json": "json",
    ".json5": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    # Shell/Scripting
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".fish": "fish",
    # Query languages
    ".sql": "sql",
    ".graphql": "graphql",
    ".gql": "graphql",
    # Other
    ".proto": "proto",
    ".md": "markdown",
    ".markdown": "markdown",
    ".rst": "rst",
    ".tex": "latex",
    ".jl": "julia",
}


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
    - Zig, Nim, V, D

    **Mobile:**
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

    def __init__(self):
        """Initialize the universal editor."""
        if not TREE_SITTER_AVAILABLE:
            raise ImportError(
                "🚨 CRITICAL: Tree-sitter not available!\n\n"
                "Ultimate Editor requires Tree-sitter for structure-aware editing.\n"
                "This is App's competitive advantage - without it, only basic editing works.\n\n"
                "PRODUCTION DEPLOYMENT ERROR:\n"
                "  Tree-sitter should be a required dependency in pyproject.toml.\n"
                "  Check that your runtime environment has the latest dependencies installed.\n\n"
                "Quick fix (temporary): pip install tree-sitter tree-sitter-language-pack\n"
                "Permanent fix: Ensure pyproject.toml has tree_sitter in main dependencies (not optional)"
            )

        self.parsers: dict[str, ParserType] = {}
        self.tree_cache: dict[str, TreeType] = {}
        self.file_cache: dict[str, bytes] = {}

        logger.info("Universal Editor initialized with Tree-sitter support")

    def detect_language(self, file_path: str) -> str | None:
        """Detect programming language from file extension.

        Args:
            file_path: Path to the file

        Returns:
            Language name (e.g., "python", "javascript", "go") or None

        """
        ext = Path(file_path).suffix.lower()
        return LANGUAGE_EXTENSIONS.get(ext)

    def get_parser(self, language: str) -> ParserType | None:
        """Get or create a Tree-sitter parser for a language.

        Args:
            language: Language name (python, javascript, go, etc.)

        Returns:
            Parser instance or None if language not supported

        """
        if language in self.parsers:
            return self.parsers[language]

        if _get_language is None or _RuntimeParser is None:
            logger.error("Tree-sitter language pack is not available")
            return None

        try:
            lang = cast(Any, _get_language)(language)
            parser = _RuntimeParser(lang)
        except Exception as e:  # pragma: no cover - dependent on runtime env
            logger.error("Failed to create parser for %s: %s", language, e)
            return None

        self.parsers[language] = parser
        return parser

    def parse_file(
        self, file_path: str, use_cache: bool = True
    ) -> tuple[TreeType, bytes, str] | None:
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
                self.detect_language(file_path) or "",
            )

        try:
            # Detect language
            language = self.detect_language(file_path)
            if not language:
                logger.warning("Unknown file type: %s", file_path)
                return None

            # Get parser
            parser = self.get_parser(language)
            if not parser:
                return None

            # Read file as bytes (Tree-sitter requires bytes)
            with open(file_path, "rb") as f:
                file_bytes = f.read()

            # Parse
            tree = parser.parse(file_bytes)

            if use_cache:
                self.tree_cache[file_path] = tree
                self.file_cache[file_path] = file_bytes

            return tree, file_bytes, language

        except FileNotFoundError:
            logger.error("File not found: %s", file_path)
            return None
        except Exception as e:
            logger.error("Failed to parse %s: %s", file_path, e)
            return None

    def find_symbol(
        self, file_path: str, symbol_name: str, symbol_type: str | None = None
    ) -> SymbolLocation | None:
        """Find a symbol in any language file.

        Args:
            file_path: Path to the file
            symbol_name: Name of the symbol (supports "Class.method" for methods)
            symbol_type: Optional filter (e.g., "function", "class", "method")

        Returns:
            SymbolLocation if found, None otherwise

        """
        parse_result = self.parse_file(file_path, use_cache=True)
        if not parse_result:
            return None

        tree, file_bytes, language = parse_result

        # Handle dot notation for methods
        if "." in symbol_name:
            parts = symbol_name.split(".")
            if len(parts) == 2:
                return self._find_method_in_class(
                    tree, file_bytes, parts[0], parts[1], file_path, language
                )

        # Search for symbol
        return self._search_tree_for_symbol(
            tree, file_bytes, symbol_name, file_path, language, symbol_type
        )

    def edit_function(
        self, file_path: str, function_name: str, new_body: str, validate: bool = True
    ) -> EditResult:
        """Edit a function's body (works for ANY language).

        Args:
            file_path: Path to the file
            function_name: Name of the function
            new_body: New function body
            validate: Whether to validate after editing

        Returns:
            EditResult with success status

        """
        parse_result = self.parse_file(file_path, use_cache=False)
        if not parse_result:
            return EditResult(success=False, message=f"Failed to parse {file_path}")

        tree, file_bytes, language = parse_result
        original_code = file_bytes.decode("utf-8")

        # Find the function node
        func_node = self._find_function_node(tree, file_bytes, function_name, language)
        if not func_node:
            return EditResult(
                success=False,
                message=f"Function '{function_name}' not found in {file_path}",
            )

        # Extract function body node (language-specific)
        body_node = self._get_function_body_node(func_node, language)
        if not body_node:
            return EditResult(
                success=False,
                message=f"Could not locate function body for '{function_name}'",
            )

        # Expand body range to include comments/decorators between ':'
        # and the block node.  Tree-sitter places comments as siblings of
        # the block, so _get_function_body_node returns only the block.
        body_start = body_node.start_byte
        body_end = body_node.end_byte
        colon_end: int | None = None
        for child in func_node.children:
            if child.type == ":":
                colon_end = child.end_byte
                break
        if colon_end is not None:
            for child in func_node.children:
                if child.start_byte >= colon_end and child.type not in (
                    ":",
                    "NEWLINE",
                    "INDENT",
                    "DEDENT",
                    "newline",
                ):
                    body_start = min(body_start, child.start_byte)
                    body_end = max(body_end, child.end_byte)

        # Replace the body
        try:
            # Build new content using expanded body range
            from types import SimpleNamespace

            effective_body = SimpleNamespace(
                start_byte=body_start, end_byte=body_end
            )
            new_code = self._replace_node_content(
                original_code, cast(NodeType, effective_body), new_body, preserve_indentation=True
            )

            # Validate if requested
            if validate:
                validation_result = self._validate_syntax(new_code, file_path, language)
                if not validation_result[0]:
                    return EditResult(
                        success=False,
                        message=f"Syntax error after edit: {validation_result[1]}",
                        syntax_valid=False,
                        original_code=original_code,
                    )

            # Normalize \r\n → \n before writing in text mode to
            # prevent doubling (original_code from binary read has \r\n,
            # text-mode write would add another \r).
            new_code = new_code.replace("\r\n", "\n").replace("\r", "\n")

            # Write back
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_code)

            # Clear cache
            self.tree_cache.pop(file_path, None)
            self.file_cache.pop(file_path, None)

            lines_changed = new_body.count("\n") + 1

            return EditResult(
                success=True,
                message=f"✓ Edited function '{function_name}' in {language} ({lines_changed} lines)",
                modified_code=new_code,
                lines_changed=lines_changed,
                original_code=original_code,
            )

        except Exception as e:
            logger.error("Error editing function: %s", e)
            return EditResult(
                success=False, message=f"Error: {e}", original_code=original_code
            )

    def rename_symbol(self, file_path: str, old_name: str, new_name: str) -> EditResult:
        """Rename a symbol throughout a file (works for ANY language).

        Args:
            file_path: Path to the file
            old_name: Current symbol name
            new_name: New symbol name

        Returns:
            EditResult with success status

        """
        parse_result = self.parse_file(file_path, use_cache=False)
        if not parse_result:
            return EditResult(success=False, message=f"Failed to parse {file_path}")

        tree, file_bytes, language = parse_result
        original_code = file_bytes.decode("utf-8")

        # Find all occurrences of the symbol
        occurrences = self._find_all_symbol_occurrences(
            tree, file_bytes, old_name, language
        )

        if not occurrences:
            return EditResult(
                success=False, message=f"Symbol '{old_name}' not found in {file_path}"
            )

        # Replace all occurrences (from end to start to preserve positions)
        new_code = original_code
        for node in reversed(occurrences):
            start_byte = node.start_byte
            end_byte = node.end_byte
            new_code = new_code[:start_byte] + new_name + new_code[end_byte:]

        # Validate
        validation_result = self._validate_syntax(new_code, file_path, language)
        if not validation_result[0]:
            return EditResult(
                success=False,
                message=f"Rename created syntax error: {validation_result[1]}",
                syntax_valid=False,
                original_code=original_code,
            )

        # Normalize \r\n → \n before writing in text mode to
        # prevent doubling (original_code from binary read has \r\n,
        # text-mode write would add another \r).
        new_code = new_code.replace("\r\n", "\n").replace("\r", "\n")

        # Write back
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_code)

        self.tree_cache.pop(file_path, None)
        self.file_cache.pop(file_path, None)

        return EditResult(
            success=True,
            message=f"✓ Renamed '{old_name}' → '{new_name}' ({len(occurrences)} occurrences in {language})",
            modified_code=new_code,
            lines_changed=len(occurrences),
            original_code=original_code,
        )

    def _find_function_node(
        self, tree: TreeType, file_bytes: bytes, function_name: str, language: str
    ) -> NodeType | None:
        """Find function node (language-agnostic using Tree-sitter queries)."""
        root = tree.root_node

        # Language-specific node types for functions
        function_types = {
            "python": ["function_definition"],
            "javascript": ["function_declaration", "function", "method_definition"],
            "typescript": ["function_declaration", "function", "method_definition"],
            "go": ["function_declaration", "method_declaration"],
            "rust": ["function_item"],
            "java": ["method_declaration", "constructor_declaration"],
            "cpp": ["function_definition"],
            "c": ["function_definition"],
            "ruby": ["method", "singleton_method"],
            "php": ["function_definition", "method_declaration"],
        }

        target_types = function_types.get(
            language, ["function_definition", "function_declaration"]
        )

        # Recursive search
        return self._find_node_by_name(root, file_bytes, function_name, target_types)

    def _find_node_by_name(
        self, node: NodeType, file_bytes: bytes, target_name: str, node_types: list[str]
    ) -> NodeType | None:
        """Recursively find a node by name and type."""
        # Check if current node matches
        if node.type in node_types:
            # Try to extract name from node
            name_node = self._get_name_node(node)
            if name_node:
                name_text = file_bytes[
                    name_node.start_byte : name_node.end_byte
                ].decode("utf-8")
                if name_text == target_name:
                    return node

        # Recursively check children
        for child in node.children:
            result = self._find_node_by_name(child, file_bytes, target_name, node_types)
            if result:
                return result

        return None

    def _get_name_node(self, node: NodeType) -> NodeType | None:
        """Extract the name identifier node from a definition node."""
        # Common patterns across languages
        for child in node.children:
            if child.type in [
                "identifier",
                "name",
                "property_identifier",
                "type_identifier",
            ]:
                return child
            # For some languages, name is in a child node
            if child.type in ["function_declarator", "class_name"]:
                return self._get_name_node(child)

        return None

    def _find_method_in_class(
        self,
        tree: TreeType,
        file_bytes: bytes,
        class_name: str,
        method_name: str,
        file_path: str,
        language: str,
    ) -> SymbolLocation | None:
        """Find a method within a class (language-agnostic)."""
        root = tree.root_node

        # Language-specific class types
        class_types = {
            "python": ["class_definition"],
            "javascript": ["class_declaration"],
            "typescript": ["class_declaration"],
            "go": ["type_declaration"],  # structs with methods
            "rust": ["impl_item"],
            "java": ["class_declaration"],
            "cpp": ["class_specifier"],
            "c_sharp": ["class_declaration"],
            "ruby": ["class"],
            "php": ["class_declaration"],
        }

        target_class_types = class_types.get(
            language, ["class_declaration", "class_definition"]
        )

        # Find the class
        class_node = self._find_node_by_name(
            root, file_bytes, class_name, target_class_types
        )
        if not class_node:
            return None

        # Find method within class
        method_types = {
            "python": ["function_definition"],
            "javascript": ["method_definition"],
            "typescript": ["method_definition"],
            "java": ["method_declaration"],
            "cpp": ["function_definition"],
            "c_sharp": ["method_declaration"],
            "ruby": ["method"],
            "php": ["method_declaration"],
        }

        target_method_types = method_types.get(
            language, ["method_definition", "method_declaration"]
        )

        method_node = self._find_node_by_name(
            class_node, file_bytes, method_name, target_method_types
        )
        if not method_node:
            return None

        return SymbolLocation(
            file_path=file_path,
            line_start=method_node.start_point[0] + 1,  # Tree-sitter is 0-indexed
            line_end=method_node.end_point[0] + 1,
            byte_start=method_node.start_byte,
            byte_end=method_node.end_byte,
            node_type=method_node.type,
            symbol_name=method_name,
            parent_name=class_name,
        )

    def _search_tree_for_symbol(
        self,
        tree: TreeType,
        file_bytes: bytes,
        symbol_name: str,
        file_path: str,
        language: str,
        symbol_type: str | None = None,
    ) -> SymbolLocation | None:
        """Search tree for any symbol."""
        root = tree.root_node

        # Determine node types to search for
        if symbol_type == "function":
            node_types = [
                "function_definition",
                "function_declaration",
                "method_definition",
            ]
        elif symbol_type == "class":
            node_types = ["class_definition", "class_declaration"]
        else:
            # Search for both
            node_types = [
                "function_definition",
                "function_declaration",
                "method_definition",
                "class_definition",
                "class_declaration",
            ]

        # Find node
        found_node = self._find_node_by_name(root, file_bytes, symbol_name, node_types)
        if not found_node:
            return None

        return SymbolLocation(
            file_path=file_path,
            line_start=found_node.start_point[0] + 1,
            line_end=found_node.end_point[0] + 1,
            byte_start=found_node.start_byte,
            byte_end=found_node.end_byte,
            node_type=found_node.type,
            symbol_name=symbol_name,
            parent_name=None,
        )

    def _get_function_body_node(
        self, func_node: NodeType, language: str
    ) -> NodeType | None:
        """Get the body node of a function (language-specific)."""
        # Common body node names across languages
        body_types = ["block", "body", "compound_statement", "expression_statement"]

        for child in func_node.children:
            if child.type in body_types:
                return child

        return None

    def _replace_node_content(
        self,
        original_code: str,
        node: NodeType,
        new_content: str,
        preserve_indentation: bool = True,
    ) -> str:
        """Replace a node's content while preserving indentation."""
        start_byte = node.start_byte
        end_byte = node.end_byte

        # Get original indentation
        if preserve_indentation:
            start_line_begin = original_code.rfind("\n", 0, start_byte) + 1
            original_indent = original_code[start_line_begin:start_byte]

            # Apply indentation to new content
            new_content_lines = new_content.split("\n")
            indented_lines = [
                original_indent + line if i > 0 else line
                for i, line in enumerate(new_content_lines)
            ]
            new_content = "\n".join(indented_lines)

        # Replace
        return original_code[:start_byte] + new_content + original_code[end_byte:]

    def _validate_syntax(
        self, code: str, file_path: str, language: str
    ) -> tuple[bool, str]:
        """Validate syntax by parsing with Tree-sitter.

        Returns:
            Tuple of (is_valid, error_message)

        """
        try:
            parser = self.get_parser(language)
            if not parser:
                return True, "Parser not available, skipping validation"

            # Parse the new code
            tree = parser.parse(code.encode("utf-8"))

            # Check for errors (Tree-sitter marks error nodes)
            if self._has_syntax_errors(tree.root_node):
                return False, "Code contains syntax errors"

            return True, "Syntax valid"

        except Exception as e:
            logger.warning("Validation failed: %s", e)
            return True, f"Validation skipped: {e}"

    def _has_syntax_errors(self, node: NodeType) -> bool:
        """Check if tree contains ERROR or MISSING nodes."""
        if node.type == "ERROR" or node.is_missing:
            return True

        for child in node.children:
            if self._has_syntax_errors(child):
                return True

        return False

    def _find_all_symbol_occurrences(
        self, tree: TreeType, file_bytes: bytes, symbol_name: str, language: str
    ) -> list[NodeType]:
        """Find all nodes that match the symbol name."""
        occurrences = []

        def visit(node: NodeType):
            """Recursively visit AST nodes to find symbol occurrences.

            Args:
                node: Tree-sitter node to visit

            """
            # Check if this is an identifier matching our symbol
            if node.type in ["identifier", "name", "property_identifier"]:
                node_text = file_bytes[node.start_byte : node.end_byte].decode("utf-8")
                if node_text == symbol_name:
                    occurrences.append(node)

            # Recurse
            for child in node.children:
                visit(child)

        visit(tree.root_node)
        return occurrences

    def get_supported_languages(self) -> list[str]:
        """Get list of all supported languages."""
        return list(set(LANGUAGE_EXTENSIONS.values()))

    def clear_cache(self):
        """Clear all caches."""
        self.tree_cache.clear()
        self.file_cache.clear()
