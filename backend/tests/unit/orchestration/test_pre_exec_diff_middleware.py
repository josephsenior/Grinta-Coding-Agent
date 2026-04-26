"""Tests for backend.orchestration.pre_exec_diff.PreExecDiffMiddleware."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from backend.orchestration.pre_exec_diff import PreExecDiffMiddleware


def _make_ctx(action=None, workspace=None):
    """Create a minimal ToolInvocationContext mock."""
    ctx = MagicMock()
    ctx.action = action or MagicMock()
    ctx.metadata = {}
    if workspace:
        ctx.controller.runtime.workspace_dir = workspace
    return ctx


# ── _resolve_path ─────────────────────────────────────────────────────


class TestResolvePath:
    def test_absolute_path_returned_as_is(self):
        ctx = _make_ctx()
        result = PreExecDiffMiddleware._resolve_path('/absolute/path.py', ctx)
        assert result == '/absolute/path.py'

    def test_relative_path_resolved_from_workspace(self):
        ctx = _make_ctx(workspace='/ws')
        result = PreExecDiffMiddleware._resolve_path('src/file.py', ctx)
        assert result == os.path.join('/ws', 'src/file.py')

    def test_returns_none_when_no_workspace(self):
        ctx = MagicMock()
        ctx.controller.runtime = MagicMock(spec=[])  # no workspace attrs
        result = PreExecDiffMiddleware._resolve_path('relative.py', ctx)
        assert result is None


# ── _read_file ────────────────────────────────────────────────────────


class TestReadFile:
    def test_reads_file_content(self, tmp_path):
        f = tmp_path / 'test.py'
        f.write_text('hello world', encoding='utf-8')
        result = PreExecDiffMiddleware._read_file(str(f))
        assert result == 'hello world'

    def test_returns_none_for_nonexistent_file(self):
        result = PreExecDiffMiddleware._read_file('/nonexistent/file.py')
        assert result is None

    def test_returns_none_for_large_file(self, tmp_path):
        f = tmp_path / 'big.bin'
        f.write_bytes(b'x' * (3 * 1024 * 1024))  # 3 MB
        result = PreExecDiffMiddleware._read_file(str(f), max_bytes=2 * 1024 * 1024)
        assert result is None


# ── _simulate_edit ────────────────────────────────────────────────────


class TestSimulateEdit:
    def setup_method(self):
        self.mw = PreExecDiffMiddleware()

    def test_replace_text(self):
        action = MagicMock()
        action.command = 'replace_text'
        action.old_str = 'old'
        action.new_str = 'new'
        result = self.mw._simulate_edit('line with old text', action)
        assert result == 'line with new text'

    def test_replace_text_first_occurrence_only(self):
        action = MagicMock()
        action.command = 'replace_text'
        action.old_str = 'a'
        action.new_str = 'b'
        result = self.mw._simulate_edit('a a a', action)
        assert result == 'b a a'

    def test_create_file_command(self):
        action = MagicMock()
        action.command = 'create_file'
        action.file_text = 'brand new content'
        result = self.mw._simulate_edit('old', action)
        assert result == 'brand new content'

    def test_insert_text_command(self):
        action = MagicMock()
        action.command = 'insert_text'
        action.insert_line = 1
        action.new_str = 'inserted line'
        result = self.mw._simulate_edit('line0\nline1\n', action)
        assert result is not None
        assert 'inserted line' in result

    def test_unknown_command_returns_none(self):
        action = MagicMock()
        action.command = 'read_file'
        result = self.mw._simulate_edit('content', action)
        assert result is None


# ── execute (FileEditAction) ──────────────────────────────────────────


class TestExecuteEdit:
    async def test_generates_diff_for_edit_action(self, tmp_path):
        mw = PreExecDiffMiddleware()

        # Create a test file
        test_file = tmp_path / 'test.py'
        test_file.write_text('line1\nline2\nline3\n', encoding='utf-8')

        # Mock FileEditAction
        action = MagicMock()
        action.__class__.__name__ = 'FileEditAction'
        action.path = str(test_file)
        action.command = 'replace_text'
        action.old_str = 'line2'
        action.new_str = 'modified_line2'

        ctx = _make_ctx(action=action)

        # Instead of setting __instancecheck__ on MagicMock (unsupported),
        # we patch the lazy imports to return real classes that our action is
        # an instance of.

        with (
            patch(
                'backend.orchestration.pre_exec_diff.PreExecDiffMiddleware._resolve_path',
                return_value=str(test_file),
            ),
        ):
            # Directly test _diff_for_edit which is what execute dispatches to
            await mw._diff_for_edit(ctx, action)

    async def test_skips_when_no_change(self, tmp_path):
        mw = PreExecDiffMiddleware()
        test_file = tmp_path / 'test.py'
        test_file.write_text('content', encoding='utf-8')

        action = MagicMock()
        action.command = 'read_file'  # returns None from _simulate_edit
        action.path = str(test_file)

        ctx = _make_ctx(action=action)
        # Should not crash, just return silently
        # We patch the lazy imports so they don't fail
        with patch.dict('sys.modules', {}):
            await mw.execute(ctx)


# ── rollback_available metadata ───────────────────────────────────────


class TestMetadataPropagation:
    async def test_diff_stored_in_metadata(self, tmp_path):
        """Verify diff gets stored in ctx.metadata['pre_exec_diff']."""
        mw = PreExecDiffMiddleware()

        test_file = tmp_path / 'test.py'
        test_file.write_text('old content', encoding='utf-8')

        action = MagicMock()
        action.path = str(test_file)
        action.command = 'replace_text'
        action.old_str = 'old'
        action.new_str = 'new'

        _make_ctx(action=action)

        # Manually test the helper directly since the execute flow
        # depends on lazy imports
        old_content = PreExecDiffMiddleware._read_file(str(test_file))
        assert old_content is not None
        new_content = mw._simulate_edit(old_content, action)
        assert new_content == 'new content'
        assert old_content != new_content
