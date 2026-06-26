"""Pin Grinta install paths (logs, settings root) before the rest of the app loads."""

from __future__ import annotations

import os
from pathlib import Path


def resolve_grinta_repo_root() -> Path:
    """Return the Grinta source/install tree (directory containing pyproject.toml)."""
    override = os.getenv('GRINTA_REPO_ROOT', '').strip()
    if override:
        return Path(override).expanduser().resolve()

    marker = Path(__file__).resolve()
    for parent in marker.parents:
        if (parent / 'backend').is_dir() and (parent / 'pyproject.toml').is_file():
            return parent
    return marker.parents[2]


def pin_grinta_runtime_paths() -> Path:
    """Ensure logs and install metadata never follow the open project folder.

    Logs always live under ``<grinta-repo>/logs/`` (override with ``GRINTA_LOG_ROOT``).
    The user's workspace (Desktop, etc.) only selects a subdirectory name under
    ``logs/workspaces/`` — never the log root itself.
    """
    root = resolve_grinta_repo_root()
    os.environ.setdefault('GRINTA_REPO_ROOT', str(root))

    log_root_raw = os.getenv('GRINTA_LOG_ROOT', '').strip()
    if not log_root_raw:
        log_root_raw = str(root / 'logs')
        os.environ['GRINTA_LOG_ROOT'] = log_root_raw

    log_root = Path(log_root_raw)
    (log_root / 'workspaces').mkdir(parents=True, exist_ok=True)
    _record_cli_launch(log_root)
    return root


def _record_cli_launch(log_root: Path) -> None:
    """Append a line to ``logs/launch.log`` so the log tree is always visible."""
    import datetime
    import sys

    try:
        stamp = datetime.datetime.now(datetime.UTC).isoformat()
        project = os.environ.get('PROJECT_ROOT', '')
        line = (
            f'{stamp} pid={os.getpid()} cwd={os.getcwd()} '
            f'project={project} argv={" ".join(sys.argv)}\n'
        )
        with (log_root / 'launch.log').open('a', encoding='utf-8') as handle:
            handle.write(line)
    except OSError:
        pass


__all__ = ['pin_grinta_runtime_paths', 'resolve_grinta_repo_root']
