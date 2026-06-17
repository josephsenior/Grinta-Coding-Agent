"""Tests for backend.execution.utils.file_editor — FileEditor, ToolResult, ToolError."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from backend.core.type_safety.sentinels import MISSING
from backend.execution.utils.file_editor import FileEditor, ToolError, ToolResult

# ---------------------------------------------------------------------------
# ToolResult / ToolError
# ---------------------------------------------------------------------------


class TestToolResult:
    """Tests for the ToolResult dataclass."""

    def test_default_fields(self):
        tr = ToolResult(output='ok')
        assert tr.output == 'ok'
        assert tr.error is None
        assert tr.old_content is None
        assert tr.new_content is None

    def test_custom_fields(self):
        tr = ToolResult(output='done', error='oops', old_content='a', new_content='b')
        assert tr.error == 'oops'
        assert tr.old_content == 'a'


class TestToolError:
    """Tests for ToolError exception."""

    def test_message_attribute(self):
        err = ToolError('something broke')
        assert err.message == 'something broke'
        assert str(err) == 'something broke'

    def test_empty_message(self):
        err = ToolError()
        assert err.message == ''


# ---------------------------------------------------------------------------
# FileEditor — view
# ---------------------------------------------------------------------------


class TestFileEditorView:
    """Tests for the FileEditor view command."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.editor = FileEditor(workspace_root=self.tmpdir)

    def _write(self, name: str, content: str) -> Path:
        p = Path(self.tmpdir) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p

    def test_view_existing_file(self):
        self._write('hello.txt', 'line1\nline2\nline3\n')
        result = self.editor(command='read_file', path='hello.txt')
        assert result.error is None
        assert 'line1' in result.output
        assert 'line2' in result.output

    def test_view_with_line_numbers(self):
        self._write('nums.txt', 'a\nb\nc\nd\ne\n')
        result = self.editor(command='read_file', path='nums.txt')
        # Should have cat -n style numbering
        assert '1\t' in result.output

    def test_view_with_range(self):
        self._write('range.txt', 'a\nb\nc\nd\ne\n')
        result = self.editor(command='read_file', path='range.txt', view_range=[2, 4])
        assert result.error is None
        assert 'b' in result.output
        assert 'd' in result.output

    def test_view_nonexistent_file(self):
        result = self.editor(command='read_file', path='nope.txt')
        assert result.error is not None
        assert (
            'not found' in result.error.lower() or 'validation' in result.error.lower()
        )

    def test_view_directory_is_error(self):
        (Path(self.tmpdir) / 'subdir').mkdir()
        result = self.editor(command='read_file', path='subdir')
        assert result.error is None
        assert 'Directory contents' in result.output


# ---------------------------------------------------------------------------
# FileEditor — create_file
# ---------------------------------------------------------------------------


