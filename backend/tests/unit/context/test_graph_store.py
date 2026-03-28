"""Tests for backend.context.graph_store — GraphMemoryStore with NetworkX."""

from __future__ import annotations

import json
import os

import pytest

from backend.context.graph_store import EdgeType, GraphMemoryStore, NodeType


class TestNodeType:
    """Tests for NodeType enum."""

    def test_values(self):
        assert NodeType.FILE.value == "file"
        assert NodeType.CLASS.value == "class"
        assert NodeType.FUNCTION.value == "function"
        assert NodeType.VARIABLE.value == "variable"
        assert NodeType.CONCEPT.value == "concept"

    def test_string_enum(self):
        assert isinstance(NodeType.FILE, str)
        assert NodeType("file") is NodeType.FILE


class TestEdgeType:
    """Tests for EdgeType enum."""

    def test_values(self):
        assert EdgeType.IMPORTS.value == "imports"
        assert EdgeType.CALLS.value == "calls"
        assert EdgeType.DEFINES.value == "defines"
        assert EdgeType.INHERITS.value == "inherits"
        assert EdgeType.REFERENCES.value == "references"
        assert EdgeType.RELATED_TO.value == "related_to"


class TestGraphMemoryStoreInit:
    """Tests for GraphMemoryStore initialization."""

    def test_init_no_persistence(self):
        store = GraphMemoryStore()
        assert store.persistence_path is None
        assert store.graph.number_of_nodes() == 0
        assert store.graph.number_of_edges() == 0

    def test_init_with_nonexistent_path(self, tmp_path):
        path = str(tmp_path / "graph.json")
        store = GraphMemoryStore(persistence_path=path)
        assert store.persistence_path == path
        assert store.graph.number_of_nodes() == 0

    def test_init_loads_existing_graph(self, tmp_path):
        path = str(tmp_path / "graph.json")
        # Create a store with data and save
        store1 = GraphMemoryStore(persistence_path=path)
        store1.add_node("module.py", NodeType.FILE)
        store1.add_node("MyClass", NodeType.CLASS)
        store1.add_edge("module.py", "MyClass", EdgeType.DEFINES)
        store1.save()

        # Load from same path
        store2 = GraphMemoryStore(persistence_path=path)
        assert store2.graph.number_of_nodes() == 2
        assert store2.graph.number_of_edges() == 1


class TestAddNode:
    """Tests for add_node."""

    def test_add_single_node(self):
        store = GraphMemoryStore()
        store.add_node("app.py", NodeType.FILE)
        assert "app.py" in store.graph
        assert store.graph.nodes["app.py"]["type"] == "file"

    def test_add_node_with_attributes(self):
        store = GraphMemoryStore()
        store.add_node("MyClass", NodeType.CLASS, module="app", line=42)
        data = store.graph.nodes["MyClass"]
        assert data["type"] == "class"
        assert data["module"] == "app"
        assert data["line"] == 42

    def test_add_duplicate_node_updates(self):
        store = GraphMemoryStore()
        store.add_node("func", NodeType.FUNCTION, line=10)
        store.add_node("func", NodeType.FUNCTION, line=20)
        assert store.graph.nodes["func"]["line"] == 20
        assert store.graph.number_of_nodes() == 1

    def test_add_multiple_node_types(self):
        store = GraphMemoryStore()
        store.add_node("main.py", NodeType.FILE)
        store.add_node("Handler", NodeType.CLASS)
        store.add_node("process", NodeType.FUNCTION)
        store.add_node("MAX_SIZE", NodeType.VARIABLE)
        store.add_node("caching", NodeType.CONCEPT)
        assert store.graph.number_of_nodes() == 5


