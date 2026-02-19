"""Unit tests for backend.controller.pre_exec_diff module.

Tests cover:
- PreExecDiffMiddleware initialization
- execute() method dispatch for different action types
- _diff_for_edit with various FileEditAction commands
- _diff_for_write for FileWriteAction
- _simulate_edit for str_replace, create, insert commands
- _resolve_path helper
- _read_file helper with size limits
"""

import os
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from backend.controller.pre_exec_diff import PreExecDiffMiddleware
from backend.events.action import CmdRunAction, FileEditAction, FileWriteAction


class TestPreExecDiffMiddlewareInit:
    """Test PreExecDiffMiddleware initialization."""

    def test_init_creates_middleware(self):
        """Should create middleware instance."""
        middleware = PreExecDiffMiddleware()

        assert middleware is not None
        assert isinstance(middleware, PreExecDiffMiddleware)


class TestExecuteMethod:
    """Test execute() middleware hook."""

    @pytest.mark.asyncio
    async def test_execute_ignores_non_file_actions(self):
        """execute should ignore actions that aren't FileEdit or FileWrite."""
        middleware = PreExecDiffMiddleware()
        action = CmdRunAction(command="ls -la")

        controller = MagicMock()
        state = MagicMock()
        ctx = MagicMock()
        ctx.action = action
        ctx.controller = controller
        ctx.state = state
        ctx.metadata = {}

        # Should not raise or add diff
        await middleware.execute(ctx)

        assert "pre_exec_diff" not in ctx.metadata

    @pytest.mark.asyncio
    async def test_execute_calls_diff_for_edit(self):
        """execute should call _diff_for_edit for FileEditAction."""
        middleware = PreExecDiffMiddleware()
        action = FileEditAction(
            path="test.txt",
            old_str="old",
            new_str="new",
            command="str_replace",
        )

        controller = MagicMock()
        state = MagicMock()
        ctx = MagicMock()
        ctx.action = action
        ctx.controller = controller
        ctx.state = state
        ctx.metadata = {}

        with patch.object(middleware, "_diff_for_edit", new=AsyncMock()) as mock_diff:
            await middleware.execute(ctx)
            mock_diff.assert_called_once_with(ctx, action)

    @pytest.mark.asyncio
    async def test_execute_calls_diff_for_write(self):
        """execute should call _diff_for_write for FileWriteAction."""
        middleware = PreExecDiffMiddleware()
        action = FileWriteAction(path="test.txt", content="new content")

        controller = MagicMock()
        state = MagicMock()
        ctx = MagicMock()
        ctx.action = action
        ctx.controller = controller
        ctx.state = state
        ctx.metadata = {}

        with patch.object(middleware, "_diff_for_write", new=AsyncMock()) as mock_diff:
            await middleware.execute(ctx)
            mock_diff.assert_called_once_with(ctx, action)


class TestDiffForEdit:
    """Test _diff_for_edit method."""

    @pytest.mark.asyncio
    async def test_diff_for_edit_nonexistent_file_returns_early(self):
        """Should return early if file doesn't exist."""
        middleware = PreExecDiffMiddleware()
        action = FileEditAction(
            path="/nonexistent/file.txt",
            old_str="old",
            new_str="new",
            command="str_replace",
        )

        controller = MagicMock()
        controller.runtime.workspace_dir = "/workspace"
        state = MagicMock()
        ctx = MagicMock()
        ctx.action = action
        ctx.controller = controller
        ctx.state = state
        ctx.metadata = {}

        await middleware._diff_for_edit(ctx, action)

        # Should not add diff for non-existent file
        assert "pre_exec_diff" not in ctx.metadata

    @pytest.mark.asyncio
    async def test_diff_for_edit_with_str_replace(self):
        """Should generate diff for str_replace command."""
        middleware = PreExecDiffMiddleware()
        action = FileEditAction(
            path="test.txt",
            old_str="old content",
            new_str="new content",
            command="str_replace",
        )

        controller = MagicMock()
        controller.runtime.workspace_dir = "/workspace"
        state = MagicMock()
        ctx = MagicMock()
        ctx.action = action
        ctx.controller = controller
        ctx.state = state
        ctx.metadata = {}

        with (
            patch.object(
                middleware, "_resolve_path", return_value="/workspace/test.txt"
            ),
            patch("os.path.isfile", return_value=True),
            patch.object(middleware, "_read_file", return_value="old content here"),
            patch(
                "backend.runtime.utils.diff.get_diff",
                return_value="- old content\\n+ new content",
            ),
        ):
            await middleware._diff_for_edit(ctx, action)

        assert "pre_exec_diff" in ctx.metadata
        assert (
            "old content" in ctx.metadata["pre_exec_diff"]
            or "new content" in ctx.metadata["pre_exec_diff"]
        )

    @pytest.mark.asyncio
    async def test_diff_for_edit_handles_exceptions(self):
        """Should handle exceptions gracefully."""
        middleware = PreExecDiffMiddleware()
        action = FileEditAction(
            path="test.txt",
            old_str="old",
            new_str="new",
            command="str_replace",
        )

        controller = MagicMock()
        state = MagicMock()
        ctx = MagicMock()
        ctx.action = action
        ctx.controller = controller
        ctx.state = state
        ctx.metadata = {}

        with patch.object(
            middleware, "_resolve_path", side_effect=RuntimeError("Test error")
        ):
            # Should not raise
            await middleware._diff_for_edit(ctx, action)

        assert "pre_exec_diff" not in ctx.metadata


