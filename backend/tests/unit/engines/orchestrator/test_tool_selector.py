"""Tests for backend.engines.orchestrator.tool_selector."""

from __future__ import annotations

from backend.engines.orchestrator.tool_selector import ToolSelector, _get_tool_name


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(name: str, description: str = "A tool.") -> dict:
    """Create a minimal ChatCompletionToolParam-like dict."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }


_ALL_TOOLS = [
    _make_tool("execute_bash"),
    _make_tool("str_replace_editor"),
    _make_tool("search_code"),
    _make_tool("think"),
    _make_tool("finish"),
    _make_tool("verify_file_lines"),
    _make_tool("task_tracker"),
    _make_tool("memory_manager"),
    _make_tool("analyze_project_structure"),
    # Contextual tools
    _make_tool("query_error_solutions"),
    _make_tool("checkpoint"),
    _make_tool("session_diff"),
    _make_tool("workspace_status"),
    _make_tool("summarize_context"),
    _make_tool("apply_patch"),
    _make_tool("web_reader"),
]


# ---------------------------------------------------------------------------
# _get_tool_name
# ---------------------------------------------------------------------------


class TestGetToolName:
    def test_extracts_name(self):
        assert _get_tool_name(_make_tool("bash")) == "bash"

    def test_empty_dict_returns_none(self):
        assert _get_tool_name({}) is None

    def test_missing_function_key_returns_none(self):
        assert _get_tool_name({"type": "function"}) is None


class TestToolSelector:
    def test_returns_all_tools_without_heuristic_filtering(self):
        ts = ToolSelector()
        selected = ts.select_tools(_ALL_TOOLS, state=None, messages=[])
        assert [_get_tool_name(t) for t in selected] == [
            _get_tool_name(t) for t in _ALL_TOOLS
        ]

    def test_deduplicates_by_name_preserving_first_occurrence(self):
        ts = ToolSelector()
        tools = _ALL_TOOLS + [_make_tool("search_code", description="duplicate")]
        selected = ts.select_tools(tools, state=None, messages=[])
        names = [_get_tool_name(t) for t in selected]
        assert names.count("search_code") == 1
        assert names[:3] == ["execute_bash", "str_replace_editor", "search_code"]

    def test_notify_condensation_does_not_change_selection(self):
        ts = ToolSelector()
        ts.notify_condensation()
        selected = ts.select_tools(_ALL_TOOLS, state=None, messages=[])
        assert [_get_tool_name(t) for t in selected] == [
            _get_tool_name(t) for t in _ALL_TOOLS
        ]
