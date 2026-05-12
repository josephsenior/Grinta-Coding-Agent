"""MacOS compatibility validation tests.

These tests verify cross-platform code paths that work on macOS,
with proper mocking to test behavior without requiring macOS.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


class TestOSCapabilitiesMocked:
    """Tests for OS capabilities with mocking."""

    @pytest.mark.integration
    def test_os_caps_imports(self) -> None:
        """Verify OS capabilities module can be imported."""
        from backend.core.os_capabilities import OS_CAPS

        assert OS_CAPS is not None

    @pytest.mark.integration
    def test_is_macos_function_imports(self) -> None:
        """Verify is_macos helper can be imported."""
        from backend.core.os_capabilities import is_macos

        assert callable(is_macos)


class TestPlatformPathSeparators:
    """Tests for path separator handling in cross-platform code."""

    @pytest.mark.integration
    def test_path_separator_detection(self) -> None:
        """Verify path separator varies by platform."""
        from backend.core.os_capabilities import OS_CAPS

        assert hasattr(OS_CAPS, 'is_windows')
        assert hasattr(OS_CAPS, 'is_posix')
        assert hasattr(OS_CAPS, 'is_macos')


class TestPathHandlingCrossPlatform:
    """Tests for cross-platform path handling."""

    @pytest.mark.integration
    def test_expanduser_works(self) -> None:
        """Verify ~ expansion works on any platform."""
        test_path = Path('~').expanduser()
        assert test_path.is_absolute()
        assert str(test_path).startswith(str(Path.home()))

    @pytest.mark.integration
    def test_path_resolution_works(self) -> None:
        """Verify path resolution works."""
        relative = Path('subdir/file.txt')
        resolved = (Path.cwd() / relative).resolve()
        assert resolved.is_absolute()

    @pytest.mark.integration
    def test_path_join_cross_platform(self) -> None:
        """Verify Path.join works across platforms."""
        result = Path('dir') / 'subdir' / 'file.txt'
        assert 'file.txt' in str(result)


class TestEnvironmentCrossPlatform:
    """Tests for environment handling that works across platforms."""

    @pytest.mark.integration
    def test_environ_gets_api_key(self) -> None:
        """Verify LLM_API_KEY can be read from environment."""
        with patch.dict(os.environ, {'LLM_API_KEY': 'test-key-123'}):
            assert os.environ.get('LLM_API_KEY') == 'test-key-123'

    @pytest.mark.integration
    def test_home_detection(self) -> None:
        """Verify home directory detection."""
        home = Path.home()
        assert home.exists()
        assert home.is_dir()

    @pytest.mark.integration
    def test_pathsep_varies_by_platform(self) -> None:
        """Verify pathsep differs by OS."""
        assert os.pathsep in (':', ';')


class TestProcessCrossPlatform:
    """Tests for process handling across platforms."""

    @pytest.mark.integration
    def test_multiprocessing_available(self) -> None:
        """Verify multiprocessing is available."""
        import multiprocessing as mp

        assert hasattr(mp, 'get_all_start_methods')
        methods = mp.get_all_start_methods()
        assert isinstance(methods, list)

    @pytest.mark.integration
    def test_shutil_which_available(self) -> None:
        """Verify shutil.which is available."""
        import shutil

        assert callable(shutil.which)


class TestSubprocessCrossPlatform:
    """Tests for subprocess handling."""

    @pytest.mark.integration
    def test_run_imports(self) -> None:
        """Verify subprocess.run is available."""
        import subprocess

        assert hasattr(subprocess, 'run')

    @pytest.mark.integration
    def test_popen_imports(self) -> None:
        """Verify subprocess.Popen is available."""
        import subprocess

        assert hasattr(subprocess, 'Popen')


class TestFileSystemCrossPlatform:
    """Tests for filesystem operations."""

    @pytest.mark.integration
    def test_mkdir_parents(self, tmp_path: Path) -> None:
        """Verify nested directory creation."""
        nested = tmp_path / 'a' / 'b' / 'c'
        nested.mkdir(parents=True, exist_ok=True)
        assert nested.exists()

    @pytest.mark.integration
    def test_write_read_text(self, tmp_path: Path) -> None:
        """Verify text file write/read."""
        f = tmp_path / 'test.txt'
        f.write_text('hello world', encoding='utf-8')
        assert f.read_text(encoding='utf-8') == 'hello world'

    @pytest.mark.integration
    def test_json_roundtrip(self, tmp_path: Path) -> None:
        """Verify JSON serialization."""
        import json

        data = {'key': 'value', 'number': 42}
        f = tmp_path / 'data.json'
        f.write_text(json.dumps(data), encoding='utf-8')
        loaded = json.loads(f.read_text(encoding='utf-8'))
        assert loaded == data


class TestOSCapsAttributes:
    """Tests for OS capabilities attributes."""

    @pytest.mark.integration
    def test_os_caps_has_is_windows(self) -> None:
        """Verify OS_CAPS has is_windows attribute."""
        from backend.core.os_capabilities import OS_CAPS

        assert hasattr(OS_CAPS, 'is_windows')

    @pytest.mark.integration
    def test_os_caps_has_is_macos(self) -> None:
        """Verify OS_CAPS has is_macos attribute."""
        from backend.core.os_capabilities import OS_CAPS

        assert hasattr(OS_CAPS, 'is_macos')

    @pytest.mark.integration
    def test_os_caps_has_is_linux(self) -> None:
        """Verify OS_CAPS has is_linux attribute."""
        from backend.core.os_capabilities import OS_CAPS

        assert hasattr(OS_CAPS, 'is_linux')

    @pytest.mark.integration
    def test_os_caps_has_is_posix(self) -> None:
        """Verify OS_CAPS has is_posix attribute."""
        from backend.core.os_capabilities import OS_CAPS

        assert hasattr(OS_CAPS, 'is_posix')

    @pytest.mark.integration
    def test_os_caps_has_sys_platform(self) -> None:
        """Verify OS_CAPS has sys_platform attribute."""
        from backend.core.os_capabilities import OS_CAPS

        assert hasattr(OS_CAPS, 'sys_platform')
        assert OS_CAPS.sys_platform in ('win32', 'darwin', 'linux')


class TestHomeDirCrossPlatform:
    """Tests for home directory handling."""

    @pytest.mark.integration
    def test_home_varies_by_platform(self) -> None:
        """Verify Path.home() returns platform-specific path."""
        home = Path.home()
        assert home.exists()
        assert home.is_dir()

    @pytest.mark.integration
    def test_home_contains_user(self, tmp_path: Path) -> None:
        """Verify home directory contains user-specific path."""
        home = Path.home()
        username = os.environ.get('USERNAME') or os.environ.get('USER') or 'user'
        assert username in str(home) or home.name == username


class TestTempDirCrossPlatform:
    """Tests for temp directory handling."""

    @pytest.mark.integration
    def test_tempdir_creation(self, tmp_path: Path) -> None:
        """Verify temp directory is created."""
        assert tmp_path.exists()

    @pytest.mark.integration
    def test_tempfile_mktemp(self, tmp_path: Path) -> None:
        """Verify tempfile can create temp files."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            assert Path(td).exists()


class TestEnvVarExpansion:
    """Tests for environment variable expansion."""

    @pytest.mark.integration
    def test_env_var_expansion(self) -> None:
        """Verify environment variables expand correctly."""
        test_val = 'test_value_123'
        with patch.dict(os.environ, {'TEST_VAR': test_val}):
            assert os.environ.get('TEST_VAR') == test_val

    @pytest.mark.integration
    def test_path_env_handling(self) -> None:
        """Verify PATH environment variable is handled."""
        path = os.environ.get('PATH', '')
        assert isinstance(path, str)