class TestDiffForWrite:
    """Test _diff_for_write method."""

    @pytest.mark.asyncio
    async def test_diff_for_write_new_file(self):
        """Should generate diff for new file creation."""
        middleware = PreExecDiffMiddleware()
        action = FileWriteAction(path="newfile.txt", content="new content")

        controller = MagicMock()
        controller.runtime.workspace_dir = "/workspace"
        state = MagicMock()
        ctx = MagicMock()
        ctx.action = action
        ctx.controller = controller
        ctx.state = state
        ctx.metadata = {}

        with (
            patch.object(
                middleware, "_resolve_path", return_value="/workspace/newfile.txt"
            ),
            patch("os.path.isfile", return_value=False),
            patch(
                "backend.runtime.utils.diff.get_diff",
                return_value="+ new content",
            ),
        ):
            await middleware._diff_for_write(ctx, action)

        assert "pre_exec_diff" in ctx.metadata

    @pytest.mark.asyncio
    async def test_diff_for_write_existing_file(self):
        """Should generate diff for overwriting existing file."""
        middleware = PreExecDiffMiddleware()
        action = FileWriteAction(path="existing.txt", content="new content")

        controller = MagicMock()
        controller.runtime.workspace_dir = "/workspace"
        state = MagicMock()
        ctx = MagicMock()
        ctx.action = action
        ctx.controller = controller
        ctx.state = state
        ctx.metadata = {}

        with (
            patch.object(
                middleware, "_resolve_path", return_value="/workspace/existing.txt"
            ),
            patch("os.path.isfile", return_value=True),
            patch.object(middleware, "_read_file", return_value="old content"),
            patch(
                "backend.runtime.utils.diff.get_diff",
                return_value="- old content\\n+ new content",
            ),
        ):
            await middleware._diff_for_write(ctx, action)

        assert "pre_exec_diff" in ctx.metadata

    @pytest.mark.asyncio
    async def test_diff_for_write_identical_content_skips_diff(self):
        """Should skip diff if content is identical."""
        middleware = PreExecDiffMiddleware()
        action = FileWriteAction(path="file.txt", content="same content")

        controller = MagicMock()
        state = MagicMock()
        ctx = MagicMock()
        ctx.action = action
        ctx.controller = controller
        ctx.state = state
        ctx.metadata = {}

        with (
            patch.object(
                middleware, "_resolve_path", return_value="/workspace/file.txt"
            ),
            patch("os.path.isfile", return_value=True),
            patch.object(middleware, "_read_file", return_value="same content"),
        ):
            await middleware._diff_for_write(ctx, action)

        # Should not add diff for identical content
        assert "pre_exec_diff" not in ctx.metadata

    @pytest.mark.asyncio
    async def test_diff_for_write_handles_exceptions(self):
        """Should handle exceptions gracefully."""
        middleware = PreExecDiffMiddleware()
        action = FileWriteAction(path="file.txt", content="content")

        controller = MagicMock()
        state = MagicMock()
        ctx = MagicMock()
        ctx.action = action
        ctx.controller = controller
        ctx.state = state
        ctx.metadata = {}

        with patch.object(
            middleware, "_resolve_path", side_effect=RuntimeError("Test error")
        ):
            # Should not raise
            await middleware._diff_for_write(ctx, action)

        assert "pre_exec_diff" not in ctx.metadata


