"""Tests for backend/core/workspace_resolution.py helpers."""

from __future__ import annotations

from pathlib import Path

from backend.core.workspace_resolution import (
    WORKSPACE_NOT_OPEN_ERROR_ID,
    WORKSPACE_NOT_OPEN_MESSAGE,
    apply_workspace_to_config,
    is_reserved_user_app_data_dir,
    is_workspace_not_open_error,
    normalize_user_workspace_path,
    resolve_cli_workspace_directory,
    resolve_existing_directory,
)


def test_is_workspace_not_open_error_matches_exact_valueerror() -> None:
    exc = ValueError(WORKSPACE_NOT_OPEN_MESSAGE)
    assert is_workspace_not_open_error(exc) is True


def test_is_workspace_not_open_error_rejects_other_valueerror() -> None:
    assert is_workspace_not_open_error(ValueError('other')) is False


def test_workspace_constants_stable() -> None:
    assert 'project folder' in WORKSPACE_NOT_OPEN_MESSAGE.lower()
    assert WORKSPACE_NOT_OPEN_ERROR_ID.startswith('WORKSPACE$')


def test_normalize_user_workspace_path_strips_quotes() -> None:
    assert normalize_user_workspace_path('  "/tmp/my project"  ') == '/tmp/my project'


def test_normalize_user_workspace_path_file_url_windows(monkeypatch) -> None:
    monkeypatch.setattr('sys.platform', 'win32')
    assert (
        normalize_user_workspace_path('file:///C:/Users/me/repo') == 'C:/Users/me/repo'
    )


def test_resolve_existing_directory_after_normalization(tmp_path) -> None:
    d = tmp_path / 'w'
    d.mkdir()
    quoted = f'"{d}"'
    assert resolve_existing_directory(quoted) == d.resolve()


def test_reserved_user_app_data_dir_matches_dot_app() -> None:
    assert is_reserved_user_app_data_dir(Path.home() / '.grinta') is True


def test_resolve_cli_workspace_directory_uses_cwd_when_unset(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('PROJECT_ROOT', raising=False)
    monkeypatch.delenv('APP_PROJECT_ROOT', raising=False)

    class _Cfg:
        project_root = None

    assert resolve_cli_workspace_directory(_Cfg()) == tmp_path.resolve()


def test_resolve_cli_workspace_directory_prefers_project_root_env(
    tmp_path, monkeypatch
) -> None:
    other = tmp_path / 'other'
    other.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('PROJECT_ROOT', str(other))

    class _Cfg:
        project_root = None

    assert resolve_cli_workspace_directory(_Cfg()) == other.resolve()


def test_workspace_storage_id_stable_for_path(tmp_path) -> None:
    from backend.core.workspace_resolution import workspace_storage_id

    p = tmp_path / 'my' / 'repo'
    p.mkdir(parents=True)
    a = workspace_storage_id(p)
    b = workspace_storage_id(p)
    assert len(a) == 32
    assert a == b
    assert a.isalnum()


def test_apply_workspace_to_config_uses_project_local_storage(
    tmp_path, monkeypatch
) -> None:
    fake = tmp_path / 'HOME'
    fake.mkdir()
    monkeypatch.setenv('HOME', str(fake))
    monkeypatch.setenv('USERPROFILE', str(fake))
    config = type('Config', (), {'project_root': None, 'local_data_root': None})()

    resolved = apply_workspace_to_config(config, tmp_path)

    from backend.core.workspace_resolution import workspace_storage_id

    wid = workspace_storage_id(tmp_path)
    expected = fake / '.grinta' / 'workspaces' / wid / 'storage'
    assert resolved == str(tmp_path)
    assert config.project_root == str(tmp_path)
    assert config.local_data_root == str(expected)
