"""Tests for backend/core/workspace_resolution.py helpers."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import backend.core.workspace_resolution as workspace_resolution
from backend.core.os_capabilities import OSCapabilities, override_os_capabilities
from backend.core.workspace_resolution import (
    WORKSPACE_NOT_OPEN_ERROR_ID,
    WORKSPACE_NOT_OPEN_MESSAGE,
    apply_workspace_to_config,
    is_reserved_user_app_data_dir,
    is_workspace_not_open_error,
    load_persisted_workspace_path,
    normalize_user_workspace_path,
    require_effective_workspace_root,
    resolve_cli_workspace_directory,
    resolve_existing_directory,
    save_persisted_workspace_path,
)


def _set_fake_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    fake_home = tmp_path / 'home'
    fake_home.mkdir()
    monkeypatch.setenv('HOME', str(fake_home))
    monkeypatch.setenv('USERPROFILE', str(fake_home))
    return fake_home


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
    windows_caps = OSCapabilities(
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
    with override_os_capabilities(windows_caps):
        assert (
            normalize_user_workspace_path('file:///C:/Users/me/repo')
            == 'C:/Users/me/repo'
        )


def test_resolve_existing_directory_after_normalization(tmp_path) -> None:
    d = tmp_path / 'w'
    d.mkdir()
    quoted = f'"{d}"'
    assert resolve_existing_directory(quoted) == d.resolve()


def test_reserved_user_app_data_dir_matches_dot_app() -> None:
    assert is_reserved_user_app_data_dir(Path.home() / '.grinta') is True


def test_reserved_user_app_data_dir_returns_false_on_resolution_error() -> None:
    class BrokenPath:
        def resolve(self) -> Path:
            raise OSError('boom')

    assert is_reserved_user_app_data_dir(BrokenPath()) is False


def test_load_persisted_workspace_path_returns_none_when_missing(
    tmp_path, monkeypatch
) -> None:
    _set_fake_home(monkeypatch, tmp_path)

    assert load_persisted_workspace_path() is None


def test_save_and_load_persisted_workspace_path_round_trip(
    tmp_path, monkeypatch
) -> None:
    fake_home = _set_fake_home(monkeypatch, tmp_path)
    workspace = tmp_path / 'repo'
    workspace.mkdir()

    save_persisted_workspace_path(str(workspace))

    persisted = fake_home / '.grinta' / 'active_workspace.json'
    assert json.loads(persisted.read_text(encoding='utf-8')) == {
        'path': str(workspace.resolve())
    }
    assert load_persisted_workspace_path() == str(workspace.resolve())


@pytest.mark.parametrize(
    'payload',
    [
        '{bad json',
        json.dumps({'path': ''}),
        json.dumps({'path': 123}),
    ],
)
def test_load_persisted_workspace_path_returns_none_for_invalid_payloads(
    tmp_path,
    monkeypatch,
    payload: str,
) -> None:
    fake_home = _set_fake_home(monkeypatch, tmp_path)
    persisted = fake_home / '.grinta' / 'active_workspace.json'
    persisted.parent.mkdir(parents=True, exist_ok=True)
    persisted.write_text(payload, encoding='utf-8')

    assert load_persisted_workspace_path() is None


def test_load_persisted_workspace_path_ignores_reserved_path(
    tmp_path, monkeypatch
) -> None:
    fake_home = _set_fake_home(monkeypatch, tmp_path)
    reserved = fake_home / '.grinta'
    reserved.mkdir(exist_ok=True)
    persisted = reserved / 'active_workspace.json'
    persisted.write_text(json.dumps({'path': str(reserved)}), encoding='utf-8')

    assert load_persisted_workspace_path() is None


def test_load_persisted_workspace_path_returns_none_when_reserved_check_errors(
    tmp_path, monkeypatch
) -> None:
    fake_home = _set_fake_home(monkeypatch, tmp_path)
    workspace = tmp_path / 'repo'
    workspace.mkdir()
    persisted = fake_home / '.grinta' / 'active_workspace.json'
    persisted.parent.mkdir(parents=True, exist_ok=True)
    persisted.write_text(json.dumps({'path': str(workspace)}), encoding='utf-8')

    def _raise_oserror(_path: Path) -> bool:
        raise OSError('boom')

    monkeypatch.setattr(workspace_resolution, 'is_reserved_user_app_data_dir', _raise_oserror)

    assert load_persisted_workspace_path() is None


def test_save_persisted_workspace_path_rejects_reserved_workspace(
    tmp_path, monkeypatch
) -> None:
    fake_home = _set_fake_home(monkeypatch, tmp_path)
    reserved = fake_home / '.grinta'
    reserved.mkdir(exist_ok=True)

    with pytest.raises(ValueError, match='Refusing to persist reserved'):
        save_persisted_workspace_path(str(reserved))


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


def test_resolve_cli_workspace_directory_skips_reserved_project_root_env(
    tmp_path, monkeypatch
) -> None:
    fake_home = _set_fake_home(monkeypatch, tmp_path)
    reserved = fake_home / '.grinta'
    reserved.mkdir(exist_ok=True)
    app_root = tmp_path / 'app-root'
    app_root.mkdir()
    monkeypatch.setenv('PROJECT_ROOT', str(reserved))
    monkeypatch.setenv('APP_PROJECT_ROOT', str(app_root))

    assert resolve_cli_workspace_directory() == app_root.resolve()


def test_resolve_cli_workspace_directory_falls_back_to_config_when_env_invalid(
    tmp_path, monkeypatch
) -> None:
    config_root = tmp_path / 'config-root'
    config_root.mkdir()
    monkeypatch.setenv('PROJECT_ROOT', str(tmp_path / 'missing'))
    monkeypatch.delenv('APP_PROJECT_ROOT', raising=False)
    config = SimpleNamespace(project_root=str(config_root))

    assert resolve_cli_workspace_directory(config) == config_root.resolve()


def test_resolve_cli_workspace_directory_returns_none_for_reserved_cwd(
    tmp_path, monkeypatch
) -> None:
    fake_home = _set_fake_home(monkeypatch, tmp_path)
    reserved = fake_home / '.grinta'
    reserved.mkdir(exist_ok=True)
    monkeypatch.chdir(reserved)
    monkeypatch.delenv('PROJECT_ROOT', raising=False)
    monkeypatch.delenv('APP_PROJECT_ROOT', raising=False)

    assert resolve_cli_workspace_directory() is None


def test_workspace_path_from_raw_returns_none_on_resolution_error(
    monkeypatch,
) -> None:
    class BrokenPath:
        def __init__(self, _value: str) -> None:
            self.value = _value

        def expanduser(self) -> BrokenPath:
            return self

        def resolve(self) -> Path:
            raise OSError('boom')

    monkeypatch.setattr(workspace_resolution, 'Path', BrokenPath)

    assert workspace_resolution._workspace_path_from_raw('repo') is None


def test_resolve_cli_workspace_directory_returns_none_when_cwd_resolution_fails(
    monkeypatch,
) -> None:
    class BrokenCwd:
        def resolve(self) -> Path:
            raise OSError('boom')

    class BrokenPath:
        @staticmethod
        def cwd() -> BrokenCwd:
            return BrokenCwd()

    monkeypatch.delenv('PROJECT_ROOT', raising=False)
    monkeypatch.delenv('APP_PROJECT_ROOT', raising=False)
    monkeypatch.setattr(workspace_resolution, 'Path', BrokenPath)

    assert resolve_cli_workspace_directory() is None


def test_workspace_storage_id_stable_for_path(tmp_path) -> None:
    from backend.core.workspace_resolution import workspace_storage_id

    p = tmp_path / 'my' / 'repo'
    p.mkdir(parents=True)
    a = workspace_storage_id(p)
    b = workspace_storage_id(p)
    assert len(a) == 32
    assert a == b
    assert a.isalnum()


def test_workspace_agent_state_dir_creates_agent_bucket_for_explicit_root(
    tmp_path, monkeypatch
) -> None:
    fake_home = _set_fake_home(monkeypatch, tmp_path)
    project_root = tmp_path / 'repo'
    project_root.mkdir()

    agent_dir = workspace_resolution.workspace_agent_state_dir(project_root)

    expected_root = (
        fake_home
        / '.grinta'
        / 'workspaces'
        / workspace_resolution.workspace_storage_id(project_root)
        / 'agent'
    )
    assert agent_dir == expected_root
    assert agent_dir.is_dir()


def test_workspace_agent_state_dir_uses_effective_workspace_when_unset(
    tmp_path, monkeypatch
) -> None:
    fake_home = _set_fake_home(monkeypatch, tmp_path)
    project_root = tmp_path / 'repo'
    project_root.mkdir()
    monkeypatch.setattr(
        workspace_resolution,
        'require_effective_workspace_root',
        lambda: project_root,
    )

    agent_dir = workspace_resolution.workspace_agent_state_dir()

    expected_root = (
        fake_home
        / '.grinta'
        / 'workspaces'
        / workspace_resolution.workspace_storage_id(project_root)
        / 'agent'
    )
    assert agent_dir == expected_root
    assert agent_dir.is_dir()


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


def test_apply_workspace_to_config_rejects_reserved_dir(
    tmp_path, monkeypatch
) -> None:
    fake_home = _set_fake_home(monkeypatch, tmp_path)
    reserved = fake_home / '.grinta'
    reserved.mkdir(exist_ok=True)
    config = SimpleNamespace(project_root=None, local_data_root=None)

    with pytest.raises(ValueError, match='reserved for app data'):
        apply_workspace_to_config(config, reserved)


def test_resolve_existing_directory_rejects_missing_path(tmp_path) -> None:
    missing = tmp_path / 'missing'

    with pytest.raises(ValueError, match='Not a directory'):
        resolve_existing_directory(str(missing))


def test_require_effective_workspace_root_raises_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        workspace_resolution,
        'get_effective_workspace_root',
        lambda: None,
    )

    with pytest.raises(ValueError, match=WORKSPACE_NOT_OPEN_MESSAGE):
        require_effective_workspace_root()


def test_get_effective_workspace_root_loads_config_and_resolves(monkeypatch) -> None:
    import backend.core.config.config_loader as config_loader

    config = SimpleNamespace(project_root='from-config')
    captured: list[object] = []
    expected = Path('C:/repo')

    monkeypatch.setattr(
        config_loader,
        'load_app_config',
        lambda set_logging_levels=False: config,
    )
    monkeypatch.setattr(
        workspace_resolution,
        'resolve_cli_workspace_directory',
        lambda cfg=None: captured.append(cfg) or expected,
    )

    assert workspace_resolution.get_effective_workspace_root() == expected
    assert captured == [config]


def test_require_effective_workspace_root_returns_resolved_path(monkeypatch) -> None:
    expected = Path('C:/repo')
    monkeypatch.setattr(
        workspace_resolution,
        'get_effective_workspace_root',
        lambda: expected,
    )

    assert require_effective_workspace_root() == expected
