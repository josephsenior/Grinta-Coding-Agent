"""Tests for backend.memory.graph_store — GraphMemoryStore with NetworkX."""

from __future__ import annotations

import json
import os

import pytest

from backend.memory.graph_store import EdgeType, GraphMemoryStore, NodeType


# ── NodeType / EdgeType enums ────────────────────────────────────────


class TestEnums:
    def test_node_types(self):
        assert NodeType.FILE.value == "file"
        assert NodeType.CLASS.value == "class"
        assert NodeType.FUNCTION.value == "function"
        assert NodeType.VARIABLE.value == "variable"
        assert NodeType.CONCEPT.value == "concept"

    def test_edge_types(self):
        assert EdgeType.IMPORTS.value == "imports"
        assert EdgeType.CALLS.value == "calls"
        assert EdgeType.DEFINES.value == "defines"
        assert EdgeType.INHERITS.value == "inherits"
        assert EdgeType.REFERENCES.value == "references"
        assert EdgeType.RELATED_TO.value == "related_to"


# ── GraphMemoryStore base ────────────────────────────────────────────


class TestGraphMemoryStoreBasic:
    def test_init_no_persistence(self):
        store = GraphMemoryStore()
        assert store.graph is not None
        assert store.graph.number_of_nodes() == 0

    def test_add_node(self):
        store = GraphMemoryStore()
        store.add_node("foo.py", NodeType.FILE, language="python")
        assert "foo.py" in store.graph
        assert store.graph.nodes["foo.py"]["type"] == "file"
        assert store.graph.nodes["foo.py"]["language"] == "python"

    def test_add_edge(self):
        store = GraphMemoryStore()
        store.add_node("a.py", NodeType.FILE)
        store.add_node("b.py", NodeType.FILE)
        store.add_edge("a.py", "b.py", EdgeType.IMPORTS)
        assert store.graph.has_edge("a.py", "b.py")

    def test_add_edge_auto_creates_nodes(self):
        store = GraphMemoryStore()
        store.add_edge("src", "dst", EdgeType.CALLS)
        assert "src" in store.graph
        assert "dst" in store.graph
        # Auto-created nodes default to CONCEPT type
        assert store.graph.nodes["src"]["type"] == "concept"

    def test_stats(self):
        store = GraphMemoryStore()
        store.add_node("a", NodeType.FILE)
        store.add_node("b", NodeType.CLASS)
        store.add_edge("a", "b", EdgeType.DEFINES)
        s = store.stats()
        assert s["nodes"] == 2
        assert s["edges"] == 1
        assert isinstance(s["density"], float)


# ── get_neighbors ────────────────────────────────────────────────────


class TestGetNeighbors:
    def test_no_neighbors(self):
        store = GraphMemoryStore()
        store.add_node("alone", NodeType.FILE)
        assert store.get_neighbors("alone") == []

    def test_node_not_in_graph(self):
        store = GraphMemoryStore()
        assert store.get_neighbors("nonexistent") == []

    def test_neighbors_returned(self):
        store = GraphMemoryStore()
        store.add_node("a", NodeType.FILE)
        store.add_node("b", NodeType.CLASS)
        store.add_edge("a", "b", EdgeType.DEFINES)
        neighbors = store.get_neighbors("a")
        assert len(neighbors) == 1
        assert neighbors[0]["id"] == "b"
        assert neighbors[0]["relationship"] == "defines"

    def test_filter_by_edge_type(self):
        store = GraphMemoryStore()
        store.add_node("a", NodeType.FILE)
        store.add_node("b", NodeType.CLASS)
        store.add_node("c", NodeType.FUNCTION)
        store.add_edge("a", "b", EdgeType.DEFINES)
        store.add_edge("a", "c", EdgeType.IMPORTS)
        # Filter only DEFINES
        neighbors = store.get_neighbors("a", EdgeType.DEFINES)
        assert len(neighbors) == 1
        assert neighbors[0]["id"] == "b"


