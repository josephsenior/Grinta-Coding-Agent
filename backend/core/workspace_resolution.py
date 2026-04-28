"""Project/workspace directory resolution.

Where the workspace comes from:

1. ``AppConfig.project_root`` after :func:`backend.core.config.load_app_config`
   (from ``PROJECT_ROOT`` / ``settings.json`` / UI persistence).
2. **Terminal use:** if nothing is configured, the current working directory is the
   project folder (same as ``cd`` into the repo and run ``grinta``).

``~/.grinta`` alone is treated as app data, not a code workspace.

Per-project persistence (sessions, KB, etc.) lives under
``~/.grinta/workspaces/<id>/storage`` where ``<id>`` is derived from the resolved
workspace path — see :func:`workspace_grinta_root`. That keeps agent-visible repos
free of a bulky ``<repo>/.grinta/storage`` tree.

For storage roots see :func:`resolve_cli_workspace_directory` (env → config → cwd).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from backend.core.os_capabilities import OS_CAPS

logger = logging.getLogger(__name__)

# Stable text + id for tool/runtime errors when no project folder is available.
WORKSPACE_NOT_OPEN_MESSAGE = (
    'No project folder is configured. Run grinta from your project directory, '
    'use grinta --project PATH, or set project_root in settings.'
)
WORKSPACE_NOT_OPEN_ERROR_ID = 'WORKSPACE$NOT_OPEN'

_PERSIST_REL = Path('.grinta') / 'active_workspace.json'


def is_workspace_not_open_error(exc: BaseException) -> bool:
    """True if *exc* is the standard missing-workspace :class:`ValueError`."""
    return isinstance(exc, ValueError) and str(exc) == WORKSPACE_NOT_OPEN_MESSAGE


def _persist_file() -> Path:
    return Path.home() / _PERSIST_REL


def is_reserved_user_app_data_dir(path: Path) -> bool:
    """True if *path* is ``~/.grinta`` (app data dir, not a code workspace)."""
    try:
        resolved = path.resolve()
        home = Path.home().resolve()
        for name in ('.grinta',):
            if resolved == (home / name).resolve():
                return True
    except (OSError, ValueError):
        return False
    return False


def workspace_storage_id(project_root: str | Path) -> str:
    """Stable id for *project_root* (hex digest, filesystem-safe).

    Uses the resolved path with OS-appropriate case normalization so the same
    folder maps to one bucket on case-insensitive volumes.
    """
    p = Path(project_root).expanduser().resolve()
    key = os.path.normcase(str(p))
    return hashlib.sha256(key.encode('utf-8')).hexdigest()[:32]


def workspace_grinta_root(project_root: str | Path) -> Path:
    """``~/.grinta/workspaces/<id>`` for app data tied to this workspace."""
    wid = workspace_storage_id(project_root)
    return Path.home() / '.grinta' / 'workspaces' / wid


def workspace_agent_state_dir(project_root: str | Path | None = None) -> Path:
    """Agent-internal durable state: ``~/.grinta/workspaces/<id>/agent/``.

    For one-off moves from old in-repo layouts use ``grinta --cleanup-storage``.
    """
    if project_root is None:
        root = require_effective_workspace_root()
    else:
        root = Path(project_root).expanduser().resolve()
    bucket = workspace_grinta_root(root)
    bucket.mkdir(parents=True, exist_ok=True)
    agent = bucket / 'agent'
    agent.mkdir(parents=True, exist_ok=True)
    return agent


def load_persisted_workspace_path() -> str | None:
    """Return last saved workspace path if valid and not a reserved data directory."""
    p = _persist_file()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
        path = data.get('path')
        if not isinstance(path, str) or not path.strip():
            return None
        try:
            if is_reserved_user_app_data_dir(Path(path).expanduser().resolve()):
                return None
        except OSError:
            return None
        return path.strip()
    except (OSError, json.JSONDecodeError, TypeError):
        logger.debug('Could not read workspace persistence file', exc_info=True)
    return None


def save_persisted_workspace_path(path: str) -> None:
    """Write workspace path for next backend start."""
    resolved = str(Path(path).resolve())
    if is_reserved_user_app_data_dir(Path(resolved)):
        msg = (
            f'Refusing to persist reserved app user data path as workspace: {resolved}'
        )
        raise ValueError(msg)
    p = _persist_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({'path': resolved}, indent=2), encoding='utf-8')


def normalize_user_workspace_path(path_str: str) -> str:
    """Strip whitespace, optional quotes, and ``file://`` URLs from UI-pasted paths."""
    s = path_str.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in '"\'':
        s = s[1:-1].strip()
    if s.lower().startswith('file:'):
        parsed = urlparse(s)
        path = unquote(parsed.path or '')
        if (
            OS_CAPS.is_windows
            and len(path) >= 3
            and path[0] == '/'
            and path[2] == ':'
        ):
            path = path[1:]
        s = path
    return s


