"""Helper functions for computing conversation-related storage paths."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from backend.core.constants import CONVERSATION_BASE_DIR

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


def get_project_local_data_root(project_root: str | Path) -> str:
    """Return the canonical per-project LocalFileStore root."""
    return str(Path(project_root).expanduser().resolve() / '.grinta' / 'storage')


def get_local_data_root(config: AppConfig | None = None) -> str:
    """Return the configured LocalFileStore root.

    The single source of truth is:
    1. ``config.local_data_root`` when explicitly set
    2. ``<project_root>/.grinta/storage`` when a project is open
    3. app settings root when no project is active
    """
    from backend.core.app_paths import get_app_settings_root
    from backend.core.config.app_config import AppConfig

    cfg = config or AppConfig()
    raw = (cfg.local_data_root or '').strip()
    if not raw:
        project_root = (cfg.project_root or '').strip()
        if project_root:
            return get_project_local_data_root(project_root)
        return get_app_settings_root()
    return os.path.expanduser(raw)


def get_active_local_data_root() -> str:
    """Return the active LocalFileStore root from the current app config."""
    try:
        from backend.core.config import load_app_config

        return get_local_data_root(load_app_config(set_logging_levels=False))
    except Exception:
        from backend.core.constants import DEFAULT_LOCAL_DATA_ROOT

        return os.path.expanduser(DEFAULT_LOCAL_DATA_ROOT)
