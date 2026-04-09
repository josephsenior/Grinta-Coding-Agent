"""Filesystem locations for app data (not the open-folder workspace).

``AppConfig.project_root`` is the open folder; ``local_data_root`` is the LocalFileStore disk root.
(sessions, agent files). ``settings.json`` is anchored to the Grinta repository root
to keep a single source of truth.
"""

from __future__ import annotations

from pathlib import Path


def get_canonical_settings_path() -> str:
    """Absolute canonical ``settings.json`` path inside the Grinta repository."""
    return str(Path(get_app_settings_root()) / 'settings.json')


def get_app_settings_root() -> str:
    """Absolute directory containing canonical ``settings.json``.

    This is always the repository root (parent of ``backend/``), regardless of
    process working directory, home directory, or environment overrides.
    """
    return str(Path(__file__).resolve().parents[2])