def resolve_existing_directory(path_str: str) -> Path:
    """Expand user home, resolve, and require a real directory."""
    normalized = normalize_user_workspace_path(path_str)
    p = Path(normalized).expanduser().resolve()
    if not p.is_dir():
        msg = f'Not a directory or does not exist: {p}'
        raise ValueError(msg)
    return p


def apply_workspace_to_config(config, root: Path) -> str:
    """Set project workspace on config and pin project-local persistent storage."""
    if is_reserved_user_app_data_dir(root):
        msg = (
            'That folder is reserved for app data. Choose a project directory instead.'
        )
        raise ValueError(msg)
    from backend.persistence.locations import get_project_local_data_root

    s = str(root)
    config.project_root = s
    config.local_data_root = get_project_local_data_root(root)
    return s


def _workspace_path_from_raw(raw: str | None) -> Path | None:
    if not raw or not str(raw).strip():
        return None
    try:
        p = Path(str(raw).strip()).expanduser().resolve()
    except OSError:
        return None
    if not p.is_dir() or is_reserved_user_app_data_dir(p):
        return None
    return p


def resolve_cli_workspace_directory(config: object | None = None) -> Path | None:
    """Directory treated as the open project for ``cd repo && grinta``.

    This is the *storage* anchor: LocalFileStore defaults to
    ``~/.grinta/workspaces/<id>/storage`` for this directory. Resolution order:

    1. ``PROJECT_ROOT`` then ``APP_PROJECT_ROOT`` (CLI pins the former to the cwd
       or ``--project`` before loading config).
    2. ``project_root`` on *config* when it is a non-empty string (e.g. from
       ``settings.json``).
    3. :func:`os.getcwd` — the normal case when you run Grinta from your repo.

    ``~/.grinta`` is never used as a code workspace here (reserved app data home).
    """
    import os

    for key in ('PROJECT_ROOT', 'APP_PROJECT_ROOT'):
        got = _workspace_path_from_raw(os.environ.get(key))
        if got is not None:
            return got
    if config is not None:
        pr = getattr(config, 'project_root', None)
        if isinstance(pr, str) and pr.strip():
            got = _workspace_path_from_raw(pr)
            if got is not None:
                return got
    try:
        cwd = Path.cwd().resolve()
    except OSError:
        return None
    if is_reserved_user_app_data_dir(cwd):
        return None
    return cwd


def get_effective_workspace_root() -> Path | None:
    """Return the project folder, or ``None`` if it cannot be determined safely.

    Order: ``PROJECT_ROOT`` env (CLI pins this to the directory you launched from),
    ``APP_PROJECT_ROOT``, then :attr:`AppConfig.project_root`, then the process cwd.
    """
    from backend.core.config.config_loader import load_app_config

    cfg = load_app_config(set_logging_levels=False)
    return resolve_cli_workspace_directory(cfg)


def require_effective_workspace_root() -> Path:
    """Like :func:`get_effective_workspace_root` but raises if no folder is open."""
    p = get_effective_workspace_root()
    if p is None:
        raise ValueError(WORKSPACE_NOT_OPEN_MESSAGE)
    return p
