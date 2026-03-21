"""Tests for backend.runtime.utils.file_editor — FileEditor, ToolResult, ToolError."""

from __future__ import annotations

import tempfile
from pathlib import Path


from backend.runtime.utils.file_editor import FileEditor, ToolError, ToolResult
from backend.core.type_safety.sentinels import MISSING


# ---------------------------------------------------------------------------
# ToolResult / ToolError
# ---------------------------------------------------------------------------


class TestToolResult:
    """Tests for the ToolResult dataclass."""

    def test_default_fields(self):
        tr = ToolResult(output="ok")
        assert tr.output == "ok"
        assert tr.error is None
        assert tr.old_content is None
        assert tr.new_content is None

    def test_custom_fields(self):
        tr = ToolResult(output="done", error="oops", old_content="a", new_content="b")
        assert tr.error == "oops"
        assert tr.old_content == "a"


class TestToolError:
    """Tests for ToolError exception."""

    def test_message_attribute(self):
        err = ToolError("something broke")
        assert err.message == "something broke"
        assert str(err) == "something broke"

    def test_empty_message(self):
        err = ToolError()
        assert err.message == ""


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
        self._write("hello.txt", "line1\nline2\nline3\n")
        result = self.editor(command="view_file", path="hello.txt")
        assert result.error is None
        assert "line1" in result.output
        assert "line2" in result.output

    def test_view_with_line_numbers(self):
        self._write("nums.txt", "a\nb\nc\nd\ne\n")
        result = self.editor(command="view_file", path="nums.txt")
        # Should have cat -n style numbering
        assert "1\t" in result.output

    def test_view_with_range(self):
        self._write("range.txt", "a\nb\nc\nd\ne\n")
        result = self.editor(
            command="view_file", path="range.txt", view_range=[2, 4]
        )
        assert result.error is None
        assert "b" in result.output
        assert "d" in result.output

    def test_view_nonexistent_file(self):
        result = self.editor(command="view_file", path="nope.txt")
        assert result.error is not None
        assert (
            "not found" in result.error.lower() or "validation" in result.error.lower()
        )

    def test_view_directory_is_error(self):
        (Path(self.tmpdir) / "subdir").mkdir()
        result = self.editor(command="view_file", path="subdir")
        assert result.error is not None


# ---------------------------------------------------------------------------
# FileEditor — write / create
# ---------------------------------------------------------------------------


class TestFileEditorWrite:
    """Tests for the FileEditor write/create commands."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.editor = FileEditor(workspace_root=self.tmpdir)

    def test_write_new_file(self):
        result = self.editor(command="write", path="new.txt", file_text="hello world")
        assert result.error is None
        content = (Path(self.tmpdir) / "new.txt").read_text()
        assert content == "hello world"

    def test_create_file_command(self):
        result = self.editor(
            command="create_file", path="created.txt", file_text="data"
        )
        assert result.error is None

    def test_write_overwrites(self):
        p = Path(self.tmpdir) / "existing.txt"
        p.write_text("old")
        result = self.editor(command="write", path="existing.txt", file_text="new")
        assert result.error is None
        assert p.read_text() == "new"

    def test_write_dry_run(self):
        result = self.editor(
            command="write", path="dry.txt", file_text="content", dry_run=True
        )
        assert result.error is None
        assert "preview" in result.output.lower() or "Preview" in result.output
        # File should not actually be created
        assert not (Path(self.tmpdir) / "dry.txt").exists()


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

    def test_str_replace(self):
        self._write("code.py", "x = 1\ny = 2\nz = 3\n")
        result = self.editor(
            command="edit",
            path="code.py",
            old_str="y = 2",
            new_str="y = 42",
        )
        assert result.error is None
        content = (Path(self.tmpdir) / "code.py").read_text()
        assert "y = 42" in content

    def test_edit_dry_run(self):
        self._write("code.py", "x = 1\n")
        result = self.editor(
            command="edit",
            path="code.py",
            old_str="x = 1",
            new_str="x = 99",
            dry_run=True,
        )
        assert result.error is None
        # File should NOT be changed
        assert (Path(self.tmpdir) / "code.py").read_text() == "x = 1\n"

    def test_insert_at_line(self):
        self._write("insert.py", "line1\nline2\nline3\n")
        result = self.editor(
            command="edit",
            path="insert.py",
            insert_line=2,
            new_str="inserted",
        )
        assert result.error is None
        content = (Path(self.tmpdir) / "insert.py").read_text()
        assert "inserted" in content


# ---------------------------------------------------------------------------
# FileEditor — unknown command
# ---------------------------------------------------------------------------


class TestFileEditorUnknown:
    """Tests for unknown commands."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.editor = FileEditor(workspace_root=self.tmpdir)

    def test_unknown_command(self):
        result = self.editor(command="delete", path="x.txt")
        assert result.error is not None


# ---------------------------------------------------------------------------
# _extract_content
# ---------------------------------------------------------------------------


class TestExtractContent:
    """Tests for _extract_content."""

    def setup_method(self):
        self.editor = FileEditor()

    def test_file_text_preferred(self):
        result = self.editor._extract_content("hello", "world")
        assert result == "hello"

    def test_new_str_fallback(self):
        result = self.editor._extract_content(MISSING, "world")
        assert result == "world"

    def test_both_missing(self):
        result = self.editor._extract_content(MISSING, MISSING)
        assert result == ""

    def test_none_values(self):
        result = self.editor._extract_content(None, None)
        assert result == ""