class TestAddEdge:
    """Tests for add_edge."""

    def test_add_edge_between_existing_nodes(self):
        store = GraphMemoryStore()
        store.add_node("app.py", NodeType.FILE)
        store.add_node("utils.py", NodeType.FILE)
        store.add_edge("app.py", "utils.py", EdgeType.IMPORTS)
        assert store.graph.number_of_edges() == 1

    def test_add_edge_auto_creates_nodes(self):
        store = GraphMemoryStore()
        store.add_edge("unknown_a", "unknown_b", EdgeType.RELATED_TO)
        assert "unknown_a" in store.graph
        assert "unknown_b" in store.graph
        assert store.graph.nodes["unknown_a"]["type"] == "concept"

    def test_add_edge_with_attributes(self):
        store = GraphMemoryStore()
        store.add_node("ClassA", NodeType.CLASS)
        store.add_node("ClassB", NodeType.CLASS)
        store.add_edge("ClassA", "ClassB", EdgeType.INHERITS, depth=1)
        edges = list(store.graph.edges(data=True))
        assert len(edges) == 1
        assert edges[0][2]["type"] == "inherits"
        assert edges[0][2]["depth"] == 1

    def test_multidigraph_allows_parallel_edges(self):
        store = GraphMemoryStore()
        store.add_node("A", NodeType.CLASS)
        store.add_node("B", NodeType.CLASS)
        store.add_edge("A", "B", EdgeType.CALLS)
        store.add_edge("A", "B", EdgeType.REFERENCES)
        assert store.graph.number_of_edges() == 2


class TestGetNeighbors:
    """Tests for get_neighbors."""

    def test_no_neighbors(self):
        store = GraphMemoryStore()
        store.add_node("isolated", NodeType.FILE)
        assert store.get_neighbors("isolated") == []

    def test_nonexistent_node_returns_empty(self):
        store = GraphMemoryStore()
        assert store.get_neighbors("does_not_exist") == []

    def test_get_all_neighbors(self):
        store = GraphMemoryStore()
        store.add_node("app.py", NodeType.FILE)
        store.add_node("utils.py", NodeType.FILE)
        store.add_node("models.py", NodeType.FILE)
        store.add_edge("app.py", "utils.py", EdgeType.IMPORTS)
        store.add_edge("app.py", "models.py", EdgeType.IMPORTS)
        neighbors = store.get_neighbors("app.py")
        ids = {n["id"] for n in neighbors}
        assert ids == {"utils.py", "models.py"}

    def test_filter_by_edge_type(self):
        store = GraphMemoryStore()
        store.add_node("A", NodeType.CLASS)
        store.add_node("B", NodeType.CLASS)
        store.add_node("C", NodeType.CLASS)
        store.add_edge("A", "B", EdgeType.INHERITS)
        store.add_edge("A", "C", EdgeType.REFERENCES)
        inherits = store.get_neighbors("A", edge_type=EdgeType.INHERITS)
        assert len(inherits) == 1
        assert inherits[0]["id"] == "B"


class TestGetSubgraph:
    """Tests for get_subgraph."""

    def test_single_node_depth_zero(self):
        store = GraphMemoryStore()
        store.add_node("A", NodeType.FILE)
        store.add_node("B", NodeType.FILE)
        store.add_edge("A", "B", EdgeType.IMPORTS)
        sub = store.get_subgraph(["A"], depth=0)
        assert set(sub.nodes()) == {"A"}

    def test_depth_one_includes_neighbors(self):
        store = GraphMemoryStore()
        store.add_node("A", NodeType.FILE)
        store.add_node("B", NodeType.FILE)
        store.add_node("C", NodeType.FILE)
        store.add_edge("A", "B", EdgeType.IMPORTS)
        store.add_edge("B", "C", EdgeType.IMPORTS)
        sub = store.get_subgraph(["A"], depth=1)
        assert "A" in sub.nodes()
        assert "B" in sub.nodes()
        # C is 2 hops away, should not be included
        assert "C" not in sub.nodes()

    def test_depth_two_includes_transitive(self):
        store = GraphMemoryStore()
        store.add_node("A", NodeType.FILE)
        store.add_node("B", NodeType.FILE)
        store.add_node("C", NodeType.FILE)
        store.add_edge("A", "B", EdgeType.IMPORTS)
        store.add_edge("B", "C", EdgeType.IMPORTS)
        sub = store.get_subgraph(["A"], depth=2)
        assert set(sub.nodes()) == {"A", "B", "C"}

    def test_includes_predecessors(self):
        """Subgraph includes incoming edges (predecessors)."""
        store = GraphMemoryStore()
        store.add_node("A", NodeType.FILE)
        store.add_node("B", NodeType.FILE)
        store.add_edge("B", "A", EdgeType.IMPORTS)  # B imports A
        sub = store.get_subgraph(["A"], depth=1)
        assert "B" in sub.nodes()

    def test_multiple_seed_nodes(self):
        store = GraphMemoryStore()
        for name in ["A", "B", "C", "D"]:
            store.add_node(name, NodeType.FILE)
        store.add_edge("A", "C", EdgeType.IMPORTS)
        store.add_edge("B", "D", EdgeType.IMPORTS)
        sub = store.get_subgraph(["A", "B"], depth=1)
        assert set(sub.nodes()) == {"A", "B", "C", "D"}


