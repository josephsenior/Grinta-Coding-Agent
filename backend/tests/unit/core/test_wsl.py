"""Tests for WSL2 layout helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.core import wsl as wsl_mod
from backend.core.wsl import WslLayout, classify_wsl_layout, is_windows_mount


def test_is_windows_mount_detects_drvfs() -> None:
    assert is_windows_mount('/mnt/c/Users/foo')
    assert is_windows_mount(Path('/mnt/d/project'))
    assert not is_windows_mount('/home/user/project')
    assert not is_windows_mount('~/Grinta')


def test_classify_wsl_layout_not_wsl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wsl_mod, 'is_wsl_runtime', lambda: False)
    assert (
        classify_wsl_layout(workspace='/mnt/c/project', repo_root='~/Grinta')
        == WslLayout.NOT_WSL
    )


def test_classify_wsl_layout_supported_split(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wsl_mod, 'is_wsl_runtime', lambda: True)
    assert (
        classify_wsl_layout(workspace='/mnt/c/Users/foo', repo_root='/home/me/Grinta')
        == WslLayout.SUPPORTED_SPLIT
    )


def test_classify_wsl_layout_repo_on_drvfs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wsl_mod, 'is_wsl_runtime', lambda: True)
    assert (
        classify_wsl_layout(
            workspace='/home/me/project',
            repo_root='/mnt/c/example/Grinta',
        )
        == WslLayout.REPO_ON_DRVFS
    )


def test_classify_wsl_layout_both_on_drvfs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wsl_mod, 'is_wsl_runtime', lambda: True)
    assert (
        classify_wsl_layout(
            workspace='/mnt/c/Users/foo',
            repo_root='/mnt/c/example/Grinta',
        )
        == WslLayout.BOTH_ON_DRVFS
    )


def test_classify_wsl_layout_ideal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wsl_mod, 'is_wsl_runtime', lambda: True)
    assert (
        classify_wsl_layout(workspace='/home/me/project', repo_root='/home/me/Grinta')
        == WslLayout.IDEAL
    )


def test_is_wsl_runtime_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('WSL_DISTRO_NAME', raising=False)
    monkeypatch.delenv('WSL_INTEROP', raising=False)
    monkeypatch.setattr(wsl_mod.sys, 'platform', 'linux')
    monkeypatch.setattr(
        wsl_mod.Path,
        'read_text',
        lambda self, encoding='utf-8': 'Linux version 5.15.0-microsoft-standard',
        raising=False,
    )
    monkeypatch.setenv('WSL_DISTRO_NAME', 'Ubuntu-24.04')
    assert wsl_mod.is_wsl_runtime() is True
    assert wsl_mod.wsl_distro_name() == 'Ubuntu-24.04'
