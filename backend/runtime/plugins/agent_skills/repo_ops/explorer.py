"""Code exploration and search functionality.

Provides functions for exploring code structure, searching snippets, and
retrieving entity contents. Production-grade implementation.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from backend.core.logger import forge_logger as logger
from backend.memory.graph_store import GraphMemoryStore
from backend.memory.graph_rag import GraphRAG
from backend.memory.vector_store import EnhancedVectorStore

# Global graph store instance (lazy initialization)
_graph_store: GraphMemoryStore | None = None
_graph_rag: GraphRAG | None = None


def _get_graph_store(workspace_root: str = "/workspace") -> tuple[GraphMemoryStore, GraphRAG | None]:
    """Get or create the global graph store and GraphRAG."""
    global _graph_store, _graph_rag
    if _graph_store is None:
        _graph_store = GraphMemoryStore()
        # We don't strictly need a real vector store for just graph traversal,
        # but GraphRAG requires it. We can pass a dummy or initialize a real one.
        # For now, we'll initialize a real one if needed, or just use GraphRAG for indexing.
        vector_store = EnhancedVectorStore()
        _graph_rag = GraphRAG(vector_store, _graph_store)
    return _graph_store, _graph_rag


def explore_tree_structure(
    start_entities: list[str],
    direction: str = "downstream",
    traversal_depth: int = 2,
    entity_type_filter: list[str] | None = None,
    dependency_type_filter: list[str] | None = None,
    workspace_root: str = "/workspace",
) -> dict[str, Any]:
    """Explore code structure starting from given entities.

    Traverses the code graph to find related entities through dependencies.

    Args:
        start_entities: List of entity IDs to start from (e.g., ["src/api.py:UserAPI"])
        direction: "upstream", "downstream", or "both"
        traversal_depth: Maximum depth to traverse (-1 for unlimited)
        entity_type_filter: Filter by entity types (e.g., ["class", "function"])
        dependency_type_filter: Filter by dependency types (e.g., ["imports", "invokes"])
        workspace_root: Root directory of the workspace

    Returns:
        Dictionary with explored entities and dependencies
    """
    graph_store, graph_rag = _get_graph_store(workspace_root)

    # Index files if needed
    for entity_id in start_entities:
        if ":" in entity_id:
            file_path = entity_id.split(":")[0]
            full_path = os.path.join(workspace_root, file_path)
            if os.path.exists(full_path):
                with open(full_path, "r", encoding="utf-8") as f:
                    content = f.read()
                if graph_rag is not None:
                    graph_rag.index_code_file(file_path, content)

    # Collect results
    explored_entities: dict[str, dict] = {}
    explored_dependencies: list[dict] = []

    def traverse(entity_id: str, depth: int, visited: set[str]) -> None:
        """Recursively traverse the graph."""
        if entity_id in visited:
            return
        if traversal_depth >= 0 and depth > traversal_depth:
            return

        visited.add(entity_id)

        # Get entity
        # In GraphMemoryStore, the node ID might be just the symbol name or file path.
        # We need to handle the "file:symbol" format from start_entities.
        node_id = entity_id
        if ":" in entity_id:
            node_id = entity_id.split(":")[1]
            
        node = graph_store.get_node(node_id)
        if not node:
            # Try to resolve as file path
            if os.path.exists(os.path.join(workspace_root, entity_id)):
                with open(os.path.join(workspace_root, entity_id), "r", encoding="utf-8") as f:
                    content = f.read()
                if graph_rag is not None:
                    graph_rag.index_code_file(entity_id, content)
                node = graph_store.get_node(entity_id)

        if not node:
            return

        # Apply entity type filter
        if entity_type_filter and node.get("type") not in entity_type_filter:
            return

        explored_entities[node_id] = {
            "entity_id": node_id,
            "entity_type": node.get("type"),
            "file_path": node.get("file_path"),
            "name": node_id,
            "line_start": node.get("line_start"),
            "line_end": node.get("line_end"),
            "parent_id": node.get("parent_id"),
        }

        # Get dependencies
        # GraphMemoryStore uses get_neighbors, which returns outgoing edges.
        # For upstream, we need predecessors.
        deps = []
        if direction in ("downstream", "both"):
            for neighbor in graph_store.get_neighbors(node_id):
                if dependency_type_filter and neighbor["relationship"] not in dependency_type_filter:
                    continue
                deps.append({
                    "from_entity": node_id,
                    "to_entity": neighbor["id"],
                    "dependency_type": neighbor["relationship"],
                })
        
        if direction in ("upstream", "both"):
            if node_id in graph_store.graph:
                for pred in graph_store.graph.predecessors(node_id):
                    edge_data = graph_store.graph.get_edge_data(pred, node_id)
                    for data in edge_data.values():
                        if dependency_type_filter and data.get("type") not in dependency_type_filter:
                            continue
                        deps.append({
                            "from_entity": pred,
                            "to_entity": node_id,
                            "dependency_type": data.get("type"),
                        })

        explored_dependencies.extend(deps)

        # Traverse dependencies
        for dep in deps:
            next_entity_id = (
                dep["to_entity"] if direction == "downstream" else dep["from_entity"]
            )
            if direction == "both":
                next_entity_id = (
                    dep["to_entity"] if dep["from_entity"] == node_id else dep["from_entity"]
                )
            traverse(next_entity_id, depth + 1, visited)

    # Start traversal from all start entities
    visited: set[str] = set()
    for entity_id in start_entities:
        traverse(entity_id, 0, visited)

    # Format results
    return {
        "entities": list(explored_entities.values()),
        "dependencies": explored_dependencies,
    }


def get_entity_contents(
    entity_names: list[str], workspace_root: str = "/workspace"
) -> dict[str, Any]:
    """Get the complete content of specified entities.

    Args:
        entity_names: List of entity identifiers (e.g., ["src/api.py:UserAPI.create_user"])
        workspace_root: Root directory of the workspace

    Returns:
        Dictionary mapping entity IDs to their content
    """
    graph_store, graph_rag = _get_graph_store(workspace_root)
    results: dict[str, str] = {}

    for entity_name in entity_names:
        # Parse entity identifier
        if ":" in entity_name:
            file_path, symbol_path = entity_name.split(":", 1)
        else:
            file_path = entity_name
            symbol_path = None

        full_path = Path(workspace_root) / file_path.lstrip("/")

        if not full_path.exists():
            results[entity_name] = f"Error: File not found: {file_path}"
            continue

        try:
            with open(full_path, encoding="utf-8") as f:
                content = f.read()

            # If no symbol specified, return entire file
            if not symbol_path:
                results[entity_name] = content
                continue

            # Find specific symbol
            if graph_rag is not None:
                graph_rag.index_code_file(file_path, content)
            
            node = graph_store.get_node(symbol_path)
            if node and node.get("line_start") and node.get("line_end"):
                lines = content.splitlines()
                entity_content = "\n".join(
                    lines[node["line_start"] - 1 : node["line_end"]]
                )
                results[entity_name] = entity_content
            else:
                # Fallback: try to find by name pattern
                results[entity_name] = _extract_symbol_by_name(
                    content, symbol_path, file_path
                )

        except Exception as e:
            results[entity_name] = f"Error reading {entity_name}: {e}"

    return {"entities": results}


def _extract_symbol_by_name(content: str, symbol_path: str, file_path: str) -> str:
    """Extract symbol content by name pattern matching (fallback)."""
    # Simple pattern matching for common cases
    lines = content.splitlines()

    # Try to find class or function definition
    pattern = rf"(class|def)\s+{re.escape(symbol_path.split('.')[-1])}"
    for i, line in enumerate(lines):
        if re.match(pattern, line.strip()):
            # Find the end of the definition (simple heuristic)
            start = i
            indent = len(line) - len(line.lstrip())
            end = start + 1

            for j in range(i + 1, len(lines)):
                if (
                    lines[j].strip()
                    and len(lines[j]) - len(lines[j].lstrip()) <= indent
                ):
                    if not lines[j].strip().startswith(("#", '"', "'")):
                        break
                end = j + 1

            return "\n".join(lines[start:end])

    return f"Symbol '{symbol_path}' not found in {file_path}"


def search_code_snippets(
    search_terms: list[str] | None = None,
    line_nums: list[int] | None = None,
    file_path_or_pattern: str = "**/*.py",
    workspace_root: str = "/workspace",
) -> dict[str, Any]:
    """Search for code snippets matching terms or around line numbers.

    Args:
        search_terms: List of search terms/keywords
        line_nums: List of line numbers to get context around
        file_path_or_pattern: File path or glob pattern to search in
        workspace_root: Root directory of the workspace

    Returns:
        Dictionary with matching code snippets
    """
    workspace = Path(workspace_root)
    results: list[dict[str, Any]] = []

    # Resolve file pattern
    if os.path.isabs(file_path_or_pattern):
        search_files = [Path(file_path_or_pattern)]
    else:
        search_files = list(workspace.glob(file_path_or_pattern))

    for file_path in search_files:
        if not file_path.is_file():
            continue

        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()
            lines = content.splitlines()

            # Search by terms
            if search_terms:
                for term in search_terms:
                    matches = _search_in_content(content, lines, term, str(file_path))
                    results.extend(matches)

            # Search by line numbers
            if line_nums:
                for line_num in line_nums:
                    if 1 <= line_num <= len(lines):
                        context = _get_line_context(lines, line_num, context_lines=5)
                        results.append(
                            {
                                "file_path": str(file_path.relative_to(workspace)),
                                "line_number": line_num,
                                "content": context,
                                "match_type": "line_number",
                            }
                        )

        except Exception as e:
            logger.debug("Error searching in %s: %s", file_path, e)

    return {"snippets": results}


def _search_in_content(
    content: str, lines: list[str], term: str, file_path: str
) -> list[dict[str, Any]]:
    """Search for a term in file content."""
    results: list[dict[str, Any]] = []
    term_lower = term.lower()

    for i, line in enumerate(lines, 1):
        if term_lower in line.lower():
            context = _get_line_context(lines, i, context_lines=3)
            results.append(
                {
                    "file_path": file_path,
                    "line_number": i,
                    "content": context,
                    "match_type": "term",
                    "search_term": term,
                }
            )

    return results


def _get_line_context(lines: list[str], line_num: int, context_lines: int = 5) -> str:
    """Get context around a line number."""
    start = max(0, line_num - context_lines - 1)
    end = min(len(lines), line_num + context_lines)
    context_lines_list = lines[start:end]

    # Add line numbers
    numbered = [
        f"{i + start + 1:4d} | {line}" for i, line in enumerate(context_lines_list)
    ]
    return "\n".join(numbered)