class TestSearchByAttribute:
    """Tests for search_by_attribute."""

    def test_search_by_type(self):
        store = GraphMemoryStore()
        store.add_node("app.py", NodeType.FILE)
        store.add_node("MyClass", NodeType.CLASS)
        store.add_node("utils.py", NodeType.FILE)
        results = store.search_by_attribute("type", "file")
        assert set(results) == {"app.py", "utils.py"}

    def test_search_by_custom_attribute(self):
        store = GraphMemoryStore()
        store.add_node("fast_func", NodeType.FUNCTION, performance="fast")
        store.add_node("slow_func", NodeType.FUNCTION, performance="slow")
        results = store.search_by_attribute("performance", "fast")
        assert results == ["fast_func"]

    def test_search_no_match(self):
        store = GraphMemoryStore()
        store.add_node("A", NodeType.FILE)
        assert store.search_by_attribute("missing", "value") == []


class TestPersistence:
    """Tests for save/load."""

    def test_save_and_load_roundtrip(self, tmp_path):
        path = str(tmp_path / "graph.json")
        store = GraphMemoryStore(persistence_path=path)
        store.add_node("app.py", NodeType.FILE, module="main")
        store.add_node("Handler", NodeType.CLASS)
        store.add_edge("app.py", "Handler", EdgeType.DEFINES)
        store.save()

        store2 = GraphMemoryStore(persistence_path=path)
        assert store2.graph.number_of_nodes() == 2
        assert store2.graph.number_of_edges() == 1

    def test_save_creates_directories(self, tmp_path):
        path = str(tmp_path / "deep" / "nested" / "graph.json")
        store = GraphMemoryStore(persistence_path=path)
        store.add_node("A", NodeType.FILE)
        store.save()
        assert os.path.exists(path)

    def test_load_nonexistent_path_is_noop(self, tmp_path):
        path = str(tmp_path / "nonexistent.json")
        store = GraphMemoryStore(persistence_path=path)
        store.load()
        assert store.graph.number_of_nodes() == 0

    def test_load_corrupted_file_raises(self, tmp_path):
        """Loading a corrupted file raises so callers know the graph was not loaded."""
        path = str(tmp_path / "corrupted.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{corrupted garbage")
        with pytest.raises(Exception):
            GraphMemoryStore(persistence_path=path)

    def test_auto_save(self, tmp_path):
        path = str(tmp_path / "auto.json")
        store = GraphMemoryStore(persistence_path=path)
        store.add_node("X", NodeType.FILE)  # Should trigger auto_save
        assert os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data.get("nodes", [])) >= 1

    def test_save_without_path_is_noop(self):
        store = GraphMemoryStore()
        store.add_node("A", NodeType.FILE)
        store.save()  # Should not raise


class TestStats:
    """Tests for stats."""

    def test_empty_graph_stats(self):
        store = GraphMemoryStore()
        s = store.stats()
        assert s["nodes"] == 0
        assert s["edges"] == 0
        assert s["density"] == 0

    def test_populated_graph_stats(self):
        store = GraphMemoryStore()
        store.add_node("A", NodeType.FILE)
        store.add_node("B", NodeType.FILE)
        store.add_edge("A", "B", EdgeType.IMPORTS)
        s = store.stats()
        assert s["nodes"] == 2
        assert s["edges"] == 1
        assert s["density"] > 0