class TestFileEditorCreate:
    """Tests for the FileEditor create_file command."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.editor = FileEditor(workspace_root=self.tmpdir)

    def test_create_file_new_file(self):
        result = self.editor(
            command='create_file', path='new.txt', file_text='hello world'
        )
        assert result.error is None
        content = (Path(self.tmpdir) / 'new.txt').read_text()
        assert content == 'hello world'

    def test_create_file_command(self):
        result = self.editor(
            command='create_file', path='created.txt', file_text='data'
        )
        assert result.error is None

    def test_create_file_rejects_existing_without_overwrite(self):
        p = Path(self.tmpdir) / 'existing.txt'
        p.write_text('old')
        result = self.editor(
            command='create_file', path='existing.txt', file_text='new'
        )
        assert result.error is not None
        assert result.error_code == 'CREATE_FILE_ALREADY_EXISTS'
        assert p.read_text() == 'old'

    def test_create_file_dry_run(self):
        result = self.editor(
            command='create_file',
            path='dry.txt',
            file_text='content',
            dry_run=True,
        )
        assert result.error is None
        assert 'preview' in result.output.lower() or 'Preview' in result.output
        assert not (Path(self.tmpdir) / 'dry.txt').exists()

    def test_write_command_is_not_supported(self):
        result = self.editor(command='write', path='legacy.txt', file_text='data')
        assert result.error is not None
        assert 'Unknown command' in result.error

    def test_malformed_css_write_succeeds_with_warning(self, monkeypatch):
        # Default policy: post-write warning, never a pre-write veto. This is
        # the change that unsticks weaker models from the "retry the same
        # malformed file forever" loop. CSS with a stray semicolon between
        # the selector and opening brace is rejected by tree-sitter-css.
        monkeypatch.delenv('GRINTA_STRICT_WRITE_VALIDATION', raising=False)
        bad_css = '.btn {\n  display: flex;\\n    gap: 4px;\n}\n'
        result = self.editor(
            command='create_file', path='broken.css', file_text=bad_css
        )
        assert result.error is None
        assert (Path(self.tmpdir) / 'broken.css').exists()
        # The diagnostic is still surfaced so the agent can self-correct.
        assert 'WARNING' in result.output

    def test_malformed_css_write_vetoed_when_strict_env_set(self, monkeypatch):
        monkeypatch.setenv('GRINTA_STRICT_WRITE_VALIDATION', '1')
        bad_css = '.btn {\n  display: flex;\\n    gap: 4px;\n}\n'
        result = self.editor(
            command='create_file', path='broken.css', file_text=bad_css
        )
        assert result.error is not None
        assert 'Syntax validation failed' in result.error
        assert not (Path(self.tmpdir) / 'broken.css').exists()

    def test_python_double_slash_comment_is_rejected_preflight(self):
        bad_python = '// bad comment\nprint("ok")\n'
        result = self.editor(command='create_file', path='bad.py', file_text=bad_python)
        assert result.error is not None
        assert 'invalid Python comment prefix' in result.error
        assert not (Path(self.tmpdir) / 'bad.py').exists()

    def test_placeholder_example_content_is_rejected_preflight(self):
        result = self.editor(
            command='create_file',
            path='placeholder.py',
            file_text='# raw file content here\n',
        )
        assert result.error is not None
        assert 'Placeholder example content detected' in result.error
        assert not (Path(self.tmpdir) / 'placeholder.py').exists()

    def test_create_file_rejects_any_existing_file_without_overwrite_existing(self):
        existing = Path(self.tmpdir) / 'big.py'
        existing.write_text(''.join(f'line_{i} = {i}\n' for i in range(250)))
        result = self.editor(
            command='create_file',
            path='big.py',
            file_text='print("rewritten")\n',
            overwrite_existing=False,
        )
        assert result.error is not None
        assert result.error_code == 'CREATE_FILE_ALREADY_EXISTS'
        assert result.error == 'File already exists.'

    def test_create_file_overwrites_existing_file_when_overwrite_existing_is_true(self):
        existing = Path(self.tmpdir) / 'big.py'
        existing.write_text(''.join(f'line_{i} = {i}\n' for i in range(250)))
        result = self.editor(
            command='create_file',
            path='big.py',
            file_text='print("rewritten")\n',
            overwrite_existing=True,
        )
        assert result.error is None
        assert existing.read_text() == 'print("rewritten")\n'

    def test_create_file_rejects_obvious_serialized_payload(self):
        result = self.editor(
            command='create_file',
            path='serialized.py',
            file_text='"def hello():\\n    print(\\"hi\\")\\n"',
        )
        assert result.error is not None
        assert 'CONTENT_APPEARS_SERIALIZED' in result.error
        assert not (Path(self.tmpdir) / 'serialized.py').exists()

    def test_syntax_warning_includes_content_excerpt(self, monkeypatch):
        # Rich feedback: the WARNING text should carry a pointer-style excerpt
        # of the offending line so the model can patch without re-reading.
        monkeypatch.delenv('GRINTA_STRICT_WRITE_VALIDATION', raising=False)
        lines = [f'.class-{i} {{ color: red; }}' for i in range(1, 40)]
        lines[20] = '.bad { display: flex;\\n  gap: 4px; }'
        bad_css = '\n'.join(lines) + '\n'
        result = self.editor(
            command='create_file', path='excerpt.css', file_text=bad_css
        )
        assert result.error is None
        # If tree-sitter reports a line number (it almost always does for
        # this class of error), the excerpt block is appended. We assert
        # on the marker since exact line numbers depend on the parser.
        if 'Content context' in result.output:
            assert '>>' in result.output  # excerpt pointer
            assert '| ' in result.output  # line-number separator


# ---------------------------------------------------------------------------
# FileEditor — edit
# ---------------------------------------------------------------------------


class TestFileEditorEdit:
    """Tests for the FileEditor edit command."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.editor = FileEditor(workspace_root=self.tmpdir)

    def _write(self, name: str, content: str) -> Path:
        p = Path(self.tmpdir) / name
        p.write_text(content)
        return p

    def test_range_edit(self):
        self._write('code.py', 'x = 1\ny = 2\nz = 3\n')
        result = self.editor(
            command='edit',
            path='code.py',
            edit_mode='range',
            start_line=2,
            end_line=2,
            new_str='y = 42\n',
        )
        assert result.error is None
        content = (Path(self.tmpdir) / 'code.py').read_text()
        assert 'y = 42' in content

    def test_range_edit_blocks_syntax_regression(self):
        from backend.utils import treesitter_editor

        if not treesitter_editor.TREE_SITTER_AVAILABLE:
            pytest.skip('tree-sitter not installed')
        target = self._write('code.py', 'def ok():\n    return 1\n')

        result = self.editor(
            command='edit',
            path='code.py',
            edit_mode='range',
            start_line=1,
            end_line=1,
            new_str='def broken(\n',
        )

        assert result.error is not None
        assert result.error_code == 'INTRODUCED_SYNTAX_ERROR'
        assert target.read_text() == 'def ok():\n    return 1\n'

    def test_range_edit_blocks_python_compile_only_regression(self):
        target = self._write('code.py', 'def ok():\n    return 1\n')

        result = self.editor(
            command='edit',
            path='code.py',
            edit_mode='range',
            start_line=1,
            end_line=2,
            new_str='return 1\n',
        )

        assert result.error is not None
        assert result.error_code == 'INTRODUCED_SYNTAX_ERROR'
        assert "'return' outside function" in result.error
        assert target.read_text() == 'def ok():\n    return 1\n'

    def test_edit_dry_run(self):
        self._write('code.py', 'x = 1\n')
        result = self.editor(
            command='edit',
            path='code.py',
            edit_mode='range',
            start_line=1,
            end_line=1,
            new_str='x = 99\n',
            dry_run=True,
        )
        assert result.error is None
        # File should NOT be changed
        assert (Path(self.tmpdir) / 'code.py').read_text() == 'x = 1\n'

    def test_insert_at_line(self):
        self._write('insert.py', 'line1\nline2\nline3\n')
        result = self.editor(
            command='edit',
            path='insert.py',
            insert_line=2,
            new_str='inserted',
        )
        assert result.error is None
        content = (Path(self.tmpdir) / 'insert.py').read_text()
        assert 'inserted' in content

    def test_edit_requires_mode(self):
        self._write('code.py', 'x = 1\n')
        result = self.editor(
            command='edit',
            path='code.py',
            new_str='x = 9',
        )
        # Should fail because no mode (like range) is provided and old_str is gone
        assert result.error is not None

    def test_unknown_command(self):
        result = self.editor(command='delete', path='x.txt')
        assert result.error is not None


