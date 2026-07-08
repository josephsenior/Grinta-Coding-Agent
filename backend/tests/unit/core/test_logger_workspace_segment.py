"""Tests for workspace log directory resolution in backend.core.logging.logger."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import pytest

from backend.core.logging import logger as logger_mod


def test_grinta_install_tree_root_points_at_repo_root():
    install_root = Path(logger_mod._grinta_install_tree_root())
    assert install_root.name != 'backend'
    assert (install_root / 'backend' / 'core' / 'logging' / 'logger.py').is_file()


def test_workspace_logs_dir_under_repo_logs_not_backend_logs(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    monkeypatch.setenv('PROJECT_ROOT', str(tmp_path))
    monkeypatch.delenv('APP_PROJECT_ROOT', raising=False)
    monkeypatch.delenv('GRINTA_LOG_ROOT', raising=False)
    monkeypatch.delenv('GRINTA_REPO_ROOT', raising=False)
    ws_dir = logger_mod._workspace_logs_dir()
    assert ws_dir is not None
    install_root = Path(logger_mod._grinta_install_tree_root())
    assert (
        Path(ws_dir)
        == install_root / 'logs' / 'workspaces' / logger_mod._workspace_logs_segment()
    )


def test_grinta_log_base_honors_override(monkeypatch: pytest.MonkeyPatch, tmp_path):
    custom = tmp_path / 'custom_logs'
    monkeypatch.setenv('GRINTA_LOG_ROOT', str(custom))
    assert logger_mod._grinta_log_base() == str(custom.resolve())


def test_workspace_logs_segment_uses_project_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    root = tmp_path / 'my_repo'
    root.mkdir()
    monkeypatch.setenv('PROJECT_ROOT', str(root))
    monkeypatch.delenv('APP_PROJECT_ROOT', raising=False)

    segment = logger_mod._workspace_logs_segment()
    assert segment is not None
    assert segment.startswith('my_repo__')
    digest = hashlib.sha256(
        os.path.normcase(os.path.normpath(str(root))).encode()
    ).hexdigest()[:12]
    assert segment == f'my_repo__{digest}'


def test_workspace_logs_segment_falls_back_to_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    monkeypatch.delenv('PROJECT_ROOT', raising=False)
    monkeypatch.delenv('APP_PROJECT_ROOT', raising=False)
    monkeypatch.chdir(tmp_path)

    segment = logger_mod._workspace_logs_segment()
    assert segment is not None
    digest = hashlib.sha256(
        os.path.normcase(os.path.normpath(str(tmp_path))).encode()
    ).hexdigest()[:12]
    base = os.path.basename(str(tmp_path))
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', base)[:48].strip('_') or 'workspace'
    assert segment == f'{safe}__{digest}'


def test_workspace_logs_segment_none_when_cwd_unusable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv('PROJECT_ROOT', raising=False)
    monkeypatch.delenv('APP_PROJECT_ROOT', raising=False)

    def _raise_oserror() -> str:
        raise OSError('no cwd')

    monkeypatch.setattr(logger_mod.os, 'getcwd', _raise_oserror)

    assert logger_mod._workspace_logs_segment() is None


def test_bind_session_logging_uses_fallback_without_workspace(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(logger_mod, 'LOG_TO_FILE', True)
    monkeypatch.setattr(logger_mod, '_workspace_logs_dir', lambda: None)

    logger_mod.bind_session_logging('test-session-id')

    assert logger_mod._LOG_SESSION_ID == 'test-session-id'
    assert 'unbound_logs' in (logger_mod._ACTIVE_SESSION_LOG_DIR or '')


def test_bind_session_logging_creates_session_jsonl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    install_root = tmp_path / 'install'
    ws_root = install_root / 'logs' / 'workspaces' / 'sample_ws'
    ws_root.mkdir(parents=True)
    monkeypatch.setattr(logger_mod, 'LOG_TO_FILE', True)
    monkeypatch.setattr(logger_mod, '_workspace_logs_dir', lambda: str(ws_root))
    monkeypatch.setattr(logger_mod, '_workspace_logs_segment', lambda: 'sample_ws')
    monkeypatch.setattr(logger_mod, '_LOG_SESSION_ID', None)
    monkeypatch.setattr(logger_mod, '_ACTIVE_SESSION_LOG_DIR', None)

    logger_mod.bind_session_logging('my-session-123')

    session_dir = ws_root / 'sessions' / 'my-session-123'
    assert session_dir.is_dir()
    jsonl = session_dir / 'session.jsonl'
    assert jsonl.is_file()
    assert 'SESSION_START' in jsonl.read_text(encoding='utf-8')


def test_workspace_logs_dir_uses_canonical_root_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    install_root = tmp_path / 'install'
    legacy_ws = install_root / 'backend' / 'logs' / 'workspaces' / 'sample_ws'
    legacy_ws.mkdir(parents=True)
    (legacy_ws / 'app.log').write_text('legacy\n', encoding='utf-8')

    monkeypatch.setattr(
        logger_mod, '_grinta_install_tree_root', lambda: str(install_root)
    )
    monkeypatch.setattr(logger_mod, '_workspace_logs_segment', lambda: 'sample_ws')

    ws_dir = Path(logger_mod._workspace_logs_dir() or '')
    canonical_ws = install_root / 'logs' / 'workspaces' / 'sample_ws'
    assert ws_dir == canonical_ws
    assert not canonical_ws.exists() or not (canonical_ws / 'app.log').exists()
    assert legacy_ws.exists()
    assert (legacy_ws / 'app.log').read_text(encoding='utf-8') == 'legacy\n'
