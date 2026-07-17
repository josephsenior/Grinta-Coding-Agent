"""Unit tests for MSYS/Git Bash path normalization on Windows."""

from __future__ import annotations

import os
from unittest.mock import patch

from backend.utils.path_normalize import (
    get_native_path_env,
    is_msys_path,
    msys_to_windows_path,
    normalize_path_env,
    to_native_path,
    which_normalized,
)


def test_is_msys_path() -> None:
    # Valid MSYS drive mount paths (must have trailing slash if no path follows)
    assert is_msys_path('/c/Users/foo') is True
    assert is_msys_path('/C/Users/foo') is True
    assert is_msys_path('/z/projects') is True
    assert is_msys_path('/d/') is True

    # Invalid / non-MSYS paths
    assert is_msys_path('/d') is False  # No trailing slash or path segment
    assert is_msys_path('') is False
    assert is_msys_path('C:\\Users\\foo') is False
    assert is_msys_path('/usr/bin') is False
    assert is_msys_path('/tmp') is False
    assert is_msys_path('relative/path') is False
    assert is_msys_path(None) is False  # type: ignore


def test_msys_to_windows_path() -> None:
    # Basic conversion cases
    assert msys_to_windows_path('/c/Users/foo') == f'C:\\Users{os.sep}foo'
    assert msys_to_windows_path('/d/') == 'D:\\'
    assert msys_to_windows_path('/z/') == 'Z:\\'

    # Non-conversion fallback cases
    assert (
        msys_to_windows_path('/d') == '/d'
    )  # Doesn't match drive RE without trailing slash
    assert msys_to_windows_path('') == ''
    assert msys_to_windows_path('C:\\Users\\foo') == 'C:\\Users\\foo'
    assert msys_to_windows_path('/usr/bin') == '/usr/bin'
    assert msys_to_windows_path(None) is None  # type: ignore


def test_to_native_path() -> None:
    # Test on Windows mode
    with (
        patch('backend.utils.path_normalize.os.name', 'nt'),
        patch('backend.utils.path_normalize.os.sep', '\\'),
    ):
        assert to_native_path('/c/Users/foo') == 'C:\\Users\\foo'
        assert to_native_path('C:\\Users\\foo') == 'C:\\Users\\foo'

    # Test on POSIX mode
    with patch('backend.utils.path_normalize.os.name', 'posix'):
        assert to_native_path('/c/Users/foo') == '/c/Users/foo'


def test_normalize_path_env_edge_cases() -> None:
    # None or empty variables
    assert normalize_path_env(None) == ''
    assert normalize_path_env('') == ''
    with patch('backend.utils.path_normalize.os.name', 'nt'):
        assert normalize_path_env('   ') == ''


def test_normalize_path_env_posix() -> None:
    # On POSIX it should be returned as-is
    with patch('backend.utils.path_normalize.os.name', 'posix'):
        raw_path = '/c/Users/foo/bin:/usr/local/bin'
        assert normalize_path_env(raw_path) == raw_path


def test_normalize_path_env_windows() -> None:
    # On Windows it splits, normalizes to native path, removes duplicates, and rejoins with ";"
    with (
        patch('backend.utils.path_normalize.os.name', 'nt'),
        patch('backend.utils.path_normalize.os.sep', '\\'),
    ):
        # Separated by ":" (colon splitting occurs only if semicolon is absent)
        res = normalize_path_env('/c/bin:/d/bin')
        assert res == 'C:\\bin;D:\\bin'

        # Separated by ";"
        res2 = normalize_path_env('C:\\bin;/c/other_bin;C:\\bin')
        # Note the duplicate "C:\bin" should be removed
        assert res2 == 'C:\\bin;C:\\other_bin'

        # Mixed delimiters, extra empty entries.
        # Since ";" is present, splitting occurs on ";" ONLY.
        # This leaves "/d/bin:" which converts to "D:\bin:".
        res3 = normalize_path_env('/c/bin;;/d/bin:')
        assert res3 == 'C:\\bin;D:\\bin:'


def test_get_native_path_env() -> None:
    mock_env = {'PATH': '/c/bin:/d/bin'}
    with patch.dict(os.environ, mock_env):
        with (
            patch('backend.utils.path_normalize.os.name', 'nt'),
            patch('backend.utils.path_normalize.os.sep', '\\'),
        ):
            assert get_native_path_env() == 'C:\\bin;D:\\bin'


def test_which_normalized() -> None:
    mock_env = {'PATH': '/c/bin:/d/bin'}

    with patch.dict(os.environ, mock_env):
        with (
            patch('backend.utils.path_normalize.os.name', 'nt'),
            patch('backend.utils.path_normalize.os.sep', '\\'),
        ):
            with patch('shutil.which') as mock_which:
                mock_which.return_value = '/c/bin/git'

                # Run which_normalized
                res = which_normalized('git')

                # The returned path must be in Windows format
                assert res == 'C:\\bin\\git'

                # Verify shutil.which was called
                mock_which.assert_called_once_with('git')

                # Check environment variable restoration
                assert os.environ.get('PATH') == '/c/bin:/d/bin'


def test_which_normalized_not_found() -> None:
    mock_env = {'PATH': '/c/bin'}
    with patch.dict(os.environ, mock_env):
        with patch('shutil.which') as mock_which:
            mock_which.return_value = None
            assert which_normalized('not_exist') is None