# ── get_subgraph ─────────────────────────────────────────────────────


class TestGetSubgraph:
    def test_single_node_depth_0(self):
        store = GraphMemoryStore()
        store.add_node("a", NodeType.FILE)
        sub = store.get_subgraph(["a"], depth=0)
        assert sub.number_of_nodes() == 1

    def test_depth_1(self):
        store = GraphMemoryStore()
        store.add_node("a", NodeType.FILE)
        store.add_node("b", NodeType.CLASS)
        store.add_node("c", NodeType.FUNCTION)
        store.add_edge("a", "b", EdgeType.DEFINES)
        store.add_edge("b", "c", EdgeType.CALLS)
        sub = store.get_subgraph(["a"], depth=1)
        assert "a" in sub
        assert "b" in sub
        # c is 2 hops, shouldn't be in depth=1 from a forward
        # But b→c is not followed from a-centric depth=1
        # Actually: depth=1 includes a's neighbors + predecessors

    def test_depth_2(self):
        store = GraphMemoryStore()
        store.add_node("a", NodeType.FILE)
        store.add_node("b", NodeType.CLASS)
        store.add_node("c", NodeType.FUNCTION)
        store.add_edge("a", "b", EdgeType.DEFINES)
        store.add_edge("b", "c", EdgeType.CALLS)
        sub = store.get_subgraph(["a"], depth=2)
        assert "c" in sub


# ── search_by_attribute ──────────────────────────────────────────────


class TestSearchByAttribute:
    def test_found(self):
        store = GraphMemoryStore()
        store.add_node("a.py", NodeType.FILE, language="python")
        store.add_node("b.rs", NodeType.FILE, language="rust")
        store.add_node("c.py", NodeType.FILE, language="python")
        results = store.search_by_attribute("language", "python")
        assert set(results) == {"a.py", "c.py"}

    def test_not_found(self):
        store = GraphMemoryStore()
        store.add_node("a", NodeType.FILE)
        assert store.search_by_attribute("language", "go") == []

    def test_search_by_type(self):
        store = GraphMemoryStore()
        store.add_node("x", NodeType.FILE)
        store.add_node("y", NodeType.CLASS)
        results = store.search_by_attribute("type", "class")
        assert results == ["y"]


# ── persistence (save / load) ────────────────────────────────────────


class TestPersistence:
    def test_save_and_load(self, tmp_path):
        path = str(tmp_path / "graph.json")
        store = GraphMemoryStore(persistence_path=path)
        store.add_node("a", NodeType.FILE)
        store.add_node("b", NodeType.CLASS)
        store.add_edge("a", "b", EdgeType.DEFINES)
        store.save()
        assert os.path.exists(path)

        # Load in a new store
        store2 = GraphMemoryStore(persistence_path=path)
        assert store2.graph.number_of_nodes() == 2
        assert store2.graph.has_edge("a", "b")

    def test_save_no_persistence_path(self):
        store = GraphMemoryStore()
        store.add_node("a", NodeType.FILE)
        store.save()  # Should not raise

    def test_load_missing_file(self, tmp_path):
        path = str(tmp_path / "does_not_exist.json")
        store = GraphMemoryStore(persistence_path=path)
        store.load()  # Should not raise
        assert store.graph.number_of_nodes() == 0

    def test_auto_save(self, tmp_path):
        path = str(tmp_path / "auto.json")
        store = GraphMemoryStore(persistence_path=path)
        store.add_node("x", NodeType.FILE)
        # Auto-save should have written the file
        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
        assert data is not None

    def test_load_corrupted_file(self, tmp_path):
        path = str(tmp_path / "broken.json")
        with open(path, "w") as f:
            f.write("not json")
        store = GraphMemoryStore(persistence_path=path)
        # Should log error but not raise
        assert store.graph.number_of_nodes() == 0
