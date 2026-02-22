"""Tests for backend.memory.graph_rag — GraphRAG retrieval system."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


from backend.memory.graph_rag import GraphRAG
from backend.memory.graph_store import EdgeType, GraphMemoryStore, NodeType


def _make_vector_result(
    content: str,
    file_path: str | None = None,
    function_name: str | None = None,
) -> dict:
    """Helper to build a vector search result dict."""
    metadata: dict = {}
    if file_path:
        metadata["file_path"] = file_path
    if function_name:
        metadata["function_name"] = function_name
    return {"content": content, "metadata": metadata}


class TestRetrieve:
    """Tests for GraphRAG.retrieve()."""

    def test_empty_results(self):
        """Vector store returns nothing ⇒ no graph expansion occurs."""
        vec = MagicMock()
        vec.search.return_value = []
        rag = GraphRAG(vector_store=vec, graph_store=GraphMemoryStore())
        result = rag.retrieve("find something")

        assert result["semantic_results"] == []
        assert result["graph_context"] == []
        assert result["seed_nodes"] == []
        assert result["stats"]["vector_hits"] == 0

    def test_vector_only_no_graph_match(self):
        """Vector finds results whose metadata has no graph nodes."""
        vec = MagicMock()
        vec.search.return_value = [
            _make_vector_result("some text"),  # no file_path or function_name
        ]
        rag = GraphRAG(vector_store=vec, graph_store=GraphMemoryStore())
        result = rag.retrieve("query")

        assert len(result["semantic_results"]) == 1
        assert result["seed_nodes"] == []
        assert result["graph_context"] == []

    def test_vector_with_graph_expansion(self):
        """Vector result metadata maps to graph nodes → expansion occurs."""
        vec = MagicMock()
        vec.search.return_value = [
            _make_vector_result("handler code", file_path="handler.py"),
        ]

        gs = GraphMemoryStore()
        gs.add_node("handler.py", NodeType.FILE)
        gs.add_node("utils.py", NodeType.FILE)
        gs.add_edge("handler.py", "utils.py", EdgeType.IMPORTS)

        rag = GraphRAG(vector_store=vec, graph_store=gs)
        result = rag.retrieve("handler logic", max_results=5, graph_depth=1)

        assert result["seed_nodes"] == ["handler.py"]
        assert result["stats"]["graph_edges"] >= 1
        # Edge text should capture the relationship
        assert any("imports" in e for e in result["graph_context"])

    def test_function_name_seed(self):
        """function_name metadata creates a seed node."""
        vec = MagicMock()
        vec.search.return_value = [
            _make_vector_result("code", function_name="process"),
        ]

        gs = GraphMemoryStore()
        gs.add_node("process", NodeType.FUNCTION)
        gs.add_node("validate", NodeType.FUNCTION)
        gs.add_edge("process", "validate", EdgeType.CALLS)

        rag = GraphRAG(vector_store=vec, graph_store=gs)
        result = rag.retrieve("process function")
        assert "process" in result["seed_nodes"]
        assert result["stats"]["graph_edges"] >= 1

    def test_graph_depth_controls_expansion(self):
        """Deeper graph_depth yields more hops."""
        vec = MagicMock()
        vec.search.return_value = [
            _make_vector_result("A code", file_path="A"),
        ]

        gs = GraphMemoryStore()
        gs.add_node("A", NodeType.FILE)
        gs.add_node("B", NodeType.FILE)
        gs.add_node("C", NodeType.FILE)
        gs.add_edge("A", "B", EdgeType.IMPORTS)
        gs.add_edge("B", "C", EdgeType.IMPORTS)

        rag = GraphRAG(vector_store=vec, graph_store=gs)

        # depth=1 should only include A→B
        r1 = rag.retrieve("query", graph_depth=1)
        # depth=2 should include A→B and B→C
        r2 = rag.retrieve("query", graph_depth=2)
        assert r2["stats"]["graph_edges"] >= r1["stats"]["graph_edges"]

    def test_max_results_forwarded(self):
        """max_results is forwarded to vector search as k."""
        vec = MagicMock()
        vec.search.return_value = []
        rag = GraphRAG(vector_store=vec, graph_store=GraphMemoryStore())
        rag.retrieve("q", max_results=3)
        vec.search.assert_called_once_with("q", k=3)


class TestIndexCodeFile:
    """Tests for GraphRAG.index_code_file()."""

    def test_adds_file_node(self):
        """Indexing a file creates a FILE node."""
        gs = GraphMemoryStore()
        rag = GraphRAG(vector_store=MagicMock(), graph_store=gs)
        rag.index_code_file("app.py", "x = 1")
        assert "app.py" in gs.graph
        assert gs.graph.nodes["app.py"]["type"] == "file"

    def test_detects_import_statement(self):
        """Simple `import x` creates an edge."""
        gs = GraphMemoryStore()
        rag = GraphRAG(vector_store=MagicMock(), graph_store=gs)
        rag.index_code_file("main.py", "import os\nimport sys\n")
        assert "os" in gs.graph
        assert "sys" in gs.graph
        neighbors = gs.get_neighbors("main.py", edge_type=EdgeType.IMPORTS)
        ids = {n["id"] for n in neighbors}
        assert ids == {"os", "sys"}

    def test_detects_from_import(self):
        """A `from x import y` creates edge to x."""
        gs = GraphMemoryStore()
        rag = GraphRAG(vector_store=MagicMock(), graph_store=gs)
        rag.index_code_file("utils.py", "from pathlib import Path\n")
        assert "pathlib" in gs.graph
        neighbors = gs.get_neighbors("utils.py", edge_type=EdgeType.IMPORTS)
        assert neighbors

    def test_ignores_non_import_lines(self):
        """Non-import lines should not create edges."""
        gs = GraphMemoryStore()
        rag = GraphRAG(vector_store=MagicMock(), graph_store=gs)
        rag.index_code_file("clean.py", "x = 1\nprint('hello')\n")
        assert gs.graph.number_of_edges() == 0

    def test_multiple_files(self):
        """Indexing multiple files creates a connected graph."""
        gs = GraphMemoryStore()
        rag = GraphRAG(vector_store=MagicMock(), graph_store=gs)
        rag.index_code_file("a.py", "import b\n")
        rag.index_code_file("b.py", "import c\n")
        assert gs.graph.number_of_nodes() >= 3  # a.py, b, b.py, c

    def test_extracts_classes_and_functions_with_line_numbers(self, tmp_path):
        """Indexing a file extracts classes and functions with line numbers."""
        # GraphRAG only indexes classes/functions when TreeSitter is available.
        # In minimal test environments (like Windows CI) TreeSitter is optional,
        # and GraphRAG intentionally falls back to the naive import parser.
        import backend.memory.graph_rag as graph_rag_module

        if not getattr(graph_rag_module, "_TREESITTER_AVAILABLE", False):
            pytest.skip("TreeSitter not available; GraphRAG uses naive import parsing")

        gs = GraphMemoryStore()
        rag = GraphRAG(vector_store=MagicMock(), graph_store=gs)
        code = '''
class MyClass:
    def my_method(self):
        pass

def my_function():
    pass
'''
        file_path = tmp_path / "test.py"
        file_path.write_text(code, encoding="utf-8")
        
        rag.index_code_file(str(file_path), code)
        
        # Check class node
        class_node = gs.get_node("MyClass")
        assert class_node is not None
        assert class_node["type"] == "class"
        assert class_node["file_path"] == str(file_path)
        assert class_node["line_start"] == 2
        assert class_node["line_end"] == 4
        
        # Check method node
        method_node = gs.get_node("MyClass.my_method")
        assert method_node is not None
        assert method_node["type"] == "function"
        assert method_node["file_path"] == str(file_path)
        assert method_node["line_start"] == 3
        assert method_node["line_end"] == 4
        assert method_node["parent_id"] == "MyClass"
        
        # Check function node
        func_node = gs.get_node("my_function")
        assert func_node is not None
        assert func_node["type"] == "function"
        assert func_node["file_path"] == str(file_path)
        assert func_node["line_start"] == 6
        assert func_node["line_end"] == 7


class TestFormatContext:
    """Tests for GraphRAG.format_context()."""

    def test_format_with_semantic_and_graph(self):
        result = {
            "semantic_results": [{"content": "some code"}],
            "graph_context": ["handler.py imports utils.py"],
            "seed_nodes": ["handler.py"],
            "stats": {"vector_hits": 1, "graph_nodes": 1, "graph_edges": 1},
        }
        rag = GraphRAG(vector_store=MagicMock(), graph_store=GraphMemoryStore())
        text = rag.format_context(result)
        assert "Semantic Matches" in text
        assert "some code" in text
        assert "Structural Context" in text
        assert "handler.py imports utils.py" in text

    def test_format_no_graph_context(self):
        result = {
            "semantic_results": [{"content": "text"}],
            "graph_context": [],
            "seed_nodes": [],
            "stats": {"vector_hits": 1, "graph_nodes": 0, "graph_edges": 0},
        }
        rag = GraphRAG(vector_store=MagicMock(), graph_store=GraphMemoryStore())
        text = rag.format_context(result)
        assert "No structural relationships found" in text

    def test_format_truncates_long_content(self):
        long_content = "x" * 500
        result = {
            "semantic_results": [{"content": long_content}],
            "graph_context": [],
            "seed_nodes": [],
            "stats": {"vector_hits": 1, "graph_nodes": 0, "graph_edges": 0},
        }
        rag = GraphRAG(vector_store=MagicMock(), graph_store=GraphMemoryStore())
        text = rag.format_context(result)
        # Content is truncated to 200 chars + "..."
        assert len(text) < len(long_content) + 100

    def test_format_empty_results(self):
        result = {
            "semantic_results": [],
            "graph_context": [],
            "seed_nodes": [],
            "stats": {"vector_hits": 0, "graph_nodes": 0, "graph_edges": 0},
        }
        rag = GraphRAG(vector_store=MagicMock(), graph_store=GraphMemoryStore())
        text = rag.format_context(result)
        assert "Semantic Matches" in text
