"""Unit tests for backend.core.type_safety.path_validation — security-critical path checks."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.core.os_capabilities import OSCapabilities, override_os_capabilities
from backend.core.type_safety.path_validation import (
    DANGEROUS_CHARS,
    PathValidationError,
    PathValidator,
    SafePath,
    _is_windows_junction,
    _reject_unsafe_links,
    _resolve_path,
    _validate_path_string,
    validate_and_sanitize_path,
)


def _windows_caps() -> OSCapabilities:
    return OSCapabilities(
        is_windows=True,
        is_posix=False,
        is_linux=False,
        is_macos=False,
        shell_kind='powershell',
        supports_pty=False,
        signal_strategy='windows',
        path_sep='\\',
        default_python_exec='python',
        sys_platform='win32',
        os_name='nt',
    )


def _posix_caps() -> OSCapabilities:
    return OSCapabilities(
        is_windows=False,
        is_posix=True,
        is_linux=True,
        is_macos=False,
        shell_kind='bash',
        supports_pty=True,
        signal_strategy='posix',
        path_sep='/',
        default_python_exec='python3',
        sys_platform='linux',
        os_name='posix',
    )

# ---------------------------------------------------------------------------
# PathValidationError
# ---------------------------------------------------------------------------


class TestPathValidationError:
    def test_basic(self):
        err = PathValidationError('bad path', '/etc/passwd')
        assert err.message == 'bad path'
        assert err.path == '/etc/passwd'

    def test_missing_path(self):
        err = PathValidationError('no path')
        assert err.path == '<unknown>'


# ---------------------------------------------------------------------------
# validate_and_sanitize_path
# ---------------------------------------------------------------------------


class TestValidateAndSanitizePath:
    @pytest.fixture()
    def workspace(self, tmp_path: Path) -> Path:
        return tmp_path

    def test_simple_relative(self, workspace: Path):
        result = validate_and_sanitize_path('app.py', workspace_root=str(workspace))
        assert result == workspace / 'app.py'

    def test_nested_relative(self, workspace: Path):
        result = validate_and_sanitize_path(
            'src/main.py', workspace_root=str(workspace)
        )
        assert result == (workspace / 'src' / 'main.py').resolve()

    def test_empty_string(self):
        with pytest.raises(PathValidationError, match='non-empty'):
            validate_and_sanitize_path('')

    def test_none_input(self):
        with pytest.raises(PathValidationError, match='non-empty'):
            validate_and_sanitize_path(None)  # type: ignore[arg-type]

    def test_null_byte(self, workspace: Path):
        with pytest.raises(PathValidationError, match='null bytes'):
            validate_and_sanitize_path('file\x00.py', workspace_root=str(workspace))

    @pytest.mark.parametrize('char', DANGEROUS_CHARS[:5])
    def test_dangerous_chars(self, char: str, workspace: Path):
        with pytest.raises(PathValidationError, match='dangerous character'):
            validate_and_sanitize_path(f'file{char}name', workspace_root=str(workspace))

    @pytest.mark.parametrize(
        'pattern', ['../etc/passwd', '..\\windows\\system32', '..%2Fetc']
    )
    def test_traversal(self, pattern: str, workspace: Path):
        with pytest.raises(PathValidationError, match='traversal'):
            validate_and_sanitize_path(pattern, workspace_root=str(workspace))

    def test_very_long_path(self, workspace: Path):
        long = 'a' * 10_000
        with pytest.raises(PathValidationError, match='too long'):
            validate_and_sanitize_path(long, workspace_root=str(workspace))

    def test_must_exist_missing(self, workspace: Path):
        with pytest.raises(PathValidationError, match='does not exist'):
            validate_and_sanitize_path(
                'nonexistent.py', workspace_root=str(workspace), must_exist=True
            )

    def test_must_exist_present(self, workspace: Path):
        (workspace / 'present.py').touch()
        result = validate_and_sanitize_path(
            'present.py', workspace_root=str(workspace), must_exist=True
        )
        assert result.exists()

    def test_relative_needs_workspace(self):
        with pytest.raises(PathValidationError, match='workspace_root required'):
            validate_and_sanitize_path(
                'file.py', workspace_root=None, must_be_relative=True
            )

    def test_absolute_mode(self, tmp_path: Path):
        target = tmp_path / 'absolute.py'
        target.touch()
        result = validate_and_sanitize_path(str(target), must_be_relative=False)
        assert result.exists()

    def test_url_decoded(self, workspace: Path):
        result = validate_and_sanitize_path(
            'my%20file.py', workspace_root=str(workspace)
        )
        assert 'my file' in str(result)

    def test_very_deep_path(self, workspace: Path):
        """Test path depth limit (>100 levels)."""
        deep_path = '/'.join(['level'] * 101)
        with pytest.raises(PathValidationError, match='depth too great'):
            validate_and_sanitize_path(deep_path, workspace_root=str(workspace))

    def test_invalid_path_oserror(self, workspace: Path):
        """Test OSError handling during path operations."""
        # Use an invalid character for Windows paths (if on Windows)
        # or a path that would cause OSError
        import platform

        if platform.system() == 'Windows':
            # Windows doesn't allow certain characters in paths
            # This should be caught by dangerous chars, but let's test other edge cases
            pass
        # Alternative approach: mock Path.resolve to raise OSError
        from unittest.mock import patch

        with patch('pathlib.Path.resolve', side_effect=OSError('Mock error')):
            with pytest.raises(PathValidationError, match='Invalid path'):
                validate_and_sanitize_path('test.py', workspace_root=str(workspace))

    def test_invalid_url_encoding_is_wrapped(self):
        with patch(
            'backend.core.type_safety.path_validation.unquote',
            side_effect=ValueError('bad escape'),
        ):
            with pytest.raises(PathValidationError, match='Invalid URL encoding'):
                _validate_path_string('bad%zz')

    def test_dotdot_segment_rejected_without_known_pattern(self, workspace: Path):
        with pytest.raises(PathValidationError, match=r'Path traversal detected: \.\.'):
            validate_and_sanitize_path('folder/..', workspace_root=str(workspace))

    def test_virtual_workspace_prefix_maps_to_workspace_root(self, workspace: Path):
        result = validate_and_sanitize_path('/workspace', workspace_root=str(workspace))
        assert result == workspace.resolve()

    def test_virtual_workspace_prefix_stripped_for_child_path(self, workspace: Path):
        result = validate_and_sanitize_path(
            '/workspace/src/app.py',
            workspace_root=str(workspace),
        )
        assert result == (workspace / 'src' / 'app.py').resolve()

    def test_windows_boundary_fallback_accepts_inside_workspace(
        self, workspace: Path
    ) -> None:
        full_path = (workspace / 'inside.py').resolve()
        original_relative_to = Path.relative_to

        def fake_relative_to(self: Path, other: Path):
            if self == full_path and other == workspace.resolve():
                raise ValueError('case mismatch')
            return original_relative_to(self, other)

        with override_os_capabilities(_windows_caps()):
            with patch.object(Path, 'relative_to', new=fake_relative_to):
                result = _resolve_path('inside.py', workspace, True)

        assert result == full_path

    def test_windows_boundary_fallback_rejects_outside_workspace(
        self, workspace: Path, tmp_path: Path
    ) -> None:
        original_resolve = Path.resolve
        candidate = workspace / 'outside.py'
        outside = (tmp_path.parent / 'outside.py').resolve()

        def fake_resolve(self: Path, strict: bool = False):
            if self == candidate:
                return outside
            return original_resolve(self)

        with override_os_capabilities(_windows_caps()):
            with patch.object(Path, 'resolve', new=fake_resolve):
                with pytest.raises(PathValidationError, match='outside workspace boundary'):
                    _resolve_path('outside.py', workspace, True)


# ---------------------------------------------------------------------------
# SafePath
# ---------------------------------------------------------------------------


class TestSafePath:
    @pytest.fixture()
    def workspace(self, tmp_path: Path) -> Path:
        return tmp_path

    def test_validate_creates_instance(self, workspace: Path):
        sp = SafePath.validate('file.py', workspace_root=str(workspace))
        assert isinstance(sp, SafePath)
        assert sp.path == (workspace / 'file.py').resolve()

    def test_relative_to_workspace(self, workspace: Path):
        sp = SafePath.validate('src/main.py', workspace_root=str(workspace))
        rel = sp.relative_to_workspace()
        assert rel == os.path.join('src', 'main.py')

    def test_relative_to_workspace_no_root(self):
        sp = SafePath(Path('/some/path'))
        with pytest.raises(ValueError, match='not set'):
            sp.relative_to_workspace()

    def test_str(self, workspace: Path):
        sp = SafePath.validate('foo.py', workspace_root=str(workspace))
        assert 'foo.py' in str(sp)

    def test_repr(self, workspace: Path):
        sp = SafePath.validate('foo.py', workspace_root=str(workspace))
        assert 'SafePath' in repr(sp)

    def test_fspath(self, workspace: Path):
        sp = SafePath.validate('foo.py', workspace_root=str(workspace))
        assert os.fspath(sp) == str(sp.path)

    def test_eq_same(self, workspace: Path):
        sp1 = SafePath.validate('a.py', workspace_root=str(workspace))
        sp2 = SafePath.validate('a.py', workspace_root=str(workspace))
        assert sp1 == sp2

    def test_eq_string(self, workspace: Path):
        sp = SafePath.validate('a.py', workspace_root=str(workspace))
        assert sp == str(sp.path)

    def test_eq_path(self, workspace: Path):
        sp = SafePath.validate('a.py', workspace_root=str(workspace))
        assert sp == sp.path

    def test_neq_other_type(self, workspace: Path):
        sp = SafePath.validate('a.py', workspace_root=str(workspace))
        assert sp != 42

    def test_hashable(self, workspace: Path):
        sp = SafePath.validate('a.py', workspace_root=str(workspace))
        d = {sp: 1}
        assert d[sp] == 1

    def test_exists_false(self, workspace: Path):
        sp = SafePath.validate('missing.py', workspace_root=str(workspace))
        assert sp.exists() is False

    def test_exists_true(self, workspace: Path):
        (workspace / 'found.py').touch()
        sp = SafePath.validate('found.py', workspace_root=str(workspace))
        assert sp.exists() is True

    def test_is_file(self, workspace: Path):
        (workspace / 'a.py').touch()
        sp = SafePath.validate('a.py', workspace_root=str(workspace))
        assert sp.is_file() is True
        assert sp.is_dir() is False

    def test_is_dir(self, workspace: Path):
        (workspace / 'subdir').mkdir()
        sp = SafePath.validate('subdir', workspace_root=str(workspace))
        assert sp.is_dir() is True

    def test_relative_to_workspace_outside(self, tmp_path: Path):
        """Test relative_to_workspace when path is outside workspace."""
        workspace = tmp_path / 'workspace'
        workspace.mkdir()
        outside = tmp_path / 'outside'
        outside.mkdir()
        outside_file = outside / 'file.py'
        outside_file.touch()
        # Create a SafePath with absolute path outside workspace
        sp = SafePath.validate(
            str(outside_file), workspace_root=str(workspace), must_be_relative=False
        )
        # Set workspace_root after validation to test the ValueError path
        sp._workspace_root = workspace
        result = sp.relative_to_workspace()
        # Should return the full path as string since it's not relative
        assert str(outside_file) in result or 'outside' in result


# ---------------------------------------------------------------------------
# PathValidator
# ---------------------------------------------------------------------------


class TestPathValidator:
    def test_init_missing_root(self):
        with pytest.raises(PathValidationError, match='does not exist'):
            PathValidator('/nonexistent/workspace/xyz')

    def test_validate(self, tmp_path: Path):
        pv = PathValidator(tmp_path)
        sp = pv.validate('test.py')
        assert isinstance(sp, SafePath)

    def test_validate_must_exist(self, tmp_path: Path):
        pv = PathValidator(tmp_path)
        with pytest.raises(PathValidationError, match='does not exist'):
            pv.validate('ghost.py', must_exist=True)


class TestPathValidationInternals:
    def test_windows_junction_returns_false_off_windows(self, tmp_path: Path) -> None:
        with override_os_capabilities(_posix_caps()):
            assert _is_windows_junction(tmp_path) is False

    def test_reject_unsafe_links_ignores_probe_oserror(self, tmp_path: Path) -> None:
        workspace = tmp_path.resolve()
        full_path = workspace / 'file.py'
        original_is_symlink = Path.is_symlink

        def fake_is_symlink(self: Path) -> bool:
            if self == full_path:
                raise OSError('denied')
            return original_is_symlink(self)

        with patch.object(Path, 'is_symlink', new=fake_is_symlink):
            _reject_unsafe_links('file.py', full_path, workspace)

    def test_reject_unsafe_links_rejects_broken_or_cyclic_link(
        self, tmp_path: Path
    ) -> None:
        workspace = tmp_path.resolve()
        full_path = workspace / 'link.py'
        original_is_symlink = Path.is_symlink
        original_resolve = Path.resolve

        def fake_is_symlink(self: Path) -> bool:
            if self == full_path:
                return True
            return original_is_symlink(self)

        def fake_resolve(self: Path, strict: bool = False):
            if self == full_path:
                raise RuntimeError('loop')
            return original_resolve(self)

        with patch.object(Path, 'is_symlink', new=fake_is_symlink):
            with patch.object(Path, 'resolve', new=fake_resolve):
                with pytest.raises(PathValidationError, match='broken or cyclic link'):
                    _reject_unsafe_links('link.py', full_path, workspace)

    def test_reject_unsafe_links_rejects_escape_target(self, tmp_path: Path) -> None:
        workspace = tmp_path.resolve()
        full_path = workspace / 'link.py'
        outside = (tmp_path.parent / 'outside.txt').resolve()
        original_is_symlink = Path.is_symlink
        original_resolve = Path.resolve

        def fake_is_symlink(self: Path) -> bool:
            if self == full_path:
                return True
            return original_is_symlink(self)

        def fake_resolve(self: Path, strict: bool = False):
            if self == full_path:
                return outside
            return original_resolve(self)

        with patch.object(Path, 'is_symlink', new=fake_is_symlink):
            with patch.object(Path, 'resolve', new=fake_resolve):
                with pytest.raises(PathValidationError, match='escapes the workspace'):
                    _reject_unsafe_links('link.py', full_path, workspace)

    def test_reject_unsafe_links_stops_at_root(self) -> None:
        _reject_unsafe_links('/', Path('/'), Path('/'))

    def test_reject_unsafe_links_breaks_on_seen_candidate_cycle(self) -> None:
        class _LoopPath:
            def __init__(self, name: str) -> None:
                self.name = name
                self.parent: _LoopPath = self

            def is_symlink(self) -> bool:
                return False

            def relative_to(self, _workspace):
                return self

            def __hash__(self) -> int:
                return hash(self.name)

            def __eq__(self, other: object) -> bool:
                return isinstance(other, _LoopPath) and self.name == other.name

        first = _LoopPath('first')
        second = _LoopPath('second')
        first.parent = second
        second.parent = first

        with patch('backend.core.type_safety.path_validation._is_windows_junction', return_value=False):
            _reject_unsafe_links('loop', first, first)

    def test_non_windows_outside_workspace_raises(self, tmp_path: Path):
        workspace = tmp_path / 'workspace'
        workspace.mkdir()
        original_resolve = Path.resolve
        candidate = workspace / 'outside.py'
        outside = (tmp_path.parent / 'outside.py').resolve()

        def fake_resolve(self: Path, strict: bool = False):
            if self == candidate:
                return outside
            return original_resolve(self)

        with override_os_capabilities(_posix_caps()):
            with patch.object(Path, 'resolve', new=fake_resolve):
                with pytest.raises(PathValidationError, match='outside workspace boundary'):
                    _resolve_path('outside.py', workspace, True)
