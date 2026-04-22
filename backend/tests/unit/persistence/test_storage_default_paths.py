"""Tests for canonical conversation persistence roots."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.core.config.app_config import AppConfig
from backend.core.workspace_resolution import workspace_storage_id
from backend.persistence.conversation.file_conversation_store import (
    FileConversationStore,
)
from backend.persistence.knowledge_base.knowledge_base_store import KnowledgeBaseStore
from backend.persistence.locations import (
    get_local_data_root,
    get_project_local_data_root,
)


def _fake_user_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Isolate ~/.grinta/workspaces/* under tmp_path for tests."""
    fake = tmp_path / 'USER_HOME'
    fake.mkdir()
    monkeypatch.setenv('HOME', str(fake))
    monkeypatch.setenv('USERPROFILE', str(fake))
    monkeypatch.delenv('PROJECT_ROOT', raising=False)
    monkeypatch.delenv('APP_PROJECT_ROOT', raising=False)
    return fake


def _workspace_store(fake_home: Path, workspace: Path) -> Path:
    wid = workspace_storage_id(workspace)
    return fake_home / '.grinta' / 'workspaces' / wid / 'storage'


def test_get_local_data_root_empty_uses_grinta_under_settings_parent(
    tmp_path, monkeypatch
) -> None:
    fake_home = _fake_user_home(monkeypatch, tmp_path)
    (tmp_path / 'settings.json').write_text('{}', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('PROJECT_ROOT', raising=False)
    monkeypatch.delenv('APP_PROJECT_ROOT', raising=False)
    cfg = AppConfig.model_validate({'local_data_root': '', 'project_root': None})
    assert Path(get_local_data_root(cfg)) == _workspace_store(fake_home, tmp_path)


def test_get_local_data_root_respects_project_root_env(tmp_path, monkeypatch) -> None:
    fake_home = _fake_user_home(monkeypatch, tmp_path)
    ws = tmp_path / 'proj'
    ws.mkdir()
    monkeypatch.setenv('PROJECT_ROOT', str(ws))
    monkeypatch.delenv('APP_PROJECT_ROOT', raising=False)
    cfg = AppConfig.model_validate({'local_data_root': '', 'project_root': None})
    assert Path(get_local_data_root(cfg)) == _workspace_store(fake_home, ws)


def test_get_local_data_root_redirects_bare_workspace_path(
    tmp_path, monkeypatch
) -> None:
    fake_home = _fake_user_home(monkeypatch, tmp_path)
    ws = tmp_path / 'repo'
    ws.mkdir()
    cfg = AppConfig(
        project_root=str(ws),
        local_data_root=str(ws),
    )
    assert Path(get_local_data_root(cfg)) == _workspace_store(fake_home, ws)


def test_get_local_data_root_redirects_repo_root_sessions_folder(
    tmp_path, monkeypatch
) -> None:
    fake_home = _fake_user_home(monkeypatch, tmp_path)
    ws = tmp_path / 'repo'
    ws.mkdir()
    legacy = ws / 'sessions'
    legacy.mkdir()
    cfg = AppConfig(project_root=str(ws), local_data_root=str(legacy))
    assert Path(get_local_data_root(cfg)) == _workspace_store(fake_home, ws)


def test_get_local_data_root_redirects_workspace_storage_folder(
    tmp_path, monkeypatch
) -> None:
    fake_home = _fake_user_home(monkeypatch, tmp_path)
    ws = tmp_path / 'repo'
    ws.mkdir()
    (ws / 'storage').mkdir()
    cfg = AppConfig(project_root=str(ws), local_data_root=str(ws / 'storage'))
    assert Path(get_local_data_root(cfg)) == _workspace_store(fake_home, ws)


def test_get_local_data_root_redirects_when_workspace_unresolved_but_cwd_is_project(
    tmp_path, monkeypatch
) -> None:
    fake_home = _fake_user_home(monkeypatch, tmp_path)
    repo = tmp_path / 'repo'
    repo.mkdir()
    monkeypatch.chdir(repo)
    monkeypatch.setattr(
        'backend.core.workspace_resolution.resolve_cli_workspace_directory',
        lambda _cfg=None: None,
    )
    dot = AppConfig.model_validate({'local_data_root': '.', 'project_root': None})
    assert Path(get_local_data_root(dot)) == _workspace_store(fake_home, repo)

    sess = AppConfig.model_validate(
        {'local_data_root': 'sessions', 'project_root': None}
    )
    assert Path(get_local_data_root(sess)) == _workspace_store(fake_home, repo)

    stor = AppConfig.model_validate(
        {'local_data_root': 'storage', 'project_root': None}
    )
    assert Path(get_local_data_root(stor)) == _workspace_store(fake_home, repo)


def test_get_project_local_data_root_migrates_legacy_in_repo_storage(
    tmp_path, monkeypatch
) -> None:
    fake_home = _fake_user_home(monkeypatch, tmp_path)
    ws = tmp_path / 'proj'
    ws.mkdir()
    legacy_sess = ws / '.grinta' / 'storage' / 'sessions' / 's1'
    legacy_sess.mkdir(parents=True)
    (legacy_sess / 'marker.txt').write_text('migrated', encoding='utf-8')
    dest = _workspace_store(fake_home, ws)
    assert not dest.exists()
    root = Path(get_project_local_data_root(ws))
    assert root == dest.resolve()
    assert (root / 'sessions' / 's1' / 'marker.txt').read_text(
        encoding='utf-8'
    ) == 'migrated'
    assert not (ws / '.grinta' / 'storage').exists()


def test_get_local_data_root_keeps_subdir_under_workspace_storage(
    tmp_path, monkeypatch
) -> None:
    fake_home = _fake_user_home(monkeypatch, tmp_path)
    ws = tmp_path / 'repo'
    ws.mkdir()
    canon = Path(get_project_local_data_root(ws))
    nested = canon / 'extra'
    nested.mkdir(parents=True)
    cfg = AppConfig(project_root=str(ws), local_data_root=str(nested))
    assert Path(get_local_data_root(cfg)) == nested.resolve()


def test_file_conversation_store_uses_configured_local_data_root(tmp_path) -> None:
    file_store = MagicMock()
    data_root = tmp_path / '.grinta' / 'storage'
    config = AppConfig(local_data_root=str(data_root), project_root=None)

    store = FileConversationStore(file_store=file_store, config=config, user_id=None)

    assert store._local_conversations_dir == data_root / 'sessions'
    assert store._local_conversations_dir.exists()


def test_file_conversation_store_uses_app_dir_under_project_root(
    tmp_path, monkeypatch
) -> None:
    _fake_user_home(monkeypatch, tmp_path)
    file_store = MagicMock()
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    root = Path(get_project_local_data_root(workspace))
    config = AppConfig(
        project_root=str(workspace),
        local_data_root=str(root),
    )

    store = FileConversationStore(file_store=file_store, config=config, user_id='u1')

    assert store._local_conversations_dir == root / 'users' / 'u1' / 'conversations'
    assert store._local_conversations_dir.exists()


def test_knowledge_base_store_defaults_to_home_app_kb(tmp_path) -> None:
    with patch(
        'backend.persistence.knowledge_base.knowledge_base_store.get_active_local_data_root',
        return_value=str(tmp_path / '.grinta' / 'storage'),
    ):
        store = KnowledgeBaseStore(storage_dir=None)

    assert store.storage_dir == tmp_path / '.grinta' / 'storage' / 'kb'
    assert store.storage_dir.exists()


def test_knowledge_base_store_keeps_explicit_storage_dir(tmp_path) -> None:
    storage_dir = tmp_path / 'custom-kb'

    store = KnowledgeBaseStore(storage_dir=storage_dir)

    assert store.storage_dir == storage_dir
    assert store.storage_dir.exists()
