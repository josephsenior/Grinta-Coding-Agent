"""Tests for backend.core.app_paths."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from backend.core import app_paths


def test_app_root_env_overrides_settings_root(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_ROOT', str(tmp_path))

    assert app_paths.get_app_settings_root() == str(tmp_path.resolve())
    assert app_paths.get_canonical_settings_path() == str(
        tmp_path.resolve() / 'settings.json'
    )


def test_source_checkout_uses_repo_root(monkeypatch):
    monkeypatch.delenv('APP_ROOT', raising=False)

    root = Path(app_paths.get_app_settings_root())

    assert (root / 'pyproject.toml').is_file()
    assert (root / 'backend').is_dir()


def test_installed_package_falls_back_to_user_grinta_root(tmp_path, monkeypatch):
    monkeypatch.delenv('APP_ROOT', raising=False)
    package_root = tmp_path / 'site-packages'
    package_root.mkdir()
    home = tmp_path / 'home'
    home.mkdir()

    with (
        patch('backend.core.app_paths._source_checkout_root', return_value=package_root),
        patch('backend.core.app_paths.Path.home', return_value=home),
    ):
        assert app_paths.get_app_settings_root() == str((home / '.grinta').resolve())
