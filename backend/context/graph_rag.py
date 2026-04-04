"""GraphRAG: Retrieval Augmented Generation using Knowledge Graphs.

Combines semantic search (Vector Store) with structural traversal (Graph Store)
to provide rich, context-aware retrieval.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from backend.context.graph_store import EdgeType, GraphMemoryStore, NodeType
from backend.context.vector_store import EnhancedVectorStore

logger = logging.getLogger(__name__)

# TreeSitter is optional; fall back gracefully if unavailable
_TREESITTER_AVAILABLE = False
from backend.utils.treesitter_editor import (  # noqa: E402
    TREE_SITTER_AVAILABLE,
    TreeSitterEditor,
)

_TREESITTER_AVAILABLE = TREE_SITTER_AVAILABLE


class GraphRAG:
    """Graph-based Retrieval Augmented Generation system."""

    def __init__(
        self,
        vector_store: EnhancedVectorStore,
        graph_store: GraphMemoryStore,
    ):
        self.vector_store = vector_store
        self.graph_store = graph_store

    def retrieve(
        self,
        query: str,
        max_results: int = 5,
        graph_depth: int = 1,
    ) -> dict[str, Any]:
        """Retrieve context using both vector search and graph expansion.

        Process:
        1. Semantic Search: Find relevant nodes using vector store.
        2. Graph Expansion: Find neighbors of these nodes in the graph.
        3. Context Assembly: Combine semantic matches + structural context.
        """
        # 1. Semantic Search
        vector_results = self.vector_store.search(query, k=max_results)

        # Extract node IDs from vector results
        # Assuming 'step_id' or specific metadata maps to graph node IDs
        seed_node_ids = []
        semantic_context = []

        for result in vector_results:
            semantic_context.append(result)
            # Try to find a graph node ID in metadata
            # This mapping strategy depends on how we index data
            # For now, let's assume 'file_path' or 'function_name' might be keys
            metadata = result.get('metadata', {})
            if 'file_path' in metadata:
                seed_node_ids.append(metadata['file_path'])
            if 'function_name' in metadata:
                seed_node_ids.append(metadata['function_name'])

        # 2. Graph Expansion
        graph_context = []
        if seed_node_ids:
            # Get subgraph around seed nodes
            subgraph = self.graph_store.get_subgraph(seed_node_ids, depth=graph_depth)

            # Convert subgraph to readable context
            for u, v, data in subgraph.edges(data=True):
                edge_type = data.get('type', 'related_to')
                graph_context.append(f'{u} {edge_type} {v}')

        return {
            'semantic_results': semantic_context,
            'graph_context': graph_context,
            'seed_nodes': seed_node_ids,
            'stats': {
                'vector_hits': len(vector_results),
                'graph_nodes': len(seed_node_ids),
                'graph_edges': len(graph_context),
            },
        }

    def index_code_file(self, file_path: str, content: str) -> None:
        """Index a code file into both vector and graph stores.

        Uses TreeSitter (when available) to extract real AST relationships:
        - Functions and classes as FUNCTION/CLASS nodes
        - DEFINES edges from file → function/class symbols
        - IMPORTS edges from file → imported modules
        - METHOD_OF edges from methods to their parent class

        Falls back to naive import-line regex when TreeSitter is unavailable
        or the file extension is unsupported.
        """
        # 1. Always create the file node
        self.graph_store.add_node(file_path, NodeType.FILE)

        # 2. Attempt real AST indexing via TreeSitter
        if _TREESITTER_AVAILABLE:
            try:
                self._index_with_treesitter(file_path, content)
                return
            except Exception as exc:
                logger.debug(
                    'TreeSitter indexing failed for %s: %s — falling back to naive parser',
                    file_path,
                    exc,
                )

        # 3. Fallback: naive import-line regex (original behaviour)
        self._index_naive(file_path, content)

    def _index_with_treesitter(self, file_path: str, content: str) -> None:
        """Use TreeSitterEditor to extract function/class/import relationships."""
        editor = TreeSitterEditor()
        parse_result = editor.parse_file(file_path, use_cache=False)
        if parse_result is None:
            # File type not supported by TreeSitter — fall through to naive
            raise ValueError(
                f'TreeSitter cannot parse {os.path.splitext(file_path)[1]}'
            )

        tree, file_bytes, language = parse_result

        # Walk the top-level tree for definitions
        classes_found: list[str] = []

        def _node_text(node) -> str:  # type: ignore[return]
            return file_bytes[node.start_byte : node.end_byte].decode(
                'utf-8', errors='replace'
            )

        def _walk(node, parent_class: str | None = None) -> None:
            nt = node.type

            # ----------------------------------------------------------------
            # Function / method definitions
            # ----------------------------------------------------------------
            if nt in (
                'function_definition',  # Python, Ruby
                'function_declaration',  # JS/TS/Go/C/C++/Java
                'method_definition',  # JS/TS
                'method_declaration',  # Java, C#, Go
                'func_literal',  # Go
                'arrow_function',  # JS/TS
                'function_item',  # Rust
            ):
                name_node = editor._get_name_node(node)
                if name_node:
                    sym = _node_text(name_node)
                    line_start = node.start_point[0] + 1
                    line_end = node.end_point[0] + 1
                    if parent_class:
                        qual = f'{parent_class}.{sym}'
                        self.graph_store.add_node(
                            qual,
                            NodeType.FUNCTION,
                            file_path=file_path,
                            line_start=line_start,
                            line_end=line_end,
                            parent_id=parent_class,
                        )
                        self.graph_store.add_edge(file_path, qual, EdgeType.DEFINES)
                        self.graph_store.add_edge(qual, parent_class, EdgeType.CALLS)
                    else:
                        self.graph_store.add_node(
                            sym,
                            NodeType.FUNCTION,
                            file_path=file_path,
                            line_start=line_start,
                            line_end=line_end,
                        )
                        self.graph_store.add_edge(file_path, sym, EdgeType.DEFINES)

            # ----------------------------------------------------------------
            # Class definitions
            # ----------------------------------------------------------------
            elif nt in (
                'class_definition',  # Python
                'class_declaration',  # JS/TS/Java/C#
                'struct_item',  # Rust
                'impl_item',  # Rust
                'type_declaration',  # Go
                'interface_declaration',  # Java, TS
            ):
                name_node = editor._get_name_node(node)
                if name_node:
                    cls_name = _node_text(name_node)
                    line_start = node.start_point[0] + 1
                    line_end = node.end_point[0] + 1
                    self.graph_store.add_node(
                        cls_name,
                        NodeType.CLASS,
                        file_path=file_path,
                        line_start=line_start,
                        line_end=line_end,
                    )
                    self.graph_store.add_edge(file_path, cls_name, EdgeType.DEFINES)
                    classes_found.append(cls_name)
                    # Recurse into class body with parent_class set
                    for child in node.children:
                        _walk(child, parent_class=cls_name)
                    return  # already walked children

            # ----------------------------------------------------------------
            # Import statements — keep naive approach since tree varies a lot
            # by language; leaf text extraction is good enough here.
            # ----------------------------------------------------------------
            elif nt in (
                'import_statement',
                'import_from_statement',
                'use_declaration',
                'import_declaration',
                'extern_crate',
            ):
                # Grab first meaningful identifier as the module name
                for child in node.children:
                    if child.type in (
                        'dotted_name',
                        'identifier',
                        'module_path',
                        'scoped_identifier',
                    ):
                        module_name = _node_text(child).split('.')[0]
                        if module_name:
                            self.graph_store.add_node(module_name, NodeType.FILE)
                            self.graph_store.add_edge(
                                file_path, module_name, EdgeType.IMPORTS
                            )
                        break

            # Recurse into children
            for child in node.children:
                _walk(child, parent_class=parent_class)

        _walk(tree.root_node)
        logger.debug(
            'TreeSitter indexed %s: classes=%s',
            file_path,
            classes_found,
        )

    def _index_naive(self, file_path: str, content: str) -> None:
        """Naive import-line heuristic (original fallback)."""
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith(('import ', 'from ')):
                parts = stripped.split()
                if len(parts) > 1:
                    imported_module = parts[1].split('.')[0]
                    if imported_module:
                        self.graph_store.add_node(imported_module, NodeType.FILE)
                        self.graph_store.add_edge(
                            file_path, imported_module, EdgeType.IMPORTS
                        )

    def format_context(self, retrieval_result: dict) -> str:
        """Format retrieval results into a prompt-friendly string."""
        lines = ['### Semantic Matches']
        for res in retrieval_result['semantic_results']:
            content = res.get('content') or ''
            lines.append(f'- {content[:200]}...')

        lines.append('\n### Structural Context (Graph)')
        if retrieval_result['graph_context']:
            for edge in retrieval_result['graph_context']:
                lines.append(f'- {edge}')
        else:
            lines.append('(No structural relationships found)')

        return '\n'.join(lines)
