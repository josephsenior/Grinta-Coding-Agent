"""GraphRAG: Retrieval Augmented Generation using Knowledge Graphs.

Combines semantic search (Vector Store) with structural traversal (Graph Store)
to provide rich, context-aware retrieval.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.memory.graph_store import GraphMemoryStore, NodeType
from backend.memory.vector_store import EnhancedVectorStore

logger = logging.getLogger(__name__)


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
            metadata = result.get("metadata", {})
            if "file_path" in metadata:
                seed_node_ids.append(metadata["file_path"])
            if "function_name" in metadata:
                seed_node_ids.append(metadata["function_name"])

        # 2. Graph Expansion
        graph_context = []
        if seed_node_ids:
            # Get subgraph around seed nodes
            subgraph = self.graph_store.get_subgraph(seed_node_ids, depth=graph_depth)

            # Convert subgraph to readable context
            for u, v, data in subgraph.edges(data=True):
                edge_type = data.get("type", "related_to")
                graph_context.append(f"{u} {edge_type} {v}")

        return {
            "semantic_results": semantic_context,
            "graph_context": graph_context,
            "seed_nodes": seed_node_ids,
            "stats": {
                "vector_hits": len(vector_results),
                "graph_nodes": len(seed_node_ids),
                "graph_edges": len(graph_context),
            },
        }

    def index_code_file(self, file_path: str, content: str):
        """Index a code file into both vector and graph stores.

        TODO: Use a parser (AST/TreeSitter) to extract real relationships.
        For now, this is a placeholder that creates a file node.
        """
        # 1. Vector Store Indexing
        # self.vector_store.add(...) - This is usually done by the memory manager

        # 2. Graph Store Indexing
        self.graph_store.add_node(file_path, NodeType.FILE)

        # Simple heuristic: Find imports (very basic python example)
        for line in content.splitlines():
            if line.startswith(("import ", "from ")):
                # This is a very naive parser, just for demonstration
                parts = line.split()
                if len(parts) > 1:
                    imported_module = parts[1]
                    self.graph_store.add_node(imported_module, NodeType.FILE)
                    from backend.memory.graph_store import EdgeType

                    self.graph_store.add_edge(
                        file_path, imported_module, EdgeType.IMPORTS
                    )

    def format_context(self, retrieval_result: dict) -> str:
        """Format retrieval results into a prompt-friendly string."""
        lines = ["### Semantic Matches"]
        for res in retrieval_result["semantic_results"]:
            lines.append(f"- {res.get('content', '')[:200]}...")

        lines.append("\n### Structural Context (Graph)")
        if retrieval_result["graph_context"]:
            for edge in retrieval_result["graph_context"]:
                lines.append(f"- {edge}")
        else:
            lines.append("(No structural relationships found)")

        return "\n".join(lines)
