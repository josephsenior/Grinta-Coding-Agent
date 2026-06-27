"""Tests for WSL2 doctor checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.cli.doctor.checks import (
    check_wsl_layout,
    collect_wsl_checks,
)
from backend.core import wsl as wsl_mod
from backend.core.wsl import WslLayout


def test_collect_wsl_checks_empty_when_not_wsl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wsl_mod, 'is_wsl_runtime', lambda: False)
    assert collect_wsl_checks() == []


def test_check_wsl_layout_supported_split(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wsl_mod, 'is_wsl_runtime', lambda: True)
    check = check_wsl_layout(
        workspace=Path('/mnt/c/Users/foo/project'),
        repo_root=Path('/home/me/Grinta'),
    )
    assert check.ok is True
    assert 'supported split' in check.detail


def test_check_wsl_layout_repo_on_drvfs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wsl_mod, 'is_wsl_runtime', lambda: True)
    check = check_wsl_layout(
        workspace=Path('/mnt/c/Users/foo'),
        repo_root=Path('/mnt/c/Users/me/Grinta'),
    )
    assert check.ok is False
    assert '~/Grinta' in check.detail


def test_collect_wsl_checks_on_wsl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wsl_mod, 'is_wsl_runtime', lambda: True)
    monkeypatch.setattr(
        wsl_mod,
        'classify_wsl_layout',
        lambda **kwargs: WslLayout.IDEAL,
    )
    names = {check.name for check in collect_wsl_checks(workspace=Path('/home/me/p'))}
    assert 'wsl_runtime' in names
    assert 'wsl_layout' in names
    assert 'tmux_tmpdir' in names
