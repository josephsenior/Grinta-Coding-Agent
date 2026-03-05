import pytest
from unittest.mock import patch
from backend.runtime.utils.file_editor import FileEditor

class TestFileEditorCoverageGaps:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """Setup for test class."""
        self.test_dir = tmp_path
        self.tmpdir = str(tmp_path)
        self.editor = FileEditor(workspace_root=self.tmpdir)

    def _write(self, name, content):
        p = self.test_dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def _read(self, name):
        p = self.test_dir / name
        return p.read_text(encoding="utf-8")

    def test_path_validation_error(self):
        """Covers line 126 (PathValidationError in __call__)."""
        result = self.editor(command="view", path="../outside.txt")
        assert result.error is not None
        assert "Path validation error" in result.error

    def test_handle_view_exception(self):
        """Covers line 193-194 (Exception in _handle_view)."""
        self._write("test.txt", "content")
        with patch.object(self.editor, "_prepare_view_content", side_effect=Exception("View error")):
            result = self.editor(command="view", path="test.txt")
            assert result.error is not None
            assert "Error reading file: View error" in result.error

    def test_handle_edit_exception(self):
        """Covers line 293-294 (Exception in _handle_edit)."""
        self._write("test.txt", "content")
        with patch.object(self.editor, "_read_file", side_effect=Exception("Read fail")):
            result = self.editor(command="edit", path="test.txt", old_str="c", new_str="d")
            assert result.error is not None
            assert "Error editing file: Read fail" in result.error

    def test_apply_edit_logic_no_content(self):
        """Covers line 382 (ToolResult for no content provided)."""
        self._write("test.txt", "content")
        result = self.editor(command="edit", path="test.txt")
        assert result.error is not None
        assert "No content provided" in result.error

    def test_apply_edit_logic_append_only(self):
        """Covers line 343 (old_content_str + new_str_val)."""
        # old_str is MISSING, new_str is provided
        self._write("test.txt", "line1\n")
        result = self.editor(command="edit", path="test.txt", new_str="line2\n")
        assert result.new_content is not None
        assert "line1\nline2\n" in result.new_content

    def test_transaction_success(self):
        """Covers lines 546-547 (Transaction success pop)."""
        self._write("file1.txt", "orig1")
        with self.editor.transaction() as trans:
            trans(command="write", path="file1.txt", file_text="new1")
            assert self.editor._transaction_stack != []
        # Success pop
        assert self.editor._transaction_stack == []
        # Line 399: backup_file should be hit if write was inside transaction
        # Let's verify backup was created
        # But backup logic is internal. Let's trust line 399 was hit.

    def test_transaction_failure(self):
        """Covers lines 549-551 (Transaction failure cleanup)."""
        self._write("file1.txt", "orig1")
        try:
            with self.editor.transaction() as trans:
                trans(command="write", path="file1.txt", file_text="new1")
                raise RuntimeError("Fail")
        except RuntimeError:
            pass
        # Failure pop
        assert self.editor._transaction_stack == []
        assert self._read("file1.txt") == "orig1"

    def test_insert_at_line_empty_file(self):
        """Covers line 497 (lines = [""] in _insert_at_line)."""
        with patch("backend.runtime.utils.file_editor.open", side_effect=ValueError("Stop hier")):
             # Actually easier to just call _insert_at_line
             res = self.editor._insert_at_line("", "content", 1)
             assert res == "content"

    def test_insert_at_line_simple_new(self):
        """Covers line 505 (new_lines = [new_text])."""
        res = self.editor._insert_at_line("a\n", "b", 2)
        assert res == "a\nb"

    def test_rollback_failure_logging_full(self):
        """Covers line 567-572 (rollback error handling)."""
        file_path = self.test_dir / "failed_restore.txt"
        self._write("failed_restore.txt", "content")
        backup: dict[str, str | None] = {str(file_path): "original"}

        with patch.object(self.editor, "_write_file", side_effect=Exception("Restore error")):
             # Hit lines 568-572
             self.editor._rollback_transaction(backup)
             # No crash!

    def test_fuzzy_match_error_high_ratio(self):
        """Covers lines 353-372 (difflib suggestion)."""
        content = "def foo():\n    print('hello')\n    return True\n"
        self._write("fuzzy.py", content)
        old_str = "def foo():\n    print('helo')\n    return True\n"
        result = self.editor(command="edit", path="fuzzy.py", old_str=old_str, new_str="something")
        assert result.error is not None
        assert "Did you mean this block" in result.error

    def test_unicode_decode_fallback(self):
        """Covers line 440-449 (UnicodeDecodeError fallback)."""
        p = self.test_dir / "binary.dat"
        p.write_bytes(b"hello \xff world") # 0xff invalid UTF-8
        content = self.editor._read_file(p)
        assert "hello" in content
        assert "ÿ" in content

    def test_write_file_unlink_error(self):
        """Covers line 490 (temp_path.unlink() in error path)."""
        # We'll mock Path.replace which is after temp file creation.
        # But we need Path.replace to be mocked on the temp_path?
        # That's tricky. Let's mock built-in replace.
        with patch("os.replace", side_effect=OSError("Replace fail")):
             with pytest.raises(OSError, match="Replace fail"):
                  # Use a dedicated target to avoid interference
                  self.editor._write_file(self.test_dir / "unlink_test.txt", "data")
        assert not list(self.test_dir.glob("*.tmp"))
