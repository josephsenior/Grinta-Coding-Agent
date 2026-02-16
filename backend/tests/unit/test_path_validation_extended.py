"""Tests for backend.core.type_safety.path_validation — SafePath, PathValidator, validate_and_sanitize_path."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from backend.core.type_safety.path_validation import (
    DANGEROUS_CHARS,
    PathValidationError,
    SafePath,
    validate_and_sanitize_path,
)


# ---------------------------------------------------------------------------
# PathValidationError
# ---------------------------------------------------------------------------

class TestPathValidationError:
    """Tests for PathValidationError."""

    def test_message_and_path(self):
        err = PathValidationError("bad path", "/etc/passwd")
        assert err.message == "bad path"
        assert err.path == "/etc/passwd"

    def test_default_unknown_path(self):
        err = PathValidationError("error only")
        assert err.path == "<unknown>"


# ---------------------------------------------------------------------------
# SafePath
# ---------------------------------------------------------------------------

class TestSafePath:
    """Tests for SafePath wrapper."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_validate_relative_path(self):
        sp = SafePath.validate("file.txt", workspace_root=self.tmpdir)
        assert sp.path == Path(self.tmpdir).resolve() / "file.txt"
        assert sp.workspace_root == Path(self.tmpdir)

    def test_relative_to_workspace(self):
        sp = SafePath.validate("sub/file.txt", workspace_root=self.tmpdir)
        assert sp.relative_to_workspace() == str(Path("sub") / "file.txt")

    def test_relative_to_workspace_no_root(self):
        sp = SafePath(Path("/some/path"))
        with pytest.raises(ValueError, match="Workspace root not set"):
            sp.relative_to_workspace()

    def test_str_and_repr(self):
        sp = SafePath(Path("/workspace/test.py"), Path("/workspace"))
        assert "test.py" in str(sp)
        assert "SafePath" in repr(sp)

    def test_fspath_protocol(self):
        sp = SafePath(Path("/workspace/test.py"))
        import os
        assert os.fspath(sp) == str(Path("/workspace/test.py"))

    def test_equality(self):
        a = SafePath(Path("/a/b"))
        b = SafePath(Path("/a/b"))
        assert a == b

    def test_equality_with_string(self):
        sp = SafePath(Path("/a/b"))
        assert sp == "/a/b"

    def test_equality_with_other_type(self):
        sp = SafePath(Path("/a/b"))
        assert sp != 42

    def test_hashable(self):
        sp = SafePath(Path("/a/b"))
        d = {sp: True}
        assert d[sp] is True


# ---------------------------------------------------------------------------
# validate_and_sanitize_path
# ---------------------------------------------------------------------------

class TestValidateAndSanitizePath:
    """Tests for validate_and_sanitize_path."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_valid_relative_path(self):
        result = validate_and_sanitize_path("file.txt", workspace_root=self.tmpdir)
        assert result == Path(self.tmpdir).resolve() / "file.txt"

    def test_empty_path_raises(self):
        with pytest.raises(PathValidationError, match="non-empty string"):
            validate_and_sanitize_path("", workspace_root=self.tmpdir)

    def test_none_path_raises(self):
        with pytest.raises(PathValidationError, match="non-empty string"):
            validate_and_sanitize_path(None, workspace_root=self.tmpdir)  # type: ignore

    def test_null_byte_raises(self):
        with pytest.raises(PathValidationError, match="null bytes"):
            validate_and_sanitize_path("file\x00.txt", workspace_root=self.tmpdir)

    def test_path_too_long(self):
        long_path = "a" * 10000
        with pytest.raises(PathValidationError, match="too long"):
            validate_and_sanitize_path(long_path, workspace_root=self.tmpdir)

    def test_dangerous_chars_rejected(self):
        for char in ["<", ">", "|", "&", ";", "`", "$"]:
            with pytest.raises(PathValidationError, match="dangerous character"):
                validate_and_sanitize_path(f"file{char}bad", workspace_root=self.tmpdir)

    def test_traversal_dot_dot_rejected(self):
        with pytest.raises(PathValidationError, match="traversal"):
            validate_and_sanitize_path("../etc/passwd", workspace_root=self.tmpdir)

    def test_url_encoded_traversal_rejected(self):
        with pytest.raises(PathValidationError, match="traversal"):
            validate_and_sanitize_path("..%2Fetc%2Fpasswd", workspace_root=self.tmpdir)

    def test_must_exist_raises(self):
        with pytest.raises(PathValidationError, match="does not exist"):
            validate_and_sanitize_path("nonexistent.txt", workspace_root=self.tmpdir, must_exist=True)

    def test_must_exist_passes(self):
        p = Path(self.tmpdir) / "exists.txt"
        p.write_text("data")
        result = validate_and_sanitize_path("exists.txt", workspace_root=self.tmpdir, must_exist=True)
        assert result == p.resolve()

    def test_relative_requires_workspace(self):
        with pytest.raises(PathValidationError, match="workspace_root required"):
            validate_and_sanitize_path("file.txt", workspace_root=None, must_be_relative=True)

    def test_absolute_path_allowed(self):
        result = validate_and_sanitize_path(self.tmpdir, must_be_relative=False)
        assert result == Path(self.tmpdir).resolve()

    def test_nested_path(self):
        result = validate_and_sanitize_path("a/b/c/file.txt", workspace_root=self.tmpdir)
        assert result == Path(self.tmpdir).resolve() / "a" / "b" / "c" / "file.txt"