# ---------------------------------------------------------------------------
# FileEditor — replace_string
# ---------------------------------------------------------------------------


class TestFileEditorReplaceString:
    """Tests for exact string replacement."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.editor = FileEditor(workspace_root=self.tmpdir)

    def _write(self, name: str, content: str) -> Path:
        p = Path(self.tmpdir) / name
        p.write_text(content)
        return p

    def test_replaces_unique_exact_string(self):
        path = self._write('doc.md', 'alpha\nbeta\ngamma\n')
        result = self.editor(
            command='replace_string',
            path='doc.md',
            old_string='beta\n',
            new_str='BETA\n',
        )
        assert result.error is None
        assert path.read_text() == 'alpha\nBETA\ngamma\n'
        assert result.metadata['target_kind'] == 'exact_string'

    def test_inserts_by_replacing_anchor_with_anchor_plus_content(self):
        path = self._write('README.md', '## Usage\n\nold\n')
        result = self.editor(
            command='replace_string',
            path='README.md',
            old_string='## Usage\n',
            new_str='## Usage\n\nExample:\nrun grinta\n',
        )
        assert result.error is None
        assert path.read_text() == '## Usage\n\nExample:\nrun grinta\n\nold\n'

    def test_deletes_by_replacing_with_empty_string(self):
        path = self._write('config.txt', 'keep\nobsolete\nkeep2\n')
        result = self.editor(
            command='replace_string',
            path='config.txt',
            old_string='obsolete\n',
            new_str='',
        )
        assert result.error is None
        assert path.read_text() == 'keep\nkeep2\n'

    def test_rejects_missing_old_string(self):
        path = self._write('doc.md', 'alpha\n')
        result = self.editor(
            command='replace_string',
            path='doc.md',
            old_string='missing',
            new_str='x',
        )
        assert result.error is not None
        assert result.error_code == 'OLD_STRING_NOT_FOUND'
        assert path.read_text() == 'alpha\n'
        assert result.error == 'replace_string old_string was not found exactly.'

    def test_old_string_not_found_after_prior_edit_on_same_path(self):
        """A second ``replace_string`` on the same path after a prior edit
        should still report the same concise not-found error.
        """
        path = self._write('node.py', 'def foo():\n    return 1\n')

        first = self.editor(
            command='replace_string',
            path='node.py',
            old_string='def foo():\n    return 1\n',
            new_str='def foo():\n    return 2\n',
        )
        assert first.error is None
        assert path.read_text() == 'def foo():\n    return 2\n'

        # Model's old_string still references the pre-edit content.
        second = self.editor(
            command='replace_string',
            path='node.py',
            old_string='def foo():\n    return 1\n',
            new_str='def foo():\n    return 3\n',
        )
        assert second.error_code == 'OLD_STRING_NOT_FOUND'
        assert second.error == 'replace_string old_string was not found exactly.'
        assert path.read_text() == 'def foo():\n    return 2\n'

    def test_rejects_multiple_matches_without_replace_all(self):
        path = self._write('doc.md', 'x\nx\n')
        result = self.editor(
            command='replace_string',
            path='doc.md',
            old_string='x\n',
            new_str='y\n',
        )
        assert result.error is not None
        assert result.error_code == 'OLD_STRING_NOT_UNIQUE'
        assert path.read_text() == 'x\nx\n'

    def test_replace_all_replaces_every_exact_occurrence(self):
        path = self._write('doc.md', 'x\nx\n')
        result = self.editor(
            command='replace_string',
            path='doc.md',
            old_string='x\n',
            new_str='y\n',
            replace_all=True,
        )
        assert result.error is None
        assert path.read_text() == 'y\ny\n'

    def test_rejects_obvious_serialized_new_string(self):
        path = self._write('demo.py', 'def hello():\n    pass\n')
        result = self.editor(
            command='replace_string',
            path='demo.py',
            old_string='def hello():\n    pass\n',
            new_str='"def hello():\\n    print(\\"hi\\")\\n"',
        )
        assert result.error is not None
        assert 'CONTENT_APPEARS_SERIALIZED' in result.error
        assert path.read_text() == 'def hello():\n    pass\n'


# ---------------------------------------------------------------------------
# _extract_content
# ---------------------------------------------------------------------------


class TestExtractContent:
    """Tests for _extract_content."""

    def setup_method(self):
        self.editor = FileEditor()

    def test_file_text_preferred(self):
        result = self.editor._extract_content('hello', 'world')
        assert result == 'hello'

    def test_new_str_fallback(self):
        result = self.editor._extract_content(MISSING, 'world')
        assert result == 'world'

    def test_both_missing(self):
        result = self.editor._extract_content(MISSING, MISSING)
        assert result == ''

    def test_none_values(self):
        result = self.editor._extract_content(None, None)
        assert result == ''
