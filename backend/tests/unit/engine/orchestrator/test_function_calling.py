"""Tests for backend.engine.function_calling."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from backend.core.errors import (
    FunctionCallNotExistsError,
    FunctionCallValidationError,
)
from backend.engine.function_calling import (
    _handle_cmd_run_tool,
    _handle_edit_symbol_body_command,
    _handle_finish_tool,
    _handle_mcp_tool,
    _handle_str_replace_editor_tool,
    _handle_summarize_context_tool,
    _handle_task_tracker_tool,
    _handle_think_tool,
    _process_single_tool_call,
    combine_thought,
    set_security_risk,
)
from backend.ledger.action import (
    AgentThinkAction,
    CmdRunAction,
    FileEditAction,
    FileReadAction,
    MessageAction,
    PlaybookFinishAction,
    TaskTrackingAction,
)
from backend.ledger.action.agent import CondensationRequestAction
from backend.ledger.action.mcp import MCPAction


@pytest.fixture(autouse=True)
def _workspace_dir_for_task_tracker(tmp_path, monkeypatch):
    """Task tracker persistence now requires an explicit workspace root."""
    monkeypatch.setattr(
        "backend.core.workspace_resolution.require_effective_workspace_root",
        lambda: tmp_path,
    )
    return tmp_path


# ---------------------------------------------------------------------------
# combine_thought
# ---------------------------------------------------------------------------


class TestCombineThought:
    def test_sets_thought_when_empty(self):
        action = CmdRunAction(command="ls")
        cast(Any, action).thought = ""
        result = combine_thought(action, "new thought")
        assert cast(Any, result).thought == "new thought"

    def test_prepends_when_already_has_thought(self):
        action = CmdRunAction(command="ls")
        cast(Any, action).thought = "existing thought"
        result = combine_thought(action, "prefix")
        assert cast(Any, result).thought == "prefix\nexisting thought"

    def test_empty_thought_no_change(self):
        action = CmdRunAction(command="ls")
        cast(Any, action).thought = "existing"
        result = combine_thought(action, "")
        assert cast(Any, result).thought == "existing"

    def test_returns_action_unchanged_when_no_thought_attr(self):
        action = MagicMock(spec=[])  # no 'thought' attribute
        result = combine_thought(action, "some thought")
        assert result is action


# ---------------------------------------------------------------------------
# set_security_risk
# ---------------------------------------------------------------------------


class TestSetSecurityRisk:
    def test_sets_valid_risk_level(self):
        action = CmdRunAction(command="ls")
        set_security_risk(action, {"security_risk": "SAFE"})
        # Should not raise; SAFE may or may not be in RISK_LEVELS, no error

    def test_invalid_risk_level_logs_warning(self):
        action = CmdRunAction(command="ls")
        # Should not raise even with an invalid level
        with patch("backend.engine.function_calling.logger") as mock_log:
            set_security_risk(action, {"security_risk": "NUCLEAR"})
        mock_log.warning.assert_called_once()

    def test_no_security_risk_key_does_nothing(self):
        action = CmdRunAction(command="ls")
        original_risk = getattr(action, "security_risk", None)
        set_security_risk(action, {})
        assert getattr(action, "security_risk", None) == original_risk


# ---------------------------------------------------------------------------
# _handle_cmd_run_tool
# ---------------------------------------------------------------------------


class TestHandleCmdRunTool:
    def test_basic_command(self):
        action = _handle_cmd_run_tool({"command": "echo hello"})
        assert isinstance(action, CmdRunAction)
        assert action.command == "echo hello"

    def test_missing_command_raises(self):
        with pytest.raises(FunctionCallValidationError, match="command"):
            _handle_cmd_run_tool({})

    def test_timeout_set(self):
        action = _handle_cmd_run_tool({"command": "sleep 2", "timeout": "5.5"})
        assert isinstance(action, CmdRunAction)

    def test_invalid_timeout_raises(self):
        with pytest.raises(FunctionCallValidationError, match="timeout"):
            _handle_cmd_run_tool({"command": "echo", "timeout": "not-a-number"})

    def test_is_input_flag(self):
        action = _handle_cmd_run_tool({"command": "y", "is_input": "true"})
        assert action.is_input is True

    def test_is_input_false_default(self):
        action = _handle_cmd_run_tool({"command": "ls"})
        assert action.is_input is False


# ---------------------------------------------------------------------------
# _handle_finish_tool
# ---------------------------------------------------------------------------


class TestHandleFinishTool:
    def test_creates_playbook_finish_action(self):
        action = _handle_finish_tool({"message": "Done!"})
        assert isinstance(action, PlaybookFinishAction)
        assert action.final_thought == "Done!"

    def test_missing_message_raises(self):
        with pytest.raises(FunctionCallValidationError, match="message"):
            _handle_finish_tool({})


# ---------------------------------------------------------------------------
# _handle_str_replace_editor_tool
# ---------------------------------------------------------------------------


class TestHandleStrReplaceEditorTool:
    def test_canonical_read_file_command_returns_file_read_action(self):
        action = _handle_str_replace_editor_tool(
            {"command": "read_file", "path": "f.py"}
        )
        assert isinstance(action, FileReadAction)
        assert action.path == "f.py"

    def test_legacy_view_alias_is_rejected(self):
        with pytest.raises(FunctionCallValidationError, match="Unknown command"):
            _handle_str_replace_editor_tool({"command": "view", "path": "f.py"})

    def test_file_path_alias_is_rejected(self):
        with pytest.raises(FunctionCallValidationError, match="path"):
            _handle_str_replace_editor_tool(
                {"command": "read_file", "file_path": "f.py"}
            )

    def test_view_with_range(self):
        action = _handle_str_replace_editor_tool(
            {"command": "read_file", "path": "f.py", "view_range": [1, 10]}
        )
        assert isinstance(action, FileReadAction)

    def test_missing_command_raises(self):
        with pytest.raises(FunctionCallValidationError, match="command"):
            _handle_str_replace_editor_tool({"path": "f.py"})

    def test_missing_path_raises(self):
        with pytest.raises(FunctionCallValidationError, match="path"):
            _handle_str_replace_editor_tool({"command": "create_file"})

    def test_create_file_command_returns_file_edit_action(self):
        action = _handle_str_replace_editor_tool(
            {"command": "create_file", "path": "new.py", "file_text": "content"}
        )
        assert isinstance(action, FileEditAction)

    def test_unexpected_arg_raises(self):
        with pytest.raises(FunctionCallValidationError):
            _handle_str_replace_editor_tool(
                {
                    "command": "create_file",
                    "path": "x.py",
                    "totally_unknown_arg": "val",
                }
            )

    def test_view_and_replace_command_rejected(self, tmp_path):
        target = tmp_path / "sample.txt"
        target.write_text("hello world\n", encoding="utf-8")
        with pytest.raises(FunctionCallValidationError, match="Unknown command"):
            _handle_str_replace_editor_tool(
                {
                    "command": "view_and_replace",
                    "path": str(target),
                    "old_str": "world",
                    "new_str": "team",
                }
            )

    def test_batch_replace_command_rejected(self, tmp_path):
        target = tmp_path / "a.py"
        target.write_text("x\n", encoding="utf-8")
        with pytest.raises(FunctionCallValidationError, match="Unknown command"):
            _handle_str_replace_editor_tool(
                {
                    "command": "batch_replace",
                    "path": str(target),
                    "edits": [{"path": "a.py", "old_str": "x", "new_str": "y"}],
                }
            )

    def test_insert_text_preview_is_read_only_think_action(self, tmp_path):
        target = tmp_path / "sample.txt"
        target.write_text("alpha\nbeta\n", encoding="utf-8")
        action = _handle_str_replace_editor_tool(
            {
                "command": "insert_text",
                "path": str(target),
                "new_str": "gamma",
                "insert_line": 0,
                "preview": True,
            }
        )
        assert isinstance(action, AgentThinkAction)
        assert "dry-run" in action.thought
        assert target.read_text(encoding="utf-8") == "alpha\nbeta\n"


# ---------------------------------------------------------------------------
# _handle_think_tool
# ---------------------------------------------------------------------------


class TestHandleThinkTool:
    def test_creates_think_action(self):
        action = _handle_think_tool({"thought": "I should check the logs"})
        assert isinstance(action, AgentThinkAction)
        assert action.thought == "I should check the logs"

    def test_missing_thought_raises(self):
        with pytest.raises(FunctionCallValidationError, match="thought"):
            _handle_think_tool({})


# ---------------------------------------------------------------------------
# _handle_summarize_context_tool
# ---------------------------------------------------------------------------


class TestHandleCondensationRequestTool:
    def test_creates_condensation_request_action(self):
        action = _handle_summarize_context_tool({})
        assert isinstance(action, CondensationRequestAction)


# ---------------------------------------------------------------------------
# _handle_mcp_tool
# ---------------------------------------------------------------------------


class TestHandleMcpTool:
    def test_creates_mcp_action_with_dict_args(self):
        action = _handle_mcp_tool("my_mcp_tool", {"key": "value"})
        assert isinstance(action, MCPAction)
        assert action.name == "my_mcp_tool"
        assert action.arguments == {"key": "value"}

    def test_non_mapping_args_defaults_to_empty(self):
        action = _handle_mcp_tool("tool_x", None)
        assert isinstance(action, MCPAction)
        assert action.arguments == {}

    def test_mcp_action_with_empty_args(self):
        action = _handle_mcp_tool("my_tool", {})
        assert isinstance(action, MCPAction)
        assert action.arguments == {}


# ---------------------------------------------------------------------------
# _handle_task_tracker_tool
# ---------------------------------------------------------------------------


class TestHandleTaskTrackerTool:
    def test_update_command_with_task_list(self):
        args = {
            "command": "update",
            "task_list": [
                {"id": "task-1", "description": "Do X", "status": "todo"},
            ],
        }
        action = _handle_task_tracker_tool(args)
        assert isinstance(action, TaskTrackingAction)
        assert action.command == "update"
        assert len(action.task_list) == 1

    def test_missing_command_raises(self):
        with pytest.raises(FunctionCallValidationError, match="command"):
            _handle_task_tracker_tool({})

    def test_update_without_task_list_raises(self):
        with pytest.raises(FunctionCallValidationError, match="task_list"):
            _handle_task_tracker_tool({"command": "update"})

    def test_task_list_not_list_raises(self):
        with pytest.raises(FunctionCallValidationError):
            _handle_task_tracker_tool({"command": "update", "task_list": "not a list"})

    def test_task_item_not_dict_raises(self):
        with pytest.raises(FunctionCallValidationError):
            _handle_task_tracker_tool(
                {"command": "update", "task_list": ["not a dict"]}
            )

    def test_normalizes_missing_task_fields(self):
        args = {
            "command": "update",
            "task_list": [{"description": "My task"}],  # missing id, status
        }
        action = cast(TaskTrackingAction, _handle_task_tracker_tool(args))
        task = action.task_list[0]
        assert task["id"] == "step-1"
        assert task["status"] == "todo"

    def test_normalizes_canonical_task_fields(self):
        args = {
            "command": "update",
            "task_list": [
                {
                    "description": "Top level",
                    "status": "todo",
                    "result": "In progress note",
                    "subtasks": [{"description": "Child step", "status": "done"}],
                }
            ],
        }
        action = cast(TaskTrackingAction, _handle_task_tracker_tool(args))
        task = action.task_list[0]
        assert task["description"] == "Top level"
        assert task["status"] == "todo"
        assert task["result"] == "In progress note"
        assert task["subtasks"][0]["description"] == "Child step"
        assert task["subtasks"][0]["status"] == "done"

    @pytest.mark.parametrize("legacy_status", ["pending", "in_progress", "completed"])
    def test_rejects_legacy_task_status_aliases(self, legacy_status: str):
        args = {
            "command": "update",
            "task_list": [
                {"id": "1", "description": "Step 1", "status": legacy_status},
            ],
        }

        with pytest.raises(FunctionCallValidationError, match="Invalid task status"):
            _handle_task_tracker_tool(args)

    def test_non_plan_command_with_empty_task_list(self):
        args = {"command": "update", "task_list": []}
        action = cast(TaskTrackingAction, _handle_task_tracker_tool(args))
        assert action.command == "update"

    def test_duplicate_update_returns_noop_task_action(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APP_WORKSPACE_DIR", str(tmp_path))
        args = {
            "command": "update",
            "task_list": [{"id": "1", "description": "step", "status": "doing"}],
        }

        first = _handle_task_tracker_tool(args)
        assert isinstance(first, TaskTrackingAction)

        second = _handle_task_tracker_tool(args)
        assert isinstance(second, TaskTrackingAction)
        assert "unchanged" in second.thought.lower()


# ---------------------------------------------------------------------------
# _process_single_tool_call
# ---------------------------------------------------------------------------


class TestProcessSingleToolCall:
    def _make_tool_call(self, name: str, mcp_names=None):
        tc = MagicMock()
        tc.function.name = name
        tc._mcp_tool_names = mcp_names
        return tc

    def test_dispatches_cmd_run(self):
        from backend.engine.tools.bash import create_cmd_run_tool

        tool_name = create_cmd_run_tool()["function"]["name"]
        tc = self._make_tool_call(tool_name)
        action = _process_single_tool_call(tc, {"command": "ls"})
        assert isinstance(action, CmdRunAction)

    def test_dispatches_finish(self):
        from backend.engine.tools.finish import create_finish_tool

        tool_name = create_finish_tool()["function"]["name"]
        tc = self._make_tool_call(tool_name)
        action = _process_single_tool_call(tc, {"message": "done"})
        assert isinstance(action, PlaybookFinishAction)

    def test_dispatches_think(self):
        from backend.engine.tools.think import create_think_tool

        tool_name = create_think_tool()["function"]["name"]
        tc = self._make_tool_call(tool_name)
        action = _process_single_tool_call(tc, {"thought": "thinking"})
        assert isinstance(action, AgentThinkAction)

    def test_dispatches_mcp_tool(self):
        tc = self._make_tool_call("some_mcp_tool", mcp_names=["some_mcp_tool"])
        action = _process_single_tool_call(tc, {"key": "val"})
        assert isinstance(action, MCPAction)

    def test_unknown_tool_raises(self):
        tc = self._make_tool_call("definitely_unknown_tool_xyz")
        with pytest.raises(FunctionCallNotExistsError):
            _process_single_tool_call(tc, {})

    def test_unknown_tool_not_in_mcp_list_raises(self):
        tc = self._make_tool_call("other_tool", mcp_names=["some_mcp_tool"])
        with pytest.raises(FunctionCallNotExistsError):
            _process_single_tool_call(tc, {})


# ---------------------------------------------------------------------------
# _validate_structure_editor_args (via _handle_ast_code_editor_tool)
# ---------------------------------------------------------------------------


class TestValidateStructureEditorArgs:
    """Tests for missing command / path validation."""

    def test_missing_command_raises(self):
        from backend.engine.function_calling import _handle_ast_code_editor_tool

        with pytest.raises(FunctionCallValidationError, match="command"):
            _handle_ast_code_editor_tool({"file_path": "x.py"})

    def test_missing_path_raises(self):
        from backend.engine.function_calling import _handle_ast_code_editor_tool

        with pytest.raises(FunctionCallValidationError, match="path"):
            _handle_ast_code_editor_tool({"command": "edit_symbol_body"})

    def test_canonical_path_with_read_file_command(self):
        from backend.engine.function_calling import _handle_ast_code_editor_tool

        result = _handle_ast_code_editor_tool(
            {
                "command": "read_file",
                "path": "x.py",
            }
        )
        assert isinstance(result, FileReadAction)
        assert result.path == "x.py"

    def test_ast_replace_text_command_rejected(self):
        from backend.engine.function_calling import _handle_ast_code_editor_tool

        with pytest.raises(FunctionCallValidationError, match="Unknown command"):
            _handle_ast_code_editor_tool(
                {
                    "command": "replace_text",
                    "path": "x.py",
                    "old_str": "old",
                    "new_str": "new",
                }
            )

    def test_unknown_command_raises_validation_error(self):
        from backend.engine.function_calling import _handle_ast_code_editor_tool

        with pytest.raises(FunctionCallValidationError, match="Unknown command"):
            _handle_ast_code_editor_tool(
                {"command": "totally_unknown_cmd", "path": "x.py"}
            )

    def test_str_replace_alias_is_rejected(self):
        from backend.engine.function_calling import _handle_ast_code_editor_tool

        with pytest.raises(FunctionCallValidationError, match="Unknown command"):
            _handle_ast_code_editor_tool(
                {
                    "command": "str_replace",
                    "path": "x.py",
                    "old_str": "old",
                    "new_str": "new",
                }
            )


class TestEditSymbolsBatch:
    def test_edit_symbols_applies_multiple(self, tmp_path):
        from backend.engine.function_calling import _handle_ast_code_editor_tool

        py = tmp_path / "m.py"
        py.write_text(
            "def a():\n    return 1\n\ndef b():\n    return 2\n",
            encoding="utf-8",
        )
        result = _handle_ast_code_editor_tool(
            {
                "command": "edit_symbols",
                "path": str(py),
                "edits": [
                    {"function_name": "a", "new_body": "    return 10"},
                    {"symbol": "b", "new_body": "    return 20"},
                ],
            }
        )
        from backend.ledger.action import FileReadAction

        assert isinstance(result, FileReadAction)
        assert result.thought is not None
        assert "10" in py.read_text(encoding="utf-8")
        assert "20" in py.read_text(encoding="utf-8")

    def test_edit_symbols_restores_on_failure(self, tmp_path):
        from backend.engine.function_calling import _handle_ast_code_editor_tool

        original = "def a():\n    return 1\n\ndef b():\n    return 2\n"
        py = tmp_path / "m.py"
        py.write_text(original, encoding="utf-8")
        result = _handle_ast_code_editor_tool(
            {
                "command": "edit_symbols",
                "path": str(py),
                "edits": [
                    {"function_name": "a", "new_body": "    return 99"},
                    {"function_name": "nope_not_a_symbol", "new_body": "    pass"},
                ],
            }
        )
        from backend.ledger.action import MessageAction

        assert isinstance(result, MessageAction)
        assert py.read_text(encoding="utf-8") == original

    def test_edit_symbols_rejects_duplicate_symbols(self, tmp_path):
        from backend.engine.function_calling import _handle_ast_code_editor_tool

        py = tmp_path / "m.py"
        py.write_text("def a():\n    return 1\n", encoding="utf-8")
        with pytest.raises(FunctionCallValidationError, match="duplicate"):
            _handle_ast_code_editor_tool(
                {
                    "command": "edit_symbols",
                    "path": str(py),
                    "edits": [
                        {"function_name": "a", "new_body": "    return 2"},
                        {"symbol": "a", "new_body": "    return 3"},
                    ],
                }
            )


# ---------------------------------------------------------------------------
# _handle_edit_symbol_body_command (imported directly)
# ---------------------------------------------------------------------------


class TestHandleEditFunctionCommand:
    def _make_editor(self, success=True, message="ok"):
        editor = MagicMock()
        result = MagicMock()
        result.success = success
        result.message = message
        editor.edit_function.return_value = result
        return editor

    def test_success_returns_file_read_action(self):
        editor = self._make_editor(success=True)
        result = _handle_edit_symbol_body_command(
            editor, "foo.py", {"function_name": "my_fn", "new_body": "return 1"}
        )
        assert isinstance(result, FileReadAction)

    def test_failure_returns_message_action(self):
        editor = self._make_editor(success=False, message="parse error")
        result = _handle_edit_symbol_body_command(
            editor, "foo.py", {"function_name": "my_fn", "new_body": "return 1"}
        )
        assert isinstance(result, MessageAction)
        assert "parse error" in result.content

    def test_missing_function_name_raises(self):
        with pytest.raises(FunctionCallValidationError, match="function_name"):
            _handle_edit_symbol_body_command(
                MagicMock(), "foo.py", {"new_body": "return 1"}
            )

    def test_missing_new_body_raises(self):
        with pytest.raises(FunctionCallValidationError, match="new_body"):
            _handle_edit_symbol_body_command(
                MagicMock(), "foo.py", {"function_name": "fn"}
            )


# ---------------------------------------------------------------------------
# _handle_rename_symbol_command
# ---------------------------------------------------------------------------


class TestHandleRenameSymbolCommand:
    def _make_editor(self, success=True, message="renamed"):
        editor = MagicMock()
        result = MagicMock()
        result.success = success
        result.message = message
        editor.rename_symbol.return_value = result
        return editor

    def test_success_returns_file_read_action(self):
        from backend.engine.function_calling import _handle_rename_symbol_command

        editor = self._make_editor(success=True)
        result = _handle_rename_symbol_command(
            editor, "f.py", {"old_name": "foo", "new_name": "bar"}
        )
        assert isinstance(result, FileReadAction)

    def test_failure_returns_message_action(self):
        from backend.engine.function_calling import _handle_rename_symbol_command

        editor = self._make_editor(success=False, message="not found")
        result = _handle_rename_symbol_command(
            editor, "f.py", {"old_name": "foo", "new_name": "bar"}
        )
        assert isinstance(result, MessageAction)
        assert "not found" in result.content

    def test_missing_old_name_raises(self):
        from backend.engine.function_calling import _handle_rename_symbol_command

        with pytest.raises(FunctionCallValidationError):
            _handle_rename_symbol_command(MagicMock(), "f.py", {"new_name": "bar"})

    def test_missing_new_name_raises(self):
        from backend.engine.function_calling import _handle_rename_symbol_command

        with pytest.raises(FunctionCallValidationError):
            _handle_rename_symbol_command(MagicMock(), "f.py", {"old_name": "foo"})


# ---------------------------------------------------------------------------
# _handle_find_symbol_command
# ---------------------------------------------------------------------------


class TestHandleFindSymbolCommand:
    def test_found_symbol_returns_message_with_info(self):
        from backend.engine.function_calling import _handle_find_symbol_command

        editor = MagicMock()
        sym = MagicMock()
        sym.node_type = "function"
        sym.line_start = 10
        sym.line_end = 20
        sym.parent_name = "MyClass"
        editor.find_symbol.return_value = sym
        result = _handle_find_symbol_command(editor, "f.py", {"symbol_name": "my_fn"})
        assert isinstance(result, MessageAction)
        assert "my_fn" in result.content

    def test_not_found_returns_not_found_message(self):
        from backend.engine.function_calling import _handle_find_symbol_command

        editor = MagicMock()
        editor.find_symbol.return_value = None
        result = _handle_find_symbol_command(editor, "f.py", {"symbol_name": "ghost"})
        assert isinstance(result, MessageAction)
        assert "not found" in result.content.lower()

    def test_missing_symbol_name_raises(self):
        from backend.engine.function_calling import _handle_find_symbol_command

        with pytest.raises(FunctionCallValidationError, match="symbol_name"):
            _handle_find_symbol_command(MagicMock(), "f.py", {})

    def test_found_symbol_without_parent_omits_parent_line(self):
        from backend.engine.function_calling import _handle_find_symbol_command

        editor = MagicMock()
        sym = MagicMock()
        sym.node_type = "class"
        sym.line_start = 1
        sym.line_end = 5
        sym.parent_name = None
        editor.find_symbol.return_value = sym
        result = _handle_find_symbol_command(editor, "f.py", {"symbol_name": "Klass"})
        assert "Parent" not in cast(Any, result).content


# ---------------------------------------------------------------------------
# _handle_replace_range_command
# ---------------------------------------------------------------------------


class TestHandleReplaceRangeCommand:
    def _make_editor(self, success=True):
        editor = MagicMock()
        r = MagicMock()
        r.success = success
        r.message = "replaced" if success else "error"
        editor.replace_code_range.return_value = r
        return editor

    def test_success_returns_file_read_action(self):
        from backend.engine.function_calling import _handle_replace_range_command

        editor = self._make_editor(success=True)
        result = _handle_replace_range_command(
            editor, "f.py", {"start_line": 1, "end_line": 5, "new_code": "pass"}
        )
        assert isinstance(result, FileReadAction)

    def test_failure_returns_message_action(self):
        from backend.engine.function_calling import _handle_replace_range_command

        editor = self._make_editor(success=False)
        result = _handle_replace_range_command(
            editor, "f.py", {"start_line": 1, "end_line": 5, "new_code": "pass"}
        )
        assert isinstance(result, MessageAction)

    def test_missing_start_line_raises(self):
        from backend.engine.function_calling import _handle_replace_range_command

        with pytest.raises(FunctionCallValidationError, match="start_line"):
            _handle_replace_range_command(
                MagicMock(), "f.py", {"end_line": 5, "new_code": "x"}
            )

    def test_missing_new_code_raises(self):
        from backend.engine.function_calling import _handle_replace_range_command

        with pytest.raises(FunctionCallValidationError):
            _handle_replace_range_command(
                MagicMock(), "f.py", {"start_line": 1, "end_line": 5}
            )


# ---------------------------------------------------------------------------
# _handle_normalize_indent_command
# ---------------------------------------------------------------------------


class TestHandleNormalizeIndentCommand:
    def _make_editor(self, success=True):
        editor = MagicMock()
        r = MagicMock()
        r.success = success
        r.message = "ok" if success else "fail"
        editor.normalize_file_indent.return_value = r
        return editor

    def test_success_returns_file_read_action(self):
        from backend.engine.function_calling import _handle_normalize_indent_command

        editor = self._make_editor(success=True)
        result = _handle_normalize_indent_command(
            editor, "f.py", {"style": "spaces", "size": 4}
        )
        assert isinstance(result, FileReadAction)

    def test_failure_returns_message_action(self):
        from backend.engine.function_calling import _handle_normalize_indent_command

        editor = self._make_editor(success=False)
        result = _handle_normalize_indent_command(editor, "f.py", {})
        assert isinstance(result, MessageAction)


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    def test_run_production_health_check_returns_dict(self):
        from backend.engine.tools.health_check import run_production_health_check

        result = run_production_health_check(raise_on_failure=False)
        assert isinstance(result, dict)
        assert "overall_status" in result

    def test_ultimate_editor_check_present(self):
        from backend.engine.tools.health_check import run_production_health_check

        result = run_production_health_check(raise_on_failure=False)
        assert "edit_code" in result

    def test_atomic_refactor_check_present(self):
        from backend.engine.tools.health_check import run_production_health_check

        result = run_production_health_check(raise_on_failure=False)
        assert "atomic_refactor" in result

    def test_check_structure_editor_returns_bool_and_str(self):
        from backend.engine.tools.health_check import (
            check_structure_editor_dependencies,
        )

        success, msg = check_structure_editor_dependencies()
        assert isinstance(success, bool)
        assert isinstance(msg, str)

    def test_check_atomic_refactor_returns_bool_and_str(self):
        from backend.engine.tools.health_check import check_atomic_refactor_dependencies

        success, msg = check_atomic_refactor_dependencies()
        assert isinstance(success, bool)
        assert isinstance(msg, str)

    def test_no_critical_failures_means_healthy(self):
        from backend.engine.tools.health_check import run_production_health_check

        with (
            patch(
                "backend.engine.tools.health_check.check_structure_editor_dependencies",
                return_value=(True, "ok"),
            ),
            patch(
                "backend.engine.tools.health_check.check_atomic_refactor_dependencies",
                return_value=(True, "ok"),
            ),
        ):
            result = run_production_health_check(raise_on_failure=False)
        assert result["overall_status"] == "HEALTHY"

    def test_critical_failure_raises_when_requested(self):
        from backend.engine.tools.health_check import run_production_health_check

        with (
            patch(
                "backend.engine.tools.health_check.check_structure_editor_dependencies",
                return_value=(False, "missing"),
            ),
            patch(
                "backend.engine.tools.health_check.check_atomic_refactor_dependencies",
                return_value=(True, "ok"),
            ),
        ):
            with pytest.raises(RuntimeError, match="health check failed"):
                run_production_health_check(raise_on_failure=True)

    def test_critical_failure_no_raise_returns_critical(self):
        from backend.engine.tools.health_check import run_production_health_check

        with (
            patch(
                "backend.engine.tools.health_check.check_structure_editor_dependencies",
                return_value=(False, "missing"),
            ),
            patch(
                "backend.engine.tools.health_check.check_atomic_refactor_dependencies",
                return_value=(True, "ok"),
            ),
        ):
            result = run_production_health_check(raise_on_failure=False)
        assert result["overall_status"] == "CRITICAL_FAILURE"
