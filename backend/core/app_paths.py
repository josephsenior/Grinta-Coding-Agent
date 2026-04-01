"""Filesystem locations for app data (not the open-folder workspace).

``AppConfig.project_root`` is the open folder; ``local_data_root`` is the LocalFileStore disk root.
(sessions, agent files).  LLM settings, secrets, and ``settings.json`` must stay in a
stable directory — typically the directory where the server was started.
"""

from __future__ import annotations

import os


def get_app_settings_root() -> str:
    """Absolute directory containing the canonical ``settings.json``.

    Search order:
    1. ``APP_ROOT`` env var (if set)
    2. Current working directory (if ``settings.json`` exists there)
    3. ``~/.grinta/`` user-level config directory (global fallback)
    4. Current working directory (for creation if nothing found)
    """
    override = (os.environ.get('APP_ROOT') or '').strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))

    cwd = os.path.abspath(os.getcwd())
    if os.path.isfile(os.path.join(cwd, 'settings.json')):
        return cwd

    user_dir = os.path.join(os.path.expanduser('~'), '.grinta')
    if os.path.isfile(os.path.join(user_dir, 'settings.json')):
        return user_dir

    return cwd
