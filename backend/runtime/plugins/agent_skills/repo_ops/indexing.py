"""Production-grade code indexing and exploration system.

Provides advanced code structure analysis, dependency graph building, and
entity search using Tree-sitter. Designed for production agent environments.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.core.logger import forge_logger as logger

# Type imports for type checking only
if TYPE_CHECKING:
    from tree_sitter import Node, Parser, Tree
else:
    # Runtime type aliases - will be set to actual types if available
    Node = Any
    Parser = Any
    Tree = Any

# Try to import Tree-sitter (optional but recommended)
TREE_SITTER_AVAILABLE = False
_get_language_func: Callable[[str], Any] | None = None
_get_parser_func: Callable[[str], Any] | None = None

try:
    from tree_sitter import Node as _Node
    from tree_sitter import Parser as _Parser
    from tree_sitter import Tree as _Tree
    from tree_sitter_language_pack import get_language as _get_language
    from tree_sitter_language_pack import get_parser as _get_parser

    # Update runtime type aliases with actual types
    if not TYPE_CHECKING:
        Node = _Node
        Parser = _Parser
        Tree = _Tree
    # These functions accept specific literal language strings, but we use runtime strings
    # This is safe - the functions handle invalid languages gracefully
    _get_language_func = _get_language  # type: ignore[assignment]
    _get_parser_func = _get_parser  # type: ignore[assignment]
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False
    logger.debug(
        "Tree-sitter not available. Code indexing will use basic file-based indexing."
    )


@dataclass
class CodeEntity:
    """Represents a code entity (function, class, file, directory)."""

    entity_id: str  # e.g., "src/api.py:UserAPI.create_user"
    entity_type: str  # "function", "class", "file", "directory"
    file_path: str
    name: str
    line_start: int
    line_end: int
    parent_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Dependency:
    """Represents a dependency relationship between entities."""

    from_entity: str
    to_entity: str
    dependency_type: str  # "imports", "invokes", "inherits", "contains"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CodeGraph:
    """Represents the code structure as a graph of entities and dependencies."""

    entities: dict[str, CodeEntity] = field(default_factory=dict)
    dependencies: list[Dependency] = field(default_factory=list)
    file_index: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))

    def add_entity(self, entity: CodeEntity) -> None:
        """Add an entity to the graph."""
        self.entities[entity.entity_id] = entity
        self.file_index[entity.file_path].append(entity.entity_id)

    def add_dependency(self, dependency: Dependency) -> None:
        """Add a dependency to the graph."""
        self.dependencies.append(dependency)

    def get_entities_in_file(self, file_path: str) -> list[CodeEntity]:
        """Get all entities in a file."""
        entity_ids = self.file_index.get(file_path, [])
        return [self.entities[eid] for eid in entity_ids if eid in self.entities]

    def get_dependencies(
        self,
        entity_id: str,
        direction: str = "downstream",  # "upstream", "downstream", "both"
        dependency_types: list[str] | None = None,
    ) -> list[Dependency]:
        """Get dependencies for an entity."""
        deps = []
        for dep in self.dependencies:
            if dependency_types and dep.dependency_type not in dependency_types:
                continue

            if self._is_dependency_in_direction(dep, entity_id, direction):
                deps.append(dep)

        return deps

    def _is_dependency_in_direction(
        self, dep: Dependency, entity_id: str, direction: str
    ) -> bool:
        """Check if a dependency matches the specified direction for an entity."""
        if direction == "downstream":
            return dep.from_entity == entity_id
        if direction == "upstream":
            return dep.to_entity == entity_id
        if direction == "both":
            return dep.from_entity == entity_id or dep.to_entity == entity_id
        return False


class CodeIndexer:
    """Production-grade code indexer using Tree-sitter.

    Builds comprehensive code graphs with entity and dependency information.
    Supports 40+ programming languages through Tree-sitter.
    """

    def __init__(
        self, workspace_root: str = "/workspace", enable_incremental: bool = True
    ):
        """Initialize the code indexer.

        Args:
            workspace_root: Root directory of the workspace to index
            enable_incremental: Enable incremental indexing (skip unchanged files)
        """
        self.workspace_root = Path(workspace_root)
        self.parsers: dict[str, Parser] = {}
        self.graph: CodeGraph = CodeGraph()
        self.enable_incremental = enable_incremental
        # Track file modification times for incremental indexing
        self.file_timestamps: dict[str, float] = {}
        # Track indexed entities per file for cleanup
        self.file_entities: dict[str, list[str]] = defaultdict(list)

        if not TREE_SITTER_AVAILABLE:
            logger.warning(
                "Tree-sitter not available. Code indexing will use basic file-based indexing."
            )

    def _get_parser(self, language: str) -> Parser | None:
        """Get or create a Tree-sitter parser for a language."""
        if language in self.parsers:
            return self.parsers[language]

        if (
            not TREE_SITTER_AVAILABLE
            or _get_language_func is None
            or _get_parser_func is None
        ):
            return None

        try:
            # These functions expect specific literal types, but we pass runtime strings
            # This is safe at runtime - the functions handle invalid languages gracefully
            _get_language_func(language)  # type: ignore[arg-type]
            parser = _get_parser_func(language)  # type: ignore[arg-type]
            self.parsers[language] = parser
            return parser
        except Exception as e:
            logger.debug("Failed to create parser for %s: %s", language, e)
            return None

    def _detect_language(self, file_path: str) -> str | None:
        """Detect programming language from file extension."""
        ext = Path(file_path).suffix.lower()
        language_map = {
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
            ".rb": "ruby",
            ".php": "php",
            ".swift": "swift",
            ".kt": "kotlin",
            ".scala": "scala",
            ".elixir": "elixir",
            ".ex": "elixir",
            ".exs": "elixir",
        }
        return language_map.get(ext)

    def index_file(self, file_path: str, force: bool = False) -> None:
        """Index a single file and extract entities.

        Args:
            file_path: Path to file to index (relative to workspace_root)
            force: Force re-indexing even if file hasn't changed
        """
        full_path = self.workspace_root / file_path.lstrip("/")
        if not full_path.exists() or not full_path.is_file():
            # File was deleted, remove from index
            if file_path in self.file_entities:
                self._remove_file_from_index(file_path)
            return

        # Incremental indexing: check if file needs re-indexing
        if self._check_incremental_skip(full_path, file_path, force):
            return

        # Remove old entities for this file before re-indexing
        if file_path in self.file_entities:
            self._remove_file_from_index(file_path)

        language = self._detect_language(str(full_path))
        if not language:
            self._index_as_generic_file(full_path, file_path)
            return

        if TREE_SITTER_AVAILABLE:
            self._index_file_with_tree_sitter(full_path, file_path, language)
        else:
            self._index_as_generic_file(full_path, file_path)

        # Update timestamp after successful indexing
        self._update_file_timestamp(full_path, file_path)

    def _check_incremental_skip(
        self, full_path: Path, file_path: str, force: bool
    ) -> bool:
        """Check if file indexing can be skipped due to incremental indexing."""
        if not self.enable_incremental or force:
            return False

        try:
            current_mtime = full_path.stat().st_mtime
            if file_path in self.file_timestamps:
                if current_mtime <= self.file_timestamps[file_path]:
                    logger.debug("Skipping unchanged file: %s", file_path)
                    return True
        except OSError:
            pass
        return False

    def _index_as_generic_file(self, full_path: Path, file_path: str) -> None:
        """Index as a generic file without language-specific parsing."""
        entity = CodeEntity(
            entity_id=file_path,
            entity_type="file",
            file_path=file_path,
            name=Path(file_path).name,
            line_start=1,
            line_end=1,
        )
        self.graph.add_entity(entity)
        self.file_entities[file_path].append(entity.entity_id)
        self._update_file_timestamp(full_path, file_path)

    def _update_file_timestamp(self, full_path: Path, file_path: str) -> None:
        """Update the stored timestamp for a file."""
        try:
            self.file_timestamps[file_path] = full_path.stat().st_mtime
        except OSError:
            pass

    def _remove_file_from_index(self, file_path: str) -> None:
        """Remove all entities and dependencies for a file from the index."""
        entity_ids = self.file_entities.get(file_path, [])
        for entity_id in entity_ids:
            # Remove entity
            self.graph.entities.pop(entity_id, None)
            # Remove dependencies involving this entity
            self.graph.dependencies = [
                dep
                for dep in self.graph.dependencies
                if dep.from_entity != entity_id and dep.to_entity != entity_id
            ]
        # Clear file index
        self.graph.file_index.pop(file_path, None)
        self.file_entities.pop(file_path, None)
        self.file_timestamps.pop(file_path, None)

    def index_directory(
        self,
        directory: str = "",
        pattern: str = "**/*",
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> None:
        """Index all files in a directory.

        Args:
            directory: Directory to index (relative to workspace_root, empty for root)
            pattern: Glob pattern for files to index (default: all files)
            progress_callback: Optional callback(current, total) for progress reporting
        """
        search_path = self.workspace_root / directory.lstrip("/")
        if not search_path.exists():
            logger.warning("Directory not found: %s", search_path)
            return

        # Find all files matching pattern
        files = list(search_path.glob(pattern))
        files = [f for f in files if f.is_file()]
        total = len(files)

        logger.info("Indexing %s files in %s...", total, directory or "workspace root")

        for i, file_path in enumerate(files):
            # Convert to relative path
            try:
                rel_path = str(file_path.relative_to(self.workspace_root))
                self.index_file(rel_path)
            except Exception as e:
                logger.debug("Failed to index %s: %s", file_path, e)

            if progress_callback:
                progress_callback(i + 1, total)

    def _index_file_with_tree_sitter(
        self, full_path: Path, file_path: str, language: str
    ) -> None:
        """Index a file using Tree-sitter parsing."""
        parser = self._get_parser(language)
        if not parser:
            return

        try:
            with open(full_path, "rb") as f:
                content = f.read()

            tree = parser.parse(content)
            text = content.decode("utf-8", errors="ignore")

            # Add file entity
            file_entity = CodeEntity(
                entity_id=file_path,
                entity_type="file",
                file_path=file_path,
                name=Path(file_path).name,
                line_start=1,
                line_end=len(text.splitlines()),
            )
            self.graph.add_entity(file_entity)
            self.file_entities[file_path].append(file_entity.entity_id)

            # Extract entities based on language
            if language == "python":
                self._extract_python_entities(tree, text, file_path)
            elif language in ("javascript", "typescript", "tsx"):
                self._extract_js_entities(tree, text, file_path)
            # Add more language-specific extractors as needed

        except Exception as e:
            logger.debug("Failed to index %s: %s", file_path, e)

    def _extract_python_entities(self, tree: Any, text: str, file_path: str) -> None:
        """Extract Python entities (classes, functions) and imports from AST."""
        if not TREE_SITTER_AVAILABLE:
            return

        imports: list[str] = []
        import_dependencies: list[tuple[str, str]] = []  # (from_entity, to_module)

        def traverse(node: Any, parent_id: str | None = None) -> None:
            node_type = node.type
            text[node.start_byte : node.end_byte]

            # Track imports for dependency analysis
            if node_type == "import_statement":
                self._handle_python_import(
                    node, text, file_path, imports, import_dependencies
                )
            elif node_type == "import_from_statement":
                self._handle_python_import_from(
                    node, text, file_path, imports, import_dependencies
                )
            # Extract class definitions
            elif node_type == "class_definition":
                self._handle_python_class(node, text, file_path, parent_id, traverse)
            # Extract function definitions
            elif node_type == "function_definition":
                self._handle_python_function(node, text, file_path, parent_id)
            else:
                # Traverse children
                for child in node.children:
                    traverse(child, parent_id)

        traverse(tree.root_node, file_path)

        # Store imports in file entity metadata and create import dependencies
        if imports:
            file_entity = self.graph.entities.get(file_path)
            if file_entity:
                file_entity.metadata["imports"] = imports

            # Create dependency edges for imports
            for from_file, to_module in import_dependencies:
                # Try to resolve module to file path (simplified)
                module_file_path = self._resolve_module_to_file(to_module, file_path)
                if module_file_path:
                    self.graph.add_dependency(
                        Dependency(
                            from_entity=file_path,
                            to_entity=module_file_path,
                            dependency_type="imports",
                            metadata={"module": to_module},
                        )
                    )

    def _resolve_module_to_file(self, module_name: str, from_file: str) -> str | None:
        """Resolve a module name to a file path (simplified implementation).

        Args:
            module_name: Module name (e.g., "utils.helpers")
            from_file: File making the import (for relative resolution)

        Returns:
            Resolved file path or None if not found
        """
        # Convert module name to potential file paths
        module_parts = module_name.split(".")
        potential_paths = [
            "/".join(module_parts) + ".py",
            "/".join(module_parts[:-1]) + f"/{module_parts[-1]}.py",
        ]

        # Check relative to importing file's directory
        from_dir = str(Path(from_file).parent)
        for path in potential_paths:
            full_path = self.workspace_root / from_dir / path
            if full_path.exists():
                return str(full_path.relative_to(self.workspace_root))

        # Check from workspace root
        for path in potential_paths:
            full_path = self.workspace_root / path
            if full_path.exists():
                return str(full_path.relative_to(self.workspace_root))

        return None

    def _handle_python_import(
        self, node: Any, text: str, file_path: str, imports: list[str], deps: list
    ) -> None:
        """Handle Python import statement."""
        module_node = node.child_by_field_name("module_name")
        if module_node:
            module_name = text[module_node.start_byte : module_node.end_byte]
            imports.append(f"import {module_name}")
            deps.append((file_path, module_name))

    def _handle_python_import_from(
        self, node: Any, text: str, file_path: str, imports: list[str], deps: list
    ) -> None:
        """Handle Python import-from statement."""
        module_node = node.child_by_field_name("module_name")
        if module_node:
            module_name = text[module_node.start_byte : module_node.end_byte]
            imports.append(f"from {module_name} import ...")
            deps.append((file_path, module_name))

    def _handle_python_class(
        self,
        node: Any,
        text: str,
        file_path: str,
        parent_id: str | None,
        traverse_func: Callable,
    ) -> None:
        """Handle Python class definition."""
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        name = text[name_node.start_byte : name_node.end_byte]
        entity_id = f"{file_path}:{name}"
        entity = CodeEntity(
            entity_id=entity_id,
            entity_type="class",
            file_path=file_path,
            name=name,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            parent_id=parent_id,
        )
        self.graph.add_entity(entity)
        self.file_entities[file_path].append(entity_id)

        if parent_id:
            self.graph.add_dependency(
                Dependency(
                    from_entity=parent_id,
                    to_entity=entity_id,
                    dependency_type="contains",
                )
            )

        # Traverse children
        for child in node.children:
            traverse_func(child, entity_id)

    def _handle_python_function(
        self, node: Any, text: str, file_path: str, parent_id: str | None
    ) -> None:
        """Handle Python function definition."""
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        name = text[name_node.start_byte : name_node.end_byte]
        entity_id = (
            f"{file_path}:{name}"
            if not parent_id
            else f"{file_path}:{parent_id.split(':')[-1]}.{name}"
        )
        entity = CodeEntity(
            entity_id=entity_id,
            entity_type="function",
            file_path=file_path,
            name=name,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            parent_id=parent_id,
        )
        self.graph.add_entity(entity)
        self.file_entities[file_path].append(entity_id)

        if parent_id:
            self.graph.add_dependency(
                Dependency(
                    from_entity=parent_id,
                    to_entity=entity_id,
                    dependency_type="contains",
                )
            )

    def _extract_js_entities(self, tree: Any, text: str, file_path: str) -> None:
        """Extract JavaScript/TypeScript entities from AST."""
        if not TREE_SITTER_AVAILABLE:
            return

        def traverse(node: Any, parent_id: str | None = None) -> None:
            node_type = node.type

            # Extract class declarations
            if node_type == "class_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = text[name_node.start_byte : name_node.end_byte]
                    entity_id = f"{file_path}:{name}"
                    entity = CodeEntity(
                        entity_id=entity_id,
                        entity_type="class",
                        file_path=file_path,
                        name=name,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        parent_id=parent_id,
                    )
                    self.graph.add_entity(entity)
                    self.file_entities[file_path].append(entity_id)

                    if parent_id:
                        self.graph.add_dependency(
                            Dependency(
                                from_entity=parent_id,
                                to_entity=entity_id,
                                dependency_type="contains",
                            )
                        )

                    for child in node.children:
                        traverse(child, entity_id)

            # Extract function declarations
            elif node_type in ("function_declaration", "method_definition"):
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = text[name_node.start_byte : name_node.end_byte]
                    entity_id = (
                        f"{file_path}:{name}"
                        if not parent_id
                        else f"{file_path}:{parent_id.split(':')[-1]}.{name}"
                    )
                    entity = CodeEntity(
                        entity_id=entity_id,
                        entity_type="function",
                        file_path=file_path,
                        name=name,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        parent_id=parent_id,
                    )
                    self.graph.add_entity(entity)
                    self.file_entities[file_path].append(entity_id)

                    if parent_id:
                        self.graph.add_dependency(
                            Dependency(
                                from_entity=parent_id,
                                to_entity=entity_id,
                                dependency_type="contains",
                            )
                        )

            else:
                for child in node.children:
                    traverse(child, parent_id)

        traverse(tree.root_node, file_path)
