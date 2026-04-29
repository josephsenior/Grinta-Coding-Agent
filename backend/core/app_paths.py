"""Filesystem locations for app data (not the open-folder workspace).

``AppConfig.project_root`` is the open folder; ``local_data_root`` is the
LocalFileStore disk root for sessions and agent files. ``settings.json`` is
resolved once through :func:`get_app_settings_root` so the CLI, onboarding, and
runtime share a single configuration contract.
"""

from __future__ import annotations

import os
from pathlib import Path


def _source_checkout_root() -> Path:
    """Return the repository/package root implied by this module location."""
    return Path(__file__).resolve().parents[2]


def _looks_like_source_checkout(root: Path) -> bool:
    """True when *root* is the editable/source checkout rather than a wheel."""
    return (root / 'pyproject.toml').is_file() and (root / 'backend').is_dir()


def _settings_root_from_env() -> Path | None:
    """Return APP_ROOT override when explicitly configured."""
    raw = os.getenv('APP_ROOT')
    if raw is None or not raw.strip():
        return None
    return Path(raw).expanduser().resolve()


def get_canonical_settings_path() -> str:
    """Absolute canonical ``settings.json`` path for this installation."""
    return str(Path(get_app_settings_root()) / 'settings.json')


def get_app_settings_root() -> str:
    """Absolute directory containing canonical ``settings.json``.

    Resolution order:

    1. ``APP_ROOT`` when explicitly set.
    2. The source checkout root for editable/source runs.
    3. ``~/.grinta`` for installed wheel/pipx-style runs.
    """
    if env_root := _settings_root_from_env():
        return str(env_root)

    root = _source_checkout_root()
    if _looks_like_source_checkout(root):
        return str(root)

    return str((Path.home() / '.grinta').resolve())
