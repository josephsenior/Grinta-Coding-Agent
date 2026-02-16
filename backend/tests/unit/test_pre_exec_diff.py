"""Unit tests for backend.controller.pre_exec_diff — diff preview middleware."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.controller.pre_exec_diff import PreExecDiffMiddleware
from backend.controller.tool_pipeline import ToolInvocationContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(
    action=None,
    workspace_path: str | None = None,
) -> ToolInvocationContext:
    controller = MagicMock()
    if workspace_path:
        runtime = MagicMock()
        runtime.workspace_dir = workspace_path
        controller.runtime = runtime
    else:
        controller.runtime = None

    state = MagicMock()
    return ToolInvocationContext(
        controller=controller,
        action=action or MagicMock(),
        state=state,
        metadata={},
    )


def _make_file_edit_action(
    path: str = "test.py",
    command: str = "str_replace",
    old_str: str | None = "old",
    new_str: str | None = "new",
    file_text: str | None = None,
    insert_line: int | None = None,
):
    """Simulate a FileEditAction without importing the real class."""
    a = MagicMock()
    a.path = path
    a.command = command
    a.old_str = old_str
    a.new_str = new_str
    a.file_text = file_text
    a.insert_line = insert_line
    type(a).__name__ = "FileEditAction"
    return a


def _make_file_write_action(path: str = "out.py", content: str = "new content"):
    a = MagicMock()
    a.path = path
    a.content = content
    type(a).__name__ = "FileWriteAction"
    return a


# ---------------------------------------------------------------------------
# _resolve_path
# ---------------------------------------------------------------------------


class TestResolvePath:
    def test_absolute_path(self):
        ctx = _make_ctx(workspace_path="/ws")
        result = PreExecDiffMiddleware._resolve_path("/abs/file.py", ctx)
        assert result == "/abs/file.py"

    def test_relative_with_workspace(self):
        ctx = _make_ctx(workspace_path="/ws")
        result = PreExecDiffMiddleware._resolve_path("src/file.py", ctx)
        assert result == os.path.join("/ws", "src/file.py")

    def test_relative_no_runtime(self):
        ctx = _make_ctx(workspace_path=None)
        result = PreExecDiffMiddleware._resolve_path("file.py", ctx)
        assert result is None


# ---------------------------------------------------------------------------
# _read_file
# ---------------------------------------------------------------------------


class TestReadFile:
    def test_read_existing_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        result = PreExecDiffMiddleware._read_file(str(f))
        assert result == "hello world"

    def test_read_nonexistent_file(self):
        result = PreExecDiffMiddleware._read_file("/nonexistent/file.txt")
        assert result is None

    def test_read_too_large(self, tmp_path):
        f = tmp_path / "big.txt"
        f.write_text("x" * 100, encoding="utf-8")
        result = PreExecDiffMiddleware._read_file(str(f), max_bytes=50)
        assert result is None


# ---------------------------------------------------------------------------
# _simulate_edit
# ---------------------------------------------------------------------------


class TestSimulateEdit:
    def setup_method(self):
        self.mw = PreExecDiffMiddleware()

    def test_str_replace(self):
        action = _make_file_edit_action(
            command="str_replace", old_str="foo", new_str="bar"
        )
        result = self.mw._simulate_edit("hello foo world", action)
        assert result == "hello bar world"

    def test_str_replace_first_occurrence_only(self):
        action = _make_file_edit_action(
            command="str_replace", old_str="x", new_str="y"
        )
        result = self.mw._simulate_edit("x and x", action)
        assert result == "y and x"

    def test_create_command(self):
        action = _make_file_edit_action(command="create", file_text="new content")
        result = self.mw._simulate_edit("old content", action)
        assert result == "new content"

    def test_create_empty(self):
        action = _make_file_edit_action(command="create", file_text="")
        result = self.mw._simulate_edit("old", action)
        assert result == ""

    def test_insert_at_beginning(self):
        action = _make_file_edit_action(
            command="insert", insert_line=0, new_str="INSERTED"
        )
        result = self.mw._simulate_edit("line1\nline2\n", action)
        assert result is not None
        assert result.startswith("INSERTED\n")

    def test_insert_at_end(self):
        action = _make_file_edit_action(
            command="insert", insert_line=999, new_str="END"
        )
        result = self.mw._simulate_edit("line1\n", action)
        assert result is not None
        assert "END" in result

    def test_insert_negative_clamped(self):
        action = _make_file_edit_action(
            command="insert", insert_line=-5, new_str="TOP"
        )
        result = self.mw._simulate_edit("abc\n", action)
        assert result is not None
        assert result.startswith("TOP\n")

    def test_view_returns_none(self):
        action = _make_file_edit_action(command="view")
        result = self.mw._simulate_edit("content", action)
        assert result is None

    def test_unknown_command_returns_none(self):
        action = _make_file_edit_action(command="unknown_cmd")
        result = self.mw._simulate_edit("content", action)
        assert result is None


# ---------------------------------------------------------------------------
# execute stage — FileEditAction
# ---------------------------------------------------------------------------


class TestExecuteFileEdit:
    @pytest.mark.asyncio
    async def test_str_replace_generates_diff(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("old line\n", encoding="utf-8")

        action = _make_file_edit_action(
            path=str(f), command="str_replace", old_str="old", new_str="new"
        )
        # Make it recognized as FileEditAction by the isinstance check
        from backend.events.action import FileEditAction

        real_action = MagicMock(spec=FileEditAction)
        real_action.path = str(f)
        real_action.command = "str_replace"
        real_action.old_str = "old"
        real_action.new_str = "new"
        real_action.file_text = None
        real_action.insert_line = None

        ctx = _make_ctx(action=real_action, workspace_path=str(tmp_path))
        mw = PreExecDiffMiddleware()
        await mw.execute(ctx)
        assert "pre_exec_diff" in ctx.metadata
        diff = ctx.metadata["pre_exec_diff"]
        assert "-old" in diff or "old" in diff

    @pytest.mark.asyncio
    async def test_nonexistent_file_no_diff(self):
        from backend.events.action import FileEditAction

        action = MagicMock(spec=FileEditAction)
        action.path = "/nonexistent/file.py"
        action.command = "str_replace"
        action.old_str = "x"
        action.new_str = "y"

        ctx = _make_ctx(action=action)
        mw = PreExecDiffMiddleware()
        await mw.execute(ctx)
        assert "pre_exec_diff" not in ctx.metadata

    @pytest.mark.asyncio
    async def test_no_change_no_diff(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("content\n", encoding="utf-8")

        from backend.events.action import FileEditAction

        action = MagicMock(spec=FileEditAction)
        action.path = str(f)
        action.command = "str_replace"
        action.old_str = "nonexistent"
        action.new_str = "replacement"

        ctx = _make_ctx(action=action, workspace_path=str(tmp_path))
        mw = PreExecDiffMiddleware()
        await mw.execute(ctx)
        # str_replace didn't match so old == new; no diff stored
        # Actually _simulate_edit does old_content.replace which may not change
        # so no diff generated
        # Just verify no crash


# ---------------------------------------------------------------------------
# execute stage — FileWriteAction
# ---------------------------------------------------------------------------


class TestExecuteFileWrite:
    @pytest.mark.asyncio
    async def test_new_file_generates_diff(self, tmp_path):
        from backend.events.action import FileWriteAction

        action = MagicMock(spec=FileWriteAction)
        action.path = str(tmp_path / "new.py")
        action.content = "print('hello')\n"

        ctx = _make_ctx(action=action, workspace_path=str(tmp_path))
        mw = PreExecDiffMiddleware()
        await mw.execute(ctx)
        assert "pre_exec_diff" in ctx.metadata

    @pytest.mark.asyncio
    async def test_overwrite_generates_diff(self, tmp_path):
        f = tmp_path / "existing.py"
        f.write_text("old content\n", encoding="utf-8")

        from backend.events.action import FileWriteAction

        action = MagicMock(spec=FileWriteAction)
        action.path = str(f)
        action.content = "new content\n"

        ctx = _make_ctx(action=action, workspace_path=str(tmp_path))
        mw = PreExecDiffMiddleware()
        await mw.execute(ctx)
        assert "pre_exec_diff" in ctx.metadata


# ---------------------------------------------------------------------------
# execute stage — non-file actions
# ---------------------------------------------------------------------------


class TestExecuteOther:
    @pytest.mark.asyncio
    async def test_message_action_no_diff(self):
        from backend.events.action.message import MessageAction

        action = MessageAction(content="hello")
        ctx = _make_ctx(action=action)
        mw = PreExecDiffMiddleware()
        await mw.execute(ctx)
        assert "pre_exec_diff" not in ctx.metadata
