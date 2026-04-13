"""Helper functions for computing conversation-related storage paths."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from backend.core.constants import CONVERSATION_BASE_DIR  # noqa: E402

if TYPE_CHECKING:
    from backend.core.config.app_config import AppConfig


def get_conversation_dir(sid: str, user_id: str | None = None) -> str:
    """Get the conversation directory path.

    Args:
        sid: The session/conversation ID.
        user_id: Optional user ID for user-specific paths.

    Returns:
        str: The conversation directory path.

    """
    if user_id:
        return f'users/{user_id}/conversations/{sid}/'
    return f'{CONVERSATION_BASE_DIR}/{sid}/'


def get_conversation_events_dir(sid: str, user_id: str | None = None) -> str:
    """Get the conversation events directory path.

    Args:
        sid: The session/conversation ID.
        user_id: Optional user ID for user-specific paths.

    Returns:
        str: The events directory path.

    """
    return f'{get_conversation_dir(sid, user_id)}events/'


def get_conversation_event_filename(
    sid: str, id: int, user_id: str | None = None
) -> str:
    """Get the filename for a specific conversation event.

    Args:
        sid: The session/conversation ID.
        id: The event ID.
        user_id: Optional user ID for user-specific paths.

    Returns:
        str: The full path to the event file.

    """
    return f'{get_conversation_events_dir(sid, user_id)}{id}.json'


def get_conversation_metadata_filename(sid: str, user_id: str | None = None) -> str:
    """Get the conversation metadata filename.

    Args:
        sid: The session/conversation ID.
        user_id: Optional user ID for user-specific paths.

    Returns:
        str: The full path to the metadata file.

    """
    return f'{get_conversation_dir(sid, user_id)}metadata.json'


def get_conversation_init_data_filename(sid: str, user_id: str | None = None) -> str:
    """Get the conversation initialization data filename.

    Args:
        sid: The session/conversation ID.
        user_id: Optional user ID for user-specific paths.

    Returns:
        str: The full path to the initialization data file.

    """
    return f'{get_conversation_dir(sid, user_id)}init.json'


def get_conversation_agent_state_filename(sid: str, user_id: str | None = None) -> str:
    """Get the conversation agent state filename.

    Args:
        sid: The session/conversation ID.
        user_id: Optional user ID for user-specific paths.

    Returns:
        str: The full path to the agent state file.

    """
    return f'{get_conversation_dir(sid, user_id)}agent_state.pkl'


def get_conversation_llm_registry_filename(sid: str, user_id: str | None = None) -> str:
    """Get the conversation LLM registry filename.

    Args:
        sid: The session/conversation ID.
        user_id: Optional user ID for user-specific paths.

    Returns:
        str: The full path to the LLM registry file.

    """
    return f'{get_conversation_dir(sid, user_id)}llm_registry.json'


def get_conversation_stats_filename(sid: str, user_id: str | None = None) -> str:
    """Get the conversation statistics filename.

    Args:
        sid: The session/conversation ID.
        user_id: Optional user ID for user-specific paths.

    Returns:
        str: The full path to the conversation stats file.

    """
    return f'{get_conversation_dir(sid, user_id)}conversation_stats.pkl'


def get_conversation_checkpoints_dir(sid: str, user_id: str | None = None) -> str:
    """Get the conversation checkpoints directory path.

    Args:
        sid: The session/conversation ID.
        user_id: Optional user ID for user-specific paths.

    Returns:
        str: The checkpoints directory path.

    """
    return f'{get_conversation_dir(sid, user_id)}checkpoints/'


def _maybe_migrate_legacy_project_storage(workspace: Path, dest_storage: Path) -> None:
    """Move ``<workspace>/.grinta/storage`` to *dest_storage* if present and *dest* absent."""
    legacy = workspace / '.grinta' / 'storage'
    if dest_storage.exists():
        return
    if not legacy.is_dir():
        return
    try:
        dest_storage.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy), str(dest_storage))
    except OSError:
        logger.warning(
            'Could not migrate legacy project storage from %s to %s',
            legacy,
            dest_storage,
            exc_info=True,
        )


def _maybe_migrate_legacy_downloads(workspace: Path, dest_downloads: Path) -> None:
    legacy = workspace / '.grinta' / 'downloads'
    if dest_downloads.exists():
        return
    if not legacy.is_dir():
        return
    try:
        dest_downloads.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy), str(dest_downloads))
    except OSError:
        logger.warning(
            'Could not migrate legacy downloads from %s to %s',
            legacy,
            dest_downloads,
            exc_info=True,
        )


def get_project_local_data_root(project_root: str | Path) -> str:
    """Return the canonical per-project LocalFileStore root under ``~/.grinta/workspaces/<id>/storage``."""
    from backend.core.workspace_resolution import workspace_grinta_root

    ws = Path(project_root).expanduser().resolve()
    dest = workspace_grinta_root(ws) / 'storage'
    _maybe_migrate_legacy_project_storage(ws, dest)
    return str(dest)


def get_workspace_downloads_dir(project_root: str | Path) -> str:
    """Per-workspace downloads directory (not inside the repo tree)."""
    from backend.core.workspace_resolution import workspace_grinta_root

    ws = Path(project_root).expanduser().resolve()
    dest = workspace_grinta_root(ws) / 'downloads'
    _maybe_migrate_legacy_downloads(ws, dest)
    dest.mkdir(parents=True, exist_ok=True)
    return str(dest)


def _config_str(cfg: AppConfig, field: str) -> str:
    """Return a stripped config string field; ignore non-str values (e.g. test mocks)."""
    value = getattr(cfg, field, None)
    if not isinstance(value, str):
        return ''
    return value.strip()


def _is_same_or_subpath(path: Path, parent: Path) -> bool:
    """True if *path* is *parent* or a directory contained under *parent*."""
    try:
        rp = path.resolve()
        pp = parent.resolve()
    except (OSError, ValueError):
        return False
    if rp == pp:
        return True
    try:
        rp.relative_to(pp)
        return True
    except ValueError:
        return False


def get_local_data_root(config: AppConfig | None = None) -> str:
    """Return the LocalFileStore root (``~/.grinta/workspaces/<id>/storage`` for the workspace).

    **Contract:** agent/session blobs stay under that canonical directory. Any
    ``local_data_root`` inside the workspace that is *not* under that directory
    (including the repo root, ``./sessions``, ``./storage``, etc.) is rewritten to
    the canonical root so a top-level ``sessions/`` tree never appears next to
    source. Paths outside the workspace are still honored (e.g. a dedicated data disk).

    Legacy in-repo ``<workspace>/.grinta/storage`` is still recognized for
    ``local_data_root`` normalization until migrated away.
    """
    from backend.core.config.app_config import AppConfig
    from backend.core.constants import DEFAULT_LOCAL_DATA_ROOT
    from backend.core.workspace_resolution import resolve_cli_workspace_directory

    cfg = config or AppConfig()
    raw = _config_str(cfg, 'local_data_root')
    ws = resolve_cli_workspace_directory(cfg)

    if not raw:
        if ws is not None:
            return get_project_local_data_root(ws)
        return str(Path(os.path.expanduser(DEFAULT_LOCAL_DATA_ROOT)).resolve())

    resolved = Path(os.path.expanduser(raw)).resolve()
    if ws is not None:
        wsp = ws.resolve()
        canonical = Path(get_project_local_data_root(ws)).resolve()
        legacy_anchor = (wsp / '.grinta' / 'storage').resolve()
        if resolved == wsp:
            return str(canonical)
        try:
            resolved.relative_to(wsp)
        except ValueError:
            return str(resolved)
        if not _is_same_or_subpath(resolved, canonical) and not _is_same_or_subpath(
            resolved, legacy_anchor
        ):
            return str(canonical)

    # Workspace could not be resolved (reserved cwd, invalid project_root, etc.) but
    # settings may still point local_data_root at "." / "sessions" / "storage"
    # relative to cwd — that used to become the LocalFileStore root and created a
    # top-level ``sessions/`` tree in the repo. Anchor those paths to the
    # workspace-keyed canonical storage when cwd is a normal project directory.
    try:
        cw = Path.cwd().resolve()
    except OSError:
        return str(resolved)
    from backend.core.workspace_resolution import is_reserved_user_app_data_dir

    if is_reserved_user_app_data_dir(cw):
        return str(resolved)
    try:
        resolved.relative_to(cw)
    except ValueError:
        return str(resolved)
    canonical_cw = Path(get_project_local_data_root(cw)).resolve()
    legacy_anchor_cw = (cw / '.grinta' / 'storage').resolve()
    if resolved == cw or resolved in (cw / 'sessions', cw / 'storage'):
        return str(canonical_cw)
    if not _is_same_or_subpath(resolved, canonical_cw) and not _is_same_or_subpath(
        resolved, legacy_anchor_cw
    ):
        return str(canonical_cw)
    return str(resolved)


def get_active_local_data_root() -> str:
    """Return the active LocalFileStore root from the current app config."""
    try:
        from backend.core.config import load_app_config

        return get_local_data_root(load_app_config(set_logging_levels=False))
    except Exception:
        from backend.core.constants import DEFAULT_LOCAL_DATA_ROOT

        return os.path.expanduser(DEFAULT_LOCAL_DATA_ROOT)