class TestSimulateEdit:
    """Test _simulate_edit method."""

    def test_simulate_edit_str_replace(self):
        """Should simulate str_replace command."""
        middleware = PreExecDiffMiddleware()
        action = MagicMock()
        action.command = "str_replace"
        action.old_str = "hello"
        action.new_str = "goodbye"

        old_content = "hello world"
        new_content = middleware._simulate_edit(old_content, action)

        assert new_content == "goodbye world"

    def test_simulate_edit_str_replace_once_only(self):
        """str_replace should replace only first occurrence."""
        middleware = PreExecDiffMiddleware()
        action = MagicMock()
        action.command = "str_replace"
        action.old_str = "cat"
        action.new_str = "dog"

        old_content = "cat cat cat"
        new_content = middleware._simulate_edit(old_content, action)

        assert new_content == "dog cat cat"

    def test_simulate_edit_create(self):
        """Should simulate create command."""
        middleware = PreExecDiffMiddleware()
        action = MagicMock()
        action.command = "create"
        action.file_text = "new file content"

        old_content = "old content"
        new_content = middleware._simulate_edit(old_content, action)

        assert new_content == "new file content"

    def test_simulate_edit_insert(self):
        """Should simulate insert command."""
        middleware = PreExecDiffMiddleware()
        action = MagicMock()
        action.command = "insert"
        action.insert_line = 1
        action.new_str = "inserted line"

        old_content = "line 0\\nline 1\\nline 2"
        new_content = middleware._simulate_edit(old_content, action)

        assert "inserted line" in new_content

    def test_simulate_edit_insert_at_end(self):
        """Should handle insert beyond last line."""
        middleware = PreExecDiffMiddleware()
        action = MagicMock()
        action.command = "insert"
        action.insert_line = 100  # Beyond end
        action.new_str = "appended line"

        old_content = "line 0\\nline 1"
        new_content = middleware._simulate_edit(old_content, action)

        assert "appended line" in new_content

    def test_simulate_edit_view_returns_none(self):
        """Should return None for view command (no edit)."""
        middleware = PreExecDiffMiddleware()
        action = MagicMock()
        action.command = "view"

        old_content = "content"
        new_content = middleware._simulate_edit(old_content, action)

        assert new_content is None

    def test_simulate_edit_unknown_command_returns_none(self):
        """Should return None for unknown commands."""
        middleware = PreExecDiffMiddleware()
        action = MagicMock()
        action.command = "unknown_command"

        old_content = "content"
        new_content = middleware._simulate_edit(old_content, action)

        assert new_content is None


class TestResolvePath:
    """Test _resolve_path static method."""

    def test_resolve_path_absolute_returns_as_is(self):
        """Should return absolute paths unchanged."""
        ctx = MagicMock()
        abs_path = "/absolute/path/to/file.txt"

        resolved = PreExecDiffMiddleware._resolve_path(abs_path, ctx)

        assert resolved == abs_path

    def test_resolve_path_relative_with_workspace(self):
        """Should join relative path with workspace directory."""
        ctx = MagicMock()
        ctx.controller.runtime.workspace_dir = "/workspace"

        resolved = PreExecDiffMiddleware._resolve_path("relative/file.txt", ctx)

        assert resolved == os.path.join("/workspace", "relative/file.txt")

    def test_resolve_path_relative_with_workspace_path(self):
        """Should try workspace_path if workspace_dir not available."""
        ctx = MagicMock()
        del ctx.controller.runtime.workspace_dir
        ctx.controller.runtime.workspace_path = "/workspace2"

        resolved = PreExecDiffMiddleware._resolve_path("file.txt", ctx)

        assert resolved == os.path.join("/workspace2", "file.txt")

    def test_resolve_path_no_workspace_returns_none(self):
        """Should return None if workspace cannot be determined."""
        ctx = MagicMock()
        ctx.controller.runtime = None

        resolved = PreExecDiffMiddleware._resolve_path("file.txt", ctx)

        assert resolved is None


class TestReadFile:
    """Test _read_file static method."""

    def test_read_file_success(self):
        """Should read file content successfully."""
        with (
            patch("builtins.open", mock_open(read_data="file content")),
            patch("os.path.getsize", return_value=100),
        ):
            content = PreExecDiffMiddleware._read_file("/path/to/file.txt")

        assert content == "file content"

    def test_read_file_too_large_returns_none(self):
        """Should return None if file is too large."""
        large_size = 10 * 1024 * 1024  # 10 MB > 2 MB limit
        with patch("os.path.getsize", return_value=large_size):
            content = PreExecDiffMiddleware._read_file("/path/to/large.txt")

        assert content is None

    def test_read_file_respects_max_bytes_param(self):
        """Should respect custom max_bytes parameter."""
        with patch("os.path.getsize", return_value=1000):
            content = PreExecDiffMiddleware._read_file(
                "/path/to/file.txt", max_bytes=500
            )

        # File is 1000 bytes but limit is 500, should return None
        assert content is None

    def test_read_file_handles_exceptions(self):
        """Should return None on read errors."""
        with patch("os.path.getsize", side_effect=OSError("File error")):
            content = PreExecDiffMiddleware._read_file("/path/to/file.txt")

        assert content is None

    def test_read_file_handles_decode_errors(self):
        """Should use error replacement for decode errors."""
        # Mock file with binary content that can't be decoded
        with (
            patch("builtins.open", mock_open(read_data="content")),
            patch("os.path.getsize", return_value=100),
        ):
            content = PreExecDiffMiddleware._read_file("/path/to/file.txt")

        # Should not raise, uses errors='replace'
        assert content is not None
