"""Graph-based memory store using NetworkX.

Stores code entities (nodes) and their relationships (edges) to enable
structural reasoning about the codebase.
"""

from __future__ import annotations

import json
import logging
import os
from enum import Enum
from typing import Any

import networkx as nx

logger = logging.getLogger(__name__)


class NodeType(str, Enum):
    FILE = 'file'
    CLASS = 'class'
    FUNCTION = 'function'
    VARIABLE = 'variable'
    CONCEPT = 'concept'


class EdgeType(str, Enum):
    IMPORTS = 'imports'
    CALLS = 'calls'
    DEFINES = 'defines'
    INHERITS = 'inherits'
    REFERENCES = 'references'
    RELATED_TO = 'related_to'


class GraphMemoryStore:
    """Persistent graph memory store using NetworkX."""

    def __init__(self, persistence_path: str | None = None):
        self.graph = nx.MultiDiGraph()
        self.persistence_path = persistence_path

        if self.persistence_path and os.path.exists(self.persistence_path):
            self.load()

    def add_node(self, node_id: str, node_type: NodeType, **attributes):
        """Add or update a node in the graph."""
        self.graph.add_node(node_id, type=node_type.value, **attributes)
        self._auto_save()

    def get_node(self, node_id: str) -> dict | None:
        """Get a node and its attributes."""
        if node_id in self.graph:
            return self.graph.nodes[node_id]
        return None

    def add_edge(
        self, source_id: str, target_id: str, edge_type: EdgeType, **attributes
    ):
        """Add a directed edge between nodes."""
        # Ensure nodes exist (auto-create as generic concepts if not)
        if source_id not in self.graph:
            self.add_node(source_id, NodeType.CONCEPT)
        if target_id not in self.graph:
            self.add_node(target_id, NodeType.CONCEPT)

        self.graph.add_edge(source_id, target_id, type=edge_type.value, **attributes)
        self._auto_save()

    def get_neighbors(
        self, node_id: str, edge_type: EdgeType | None = None
    ) -> list[dict]:
        """Get neighboring nodes, optionally filtered by edge type."""
        if node_id not in self.graph:
            return []

        neighbors = []
        for neighbor_id in self.graph.neighbors(node_id):
            edge_data = self.graph.get_edge_data(node_id, neighbor_id)

            # Handle MultiDiGraph edge data structure (dict of edges)
            for data in edge_data.values():
                if edge_type and data.get('type') != edge_type.value:
                    continue

                node_data = self.graph.nodes[neighbor_id]
                neighbors.append(
                    {
                        'id': neighbor_id,
                        'type': node_data.get('type'),
                        'relationship': data.get('type'),
                        'attributes': node_data,
                    }
                )

        return neighbors

    def get_subgraph(self, node_ids: list[str], depth: int = 1) -> nx.MultiDiGraph:
        """Extract a subgraph centered around the given nodes up to 'depth' hops."""
        nodes_to_include = set(node_ids)
        current_layer = set(node_ids)

        for _ in range(depth):
            next_layer = set()
            for node in current_layer:
                if node in self.graph:
                    next_layer.update(self.graph.neighbors(node))
                    # Also include incoming edges for context
                    next_layer.update(self.graph.predecessors(node))

            nodes_to_include.update(next_layer)
            current_layer = next_layer

        return self.graph.subgraph(nodes_to_include).copy()

    def search_by_attribute(self, attr_name: str, attr_value: Any) -> list[str]:
        """Find nodes with a specific attribute value."""
        return [
            n for n, d in self.graph.nodes(data=True) if d.get(attr_name) == attr_value
        ]

    def save(self):
        """Save graph to disk."""
        if not self.persistence_path:
            return

        try:
            data = nx.node_link_data(self.graph)
            os.makedirs(os.path.dirname(self.persistence_path), exist_ok=True)
            with open(self.persistence_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            logger.debug('Graph saved to %s', self.persistence_path)
        except Exception as e:
            logger.error('Failed to save graph: %s', e)

    def load(self):
        """Load graph from disk."""
        if not self.persistence_path or not os.path.exists(self.persistence_path):
            return

        try:
            with open(self.persistence_path, encoding='utf-8') as f:
                data = json.load(f)
            loaded = nx.node_link_graph(data)
            self.graph = loaded
            logger.info(
                'Graph loaded from %s (%s nodes)',
                self.persistence_path,
                self.graph.number_of_nodes(),
            )
        except Exception as e:
            logger.error('Failed to load graph: %s', e)
            raise

    def _auto_save(self):
        """Save on every write if path is set (for now)."""
        if self.persistence_path:
            self.save()

    def stats(self) -> dict:
        """Return graph statistics."""
        return {
            'nodes': self.graph.number_of_nodes(),
            'edges': self.graph.number_of_edges(),
            'density': nx.density(self.graph),
        }
