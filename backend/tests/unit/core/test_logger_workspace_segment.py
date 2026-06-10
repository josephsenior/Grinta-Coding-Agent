"""Tests for workspace log directory resolution in backend.core.logger."""

from __future__ import annotations

import hashlib
import os
import re

import pytest

from backend.core import logger as logger_mod


def test_workspace_logs_segment_uses_project_root(monkeypatch: pytest.MonkeyPatch, tmp_path):
    root = tmp_path / 'my_repo'
    root.mkdir()
    monkeypatch.setenv('PROJECT_ROOT', str(root))
    monkeypatch.delenv('APP_PROJECT_ROOT', raising=False)

    segment = logger_mod._workspace_logs_segment()
    assert segment is not None
    assert segment.startswith('my_repo__')
    digest = hashlib.sha256(os.path.normcase(os.path.normpath(str(root))).encode()).hexdigest()[:12]
    assert segment == f'my_repo__{digest}'


def test_workspace_logs_segment_falls_back_to_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    monkeypatch.delenv('PROJECT_ROOT', raising=False)
    monkeypatch.delenv('APP_PROJECT_ROOT', raising=False)
    monkeypatch.chdir(tmp_path)

    segment = logger_mod._workspace_logs_segment()
    assert segment is not None
    digest = hashlib.sha256(os.path.normcase(os.path.normpath(str(tmp_path))).encode()).hexdigest()[:12]
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


def test_bind_session_logging_skips_without_workspace(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(logger_mod, 'LOG_TO_FILE', True)
    monkeypatch.setattr(logger_mod, '_workspace_logs_dir', lambda: None)

    logger_mod.bind_session_logging('test-session-id')

    assert logger_mod._LOG_SESSION_ID is None
