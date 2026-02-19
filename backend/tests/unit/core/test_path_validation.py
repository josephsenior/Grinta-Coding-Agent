"""Unit tests for backend.core.type_safety.path_validation — security-critical path checks."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.core.type_safety.path_validation import (
    DANGEROUS_CHARS,
    PathValidationError,
    PathValidator,
    SafePath,
    validate_and_sanitize_path,
)


# ---------------------------------------------------------------------------
# PathValidationError
# ---------------------------------------------------------------------------


class TestPathValidationError:
    def test_basic(self):
        err = PathValidationError("bad path", "/etc/passwd")
        assert err.message == "bad path"
        assert err.path == "/etc/passwd"

    def test_missing_path(self):
        err = PathValidationError("no path")
        assert err.path == "<unknown>"


# ---------------------------------------------------------------------------
# validate_and_sanitize_path
# ---------------------------------------------------------------------------


class TestValidateAndSanitizePath:
    @pytest.fixture()
    def workspace(self, tmp_path: Path) -> Path:
        return tmp_path

    def test_simple_relative(self, workspace: Path):
        result = validate_and_sanitize_path("app.py", workspace_root=str(workspace))
        assert result == workspace / "app.py"

    def test_nested_relative(self, workspace: Path):
        result = validate_and_sanitize_path(
            "src/main.py", workspace_root=str(workspace)
        )
        assert result == (workspace / "src" / "main.py").resolve()

    def test_empty_string(self):
        with pytest.raises(PathValidationError, match="non-empty"):
            validate_and_sanitize_path("")

    def test_none_input(self):
        with pytest.raises(PathValidationError, match="non-empty"):
            validate_and_sanitize_path(None)  # type: ignore[arg-type]

    def test_null_byte(self, workspace: Path):
        with pytest.raises(PathValidationError, match="null bytes"):
            validate_and_sanitize_path("file\x00.py", workspace_root=str(workspace))

    @pytest.mark.parametrize("char", DANGEROUS_CHARS[:5])
    def test_dangerous_chars(self, char: str, workspace: Path):
        with pytest.raises(PathValidationError, match="dangerous character"):
            validate_and_sanitize_path(f"file{char}name", workspace_root=str(workspace))

    @pytest.mark.parametrize(
        "pattern", ["../etc/passwd", "..\\windows\\system32", "..%2Fetc"]
    )
    def test_traversal(self, pattern: str, workspace: Path):
        with pytest.raises(PathValidationError, match="traversal"):
            validate_and_sanitize_path(pattern, workspace_root=str(workspace))

    def test_very_long_path(self, workspace: Path):
        long = "a" * 10_000
        with pytest.raises(PathValidationError, match="too long"):
            validate_and_sanitize_path(long, workspace_root=str(workspace))

    def test_must_exist_missing(self, workspace: Path):
        with pytest.raises(PathValidationError, match="does not exist"):
            validate_and_sanitize_path(
                "nonexistent.py", workspace_root=str(workspace), must_exist=True
            )

    def test_must_exist_present(self, workspace: Path):
        (workspace / "present.py").touch()
        result = validate_and_sanitize_path(
            "present.py", workspace_root=str(workspace), must_exist=True
        )
        assert result.exists()

    def test_relative_needs_workspace(self):
        with pytest.raises(PathValidationError, match="workspace_root required"):
            validate_and_sanitize_path(
                "file.py", workspace_root=None, must_be_relative=True
            )

    def test_absolute_mode(self, tmp_path: Path):
        target = tmp_path / "absolute.py"
        target.touch()
        result = validate_and_sanitize_path(str(target), must_be_relative=False)
        assert result.exists()

    def test_url_decoded(self, workspace: Path):
        result = validate_and_sanitize_path(
            "my%20file.py", workspace_root=str(workspace)
        )
        assert "my file" in str(result)

    def test_very_deep_path(self, workspace: Path):
        """Test path depth limit (>100 levels)."""
        deep_path = "/".join(["level"] * 101)
        with pytest.raises(PathValidationError, match="depth too great"):
            validate_and_sanitize_path(deep_path, workspace_root=str(workspace))

    def test_invalid_path_oserror(self, workspace: Path):
        """Test OSError handling during path operations."""
        # Use an invalid character for Windows paths (if on Windows)
        # or a path that would cause OSError
        import platform

        if platform.system() == "Windows":
            # Windows doesn't allow certain characters in paths
            # This should be caught by dangerous chars, but let's test other edge cases
            pass
        # Alternative approach: mock Path.resolve to raise OSError
        from unittest.mock import patch

        with patch("pathlib.Path.resolve", side_effect=OSError("Mock error")):
            with pytest.raises(PathValidationError, match="Invalid path"):
                validate_and_sanitize_path("test.py", workspace_root=str(workspace))


# ---------------------------------------------------------------------------
# SafePath
# ---------------------------------------------------------------------------


class TestSafePath:
    @pytest.fixture()
    def workspace(self, tmp_path: Path) -> Path:
        return tmp_path

    def test_validate_creates_instance(self, workspace: Path):
        sp = SafePath.validate("file.py", workspace_root=str(workspace))
        assert isinstance(sp, SafePath)
        assert sp.path == (workspace / "file.py").resolve()

    def test_relative_to_workspace(self, workspace: Path):
        sp = SafePath.validate("src/main.py", workspace_root=str(workspace))
        rel = sp.relative_to_workspace()
        assert rel == os.path.join("src", "main.py")

    def test_relative_to_workspace_no_root(self):
        sp = SafePath(Path("/some/path"))
        with pytest.raises(ValueError, match="not set"):
            sp.relative_to_workspace()

    def test_str(self, workspace: Path):
        sp = SafePath.validate("foo.py", workspace_root=str(workspace))
        assert "foo.py" in str(sp)

    def test_repr(self, workspace: Path):
        sp = SafePath.validate("foo.py", workspace_root=str(workspace))
        assert "SafePath" in repr(sp)

    def test_fspath(self, workspace: Path):
        sp = SafePath.validate("foo.py", workspace_root=str(workspace))
        assert os.fspath(sp) == str(sp.path)

    def test_eq_same(self, workspace: Path):
        sp1 = SafePath.validate("a.py", workspace_root=str(workspace))
        sp2 = SafePath.validate("a.py", workspace_root=str(workspace))
        assert sp1 == sp2

    def test_eq_string(self, workspace: Path):
        sp = SafePath.validate("a.py", workspace_root=str(workspace))
        assert sp == str(sp.path)

    def test_eq_path(self, workspace: Path):
        sp = SafePath.validate("a.py", workspace_root=str(workspace))
        assert sp == sp.path

    def test_neq_other_type(self, workspace: Path):
        sp = SafePath.validate("a.py", workspace_root=str(workspace))
        assert sp != 42

    def test_hashable(self, workspace: Path):
        sp = SafePath.validate("a.py", workspace_root=str(workspace))
        d = {sp: 1}
        assert d[sp] == 1

    def test_exists_false(self, workspace: Path):
        sp = SafePath.validate("missing.py", workspace_root=str(workspace))
        assert sp.exists() is False

    def test_exists_true(self, workspace: Path):
        (workspace / "found.py").touch()
        sp = SafePath.validate("found.py", workspace_root=str(workspace))
        assert sp.exists() is True

    def test_is_file(self, workspace: Path):
        (workspace / "a.py").touch()
        sp = SafePath.validate("a.py", workspace_root=str(workspace))
        assert sp.is_file() is True
        assert sp.is_dir() is False

    def test_is_dir(self, workspace: Path):
        (workspace / "subdir").mkdir()
        sp = SafePath.validate("subdir", workspace_root=str(workspace))
        assert sp.is_dir() is True

    def test_relative_to_workspace_outside(self, tmp_path: Path):
        """Test relative_to_workspace when path is outside workspace."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        outside_file = outside / "file.py"
        outside_file.touch()
        # Create a SafePath with absolute path outside workspace
        sp = SafePath.validate(
            str(outside_file), workspace_root=str(workspace), must_be_relative=False
        )
        # Set workspace_root after validation to test the ValueError path
        sp._workspace_root = workspace
        result = sp.relative_to_workspace()
        # Should return the full path as string since it's not relative
        assert str(outside_file) in result or "outside" in result


# ---------------------------------------------------------------------------
# PathValidator
# ---------------------------------------------------------------------------


class TestPathValidator:
    def test_init_missing_root(self):
        with pytest.raises(PathValidationError, match="does not exist"):
            PathValidator("/nonexistent/workspace/xyz")

    def test_validate(self, tmp_path: Path):
        pv = PathValidator(tmp_path)
        sp = pv.validate("test.py")
        assert isinstance(sp, SafePath)

    def test_validate_must_exist(self, tmp_path: Path):
        pv = PathValidator(tmp_path)
        with pytest.raises(PathValidationError, match="does not exist"):
            pv.validate("ghost.py", must_exist=True)
