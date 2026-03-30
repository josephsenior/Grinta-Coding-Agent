"""Filesystem locations for app data (not the open-folder workspace).

``AppConfig.project_root`` is the open folder; ``local_data_root`` is the LocalFileStore disk root.
(sessions, agent files).  LLM settings, secrets, and ``settings.json`` must stay in a
stable directory — typically the directory where the server was started.
"""

from __future__ import annotations

import os


def get_app_settings_root() -> str:
    """Absolute directory containing the canonical ``settings.json``.

    - ``APP_ROOT``: if set, this path is used (expanded, absolute).
    - Otherwise: current working directory when the backend resolves the path.

    This is **not** the per-project workspace root from Open folder.
    """
    override = (os.environ.get("APP_ROOT") or "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    return os.path.abspath(os.getcwd())
