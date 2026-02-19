"""Tests for backend.engines.orchestrator.tool_selector — progressive tool disclosure."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

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


def _make_state(
    turn: int = 0,
    errors: int = 0,
    file_edits: int = 0,
    token_pct: float = 0.0,
):
    """Create a minimal mock State for tool selection."""
    state = MagicMock()
    # Iteration flag
    iter_flag = MagicMock()
    iter_flag.current_value = turn
    state.iteration_flag = iter_flag

    # Token usage
    metrics = MagicMock()
    atu = MagicMock()
    atu.prompt_tokens = int(token_pct * 100_000)
    atu.context_window = 100_000
    metrics.accumulated_token_usage = atu
    state.metrics = metrics

    # History with errors and edits
    history: list = []
    for _ in range(errors):
        err = MagicMock()
        type(err).__name__ = "ErrorObservation"
        err.content = "error occurred"
        history.append(err)
    for _ in range(file_edits):
        edit = MagicMock()
        type(edit).__name__ = "FileEditAction"
        history.append(edit)
    state.history = history

    return state


# Full base toolset for testing
_ALL_TOOLS = [
    _make_tool("execute_bash"),
    _make_tool("str_replace_editor"),
    _make_tool("search_code"),
    _make_tool("think"),
    _make_tool("finish"),
    _make_tool("note"),
    _make_tool("recall"),
    _make_tool("semantic_recall"),
    _make_tool("run_tests"),
    _make_tool("verify_state"),
    _make_tool("task_tracker"),
    _make_tool("project_map"),
    # Contextual tools
    _make_tool("error_patterns"),
    _make_tool("working_memory"),
    _make_tool("checkpoint"),
    _make_tool("session_diff"),
    _make_tool("workspace_status"),
    _make_tool("condensation_request"),
    _make_tool("apply_patch"),
    _make_tool("web_search"),
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


# ---------------------------------------------------------------------------
# Core tools always included
# ---------------------------------------------------------------------------


class TestCoreToolsAlwaysIncluded:
    def test_core_tools_on_first_turn(self):
        ts = ToolSelector()
        state = _make_state(turn=0)
        selected = ts.select_tools(_ALL_TOOLS, state)
        names = {_get_tool_name(t) for t in selected}
        # Core tools must be present
        for core in [
            "execute_bash",
            "str_replace_editor",
            "search_code",
            "think",
            "finish",
            "note",
            "recall",
            "run_tests",
            "verify_state",
            "task_tracker",
            "project_map",
        ]:
            assert core in names, f"Core tool '{core}' missing on turn 0"

    def test_core_tools_on_late_turn(self):
        ts = ToolSelector()
        state = _make_state(turn=20)
        selected = ts.select_tools(_ALL_TOOLS, state)
        names = {_get_tool_name(t) for t in selected}
        assert "think" in names
        assert "execute_bash" in names


# ---------------------------------------------------------------------------
# Contextual tools hidden by default
# ---------------------------------------------------------------------------


class TestContextualToolsHiddenByDefault:
    def test_error_patterns_hidden_with_no_errors(self):
        ts = ToolSelector()
        state = _make_state(turn=0, errors=0)
        selected = ts.select_tools(_ALL_TOOLS, state)
        names = {_get_tool_name(t) for t in selected}
        assert "error_patterns" not in names

    def test_checkpoint_hidden_before_turn_5(self):
        ts = ToolSelector()
        state = _make_state(turn=3)
        selected = ts.select_tools(_ALL_TOOLS, state)
        names = {_get_tool_name(t) for t in selected}
        assert "checkpoint" not in names

    def test_session_diff_hidden_with_few_edits(self):
        ts = ToolSelector()
        state = _make_state(turn=2, file_edits=1)
        selected = ts.select_tools(_ALL_TOOLS, state)
        names = {_get_tool_name(t) for t in selected}
        assert "session_diff" not in names


# ---------------------------------------------------------------------------
# Contextual tools unlocked by conditions
# ---------------------------------------------------------------------------


class TestContextualToolsUnlocked:
    def test_error_patterns_unlocked_after_errors(self):
        ts = ToolSelector()
        state = _make_state(turn=5, errors=3)
        selected = ts.select_tools(_ALL_TOOLS, state)
        names = {_get_tool_name(t) for t in selected}
        assert "error_patterns" in names

    def test_working_memory_unlocked_after_turn_3(self):
        ts = ToolSelector()
        state = _make_state(turn=3)
        selected = ts.select_tools(_ALL_TOOLS, state)
        names = {_get_tool_name(t) for t in selected}
        assert "working_memory" in names

    def test_working_memory_unlocked_on_complex_task(self):
        ts = ToolSelector()
        state = _make_state(turn=0)
        messages = [
            {
                "role": "user",
                "content": "create a new module, fix the tests, and refactor the API",
            }
        ]
        selected = ts.select_tools(_ALL_TOOLS, state, messages)
        names = {_get_tool_name(t) for t in selected}
        assert "working_memory" in names

    def test_checkpoint_unlocked_after_turn_5(self):
        ts = ToolSelector()
        state = _make_state(turn=6)
        selected = ts.select_tools(_ALL_TOOLS, state)
        names = {_get_tool_name(t) for t in selected}
        assert "checkpoint" in names

    def test_session_diff_unlocked_after_3_edits(self):
        ts = ToolSelector()
        state = _make_state(turn=5, file_edits=4)
        selected = ts.select_tools(_ALL_TOOLS, state)
        names = {_get_tool_name(t) for t in selected}
        assert "session_diff" in names

    def test_workspace_status_on_first_turn(self):
        ts = ToolSelector()
        state = _make_state(turn=0)
        selected = ts.select_tools(_ALL_TOOLS, state)
        names = {_get_tool_name(t) for t in selected}
        assert "workspace_status" in names

    def test_workspace_status_after_condensation(self):
        ts = ToolSelector()
        ts.notify_condensation()
        state = _make_state(turn=10)
        selected = ts.select_tools(_ALL_TOOLS, state)
        names = {_get_tool_name(t) for t in selected}
        assert "workspace_status" in names

    def test_condensation_request_on_high_token_usage(self):
        ts = ToolSelector()
        state = _make_state(turn=5, token_pct=0.7)
        selected = ts.select_tools(_ALL_TOOLS, state)
        names = {_get_tool_name(t) for t in selected}
        assert "condensation_request" in names

    def test_web_tools_on_research_task(self):
        ts = ToolSelector()
        state = _make_state(turn=0)
        messages = [
            {
                "role": "user",
                "content": "research the best database library for this project",
            }
        ]
        selected = ts.select_tools(_ALL_TOOLS, state, messages)
        names = {_get_tool_name(t) for t in selected}
        assert "web_search" in names
        assert "web_reader" in names

    def test_apply_patch_on_multi_file_task(self):
        ts = ToolSelector()
        state = _make_state(turn=0)
        messages = [{"role": "user", "content": "refactor the module across files"}]
        selected = ts.select_tools(_ALL_TOOLS, state, messages)
        names = {_get_tool_name(t) for t in selected}
        assert "apply_patch" in names


# ---------------------------------------------------------------------------
# select_tools preserves order
# ---------------------------------------------------------------------------


class TestSelectToolsPreservesOrder:
    def test_order_preserved(self):
        ts = ToolSelector()
        state = _make_state(turn=0)
        selected = ts.select_tools(_ALL_TOOLS, state)
        names = [_get_tool_name(t) for t in selected]
        # Core tools should appear in same relative order as input
        core_names = [n for n in names if n in {"execute_bash", "think", "finish"}]
        assert core_names == ["execute_bash", "think", "finish"]
