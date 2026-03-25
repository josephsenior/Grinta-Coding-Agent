"""User-selected project folder (workspace) only.

The workspace path is whatever folder the user sets via **Open workspace** (and optional
persisted ``~/.forge/app/active_workspace.json``). There is no fallback to ``cwd()`` or
``~/.Forge`` as a project root.

Machine-local session files use :func:`backend.core.app_paths.get_app_settings_root` when
no workspace is open (see ``AppState``).
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)

# Stable text + id for tool/runtime errors when no project folder is open (UI may toast once).
WORKSPACE_NOT_OPEN_MESSAGE = (
    "No project folder is open. Choose a folder via Open workspace first."
)
WORKSPACE_NOT_OPEN_ERROR_ID = "WORKSPACE$NOT_OPEN"

_PERSIST_REL = Path(".forge") / "app" / "active_workspace.json"


def is_workspace_not_open_error(exc: BaseException) -> bool:
    """True if *exc* is the standard missing-workspace :class:`ValueError`."""
    return isinstance(exc, ValueError) and str(exc) == WORKSPACE_NOT_OPEN_MESSAGE


def _persist_file() -> Path:
    return Path.home() / _PERSIST_REL


def is_reserved_user_forge_data_dir(path: Path) -> bool:
    """True if *path* is ``~/.Forge`` or ``~/.forge`` (app data dirs, not a code workspace)."""
    try:
        resolved = path.resolve()
        home = Path.home().resolve()
        for name in (".Forge", ".forge"):
            if resolved == (home / name).resolve():
                return True
    except (OSError, ValueError):
        return False
    return False


def load_persisted_workspace_path() -> str | None:
    """Return last saved workspace path if valid and not a reserved data directory."""
    p = _persist_file()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        path = data.get("path")
        if not isinstance(path, str) or not path.strip():
            return None
        try:
            if is_reserved_user_forge_data_dir(Path(path).expanduser().resolve()):
                return None
        except OSError:
            return None
        return path.strip()
    except (OSError, json.JSONDecodeError, TypeError):
        logger.debug("Could not read workspace persistence file", exc_info=True)
    return None


def save_persisted_workspace_path(path: str) -> None:
    """Write workspace path for next backend start."""
    resolved = str(Path(path).resolve())
    if is_reserved_user_forge_data_dir(Path(resolved)):
        msg = f"Refusing to persist reserved Forge user data path as workspace: {resolved}"
        raise ValueError(msg)
    p = _persist_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"path": resolved}, indent=2), encoding="utf-8")


def normalize_user_workspace_path(path_str: str) -> str:
    """Strip whitespace, optional quotes, and ``file://`` URLs from UI-pasted paths."""
    s = path_str.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1].strip()
    if s.lower().startswith("file:"):
        parsed = urlparse(s)
        path = unquote(parsed.path or "")
        if sys.platform == "win32" and len(path) >= 3 and path[0] == "/" and path[2] == ":":
            path = path[1:]
        s = path
    return s


def resolve_existing_directory(path_str: str) -> Path:
    """Expand user home, resolve, and require a real directory."""
    normalized = normalize_user_workspace_path(path_str)
    p = Path(normalized).expanduser().resolve()
    if not p.is_dir():
        msg = f"Not a directory or does not exist: {p}"
        raise ValueError(msg)
    return p


def apply_workspace_to_config(config, root: Path) -> str:
    """Set project workspace on config; same path is used for conversation file store."""
    if is_reserved_user_forge_data_dir(root):
        msg = (
            "That folder is reserved for Forge app data. Choose a project directory instead."
        )
        raise ValueError(msg)
    s = str(root)
    config.project_root = s
    config.local_data_root = s
    return s


def get_effective_workspace_root() -> Path | None:
    """Return the open project folder, or ``None`` if the user has not chosen one."""
    try:
        from backend.api.app_state import get_app_state

        wb = (get_app_state().config.project_root or "").strip()
        if wb:
            return Path(wb).expanduser().resolve()
    except Exception:
        pass

    from backend.core.config.config_loader import load_forge_config

    wb = (load_forge_config(set_logging_levels=False).project_root or "").strip()
    if wb:
        return Path(wb).expanduser().resolve()
    return None


def require_effective_workspace_root() -> Path:
    """Like :func:`get_effective_workspace_root` but raises if no folder is open."""
    p = get_effective_workspace_root()
    if p is None:
        raise ValueError(WORKSPACE_NOT_OPEN_MESSAGE)
    return p
