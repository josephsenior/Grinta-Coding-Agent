"""Session-scoped context path resolution (never fall back to workspace-wide files)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from backend.core.logging.logger import app_logger as logger

if TYPE_CHECKING:
    from backend.orchestration.state.state import State

_UNBOUND_DIR = '.session_context_unbound'
_last_session_symbol_index_cleared: str | None = None


def _clear_symbol_index_on_new_session(session_id: str) -> None:
    global _last_session_symbol_index_cleared
    if _last_session_symbol_index_cleared == session_id:
        return
    _last_session_symbol_index_cleared = session_id
    try:
        from backend.context.symbol_index.store import clear_symbol_index_for_workspace

        clear_symbol_index_for_workspace()
    except Exception:
        logger.debug('Symbol index session reset skipped', exc_info=True)


def resolve_session_id(
    *,
    state: State | None = None,
    session_id: str | None = None,
) -> str | None:
    """Resolve session id from explicit arg, state, contextvar, or logger.

    Order: explicit arg, then state.session_id, then contextvar, then the
    bound session event logger (process-wide fallback).
    """
    for candidate in (
        session_id,
        getattr(state, 'session_id', None) if state is not None else None,
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    try:
        from backend.engine.tools.working_memory import get_current_session_id

        ctx = get_current_session_id()
        if isinstance(ctx, str) and ctx.strip():
            return ctx.strip()
    except Exception:
        pass
    try:
        from backend.core.logging.session_event_logger import get_bound_session_id

        sid = get_bound_session_id()
        if isinstance(sid, str) and sid.strip():
            return sid.strip()
    except Exception:
        pass
    return None


def bind_session_context(
    *,
    state: State | None = None,
    session_id: str | None = None,
) -> str | None:
    """Bind contextvar on the current thread/task from state or explicit id."""
    sid = resolve_session_id(state=state, session_id=session_id)
    if not sid:
        return None
    try:
        from backend.engine.tools.working_memory import set_current_session_id

        set_current_session_id(sid)
        _clear_symbol_index_on_new_session(sid)
    except Exception:
        logger.debug('bind_session_context failed', exc_info=True)
        return None
    return sid


def agent_state_dir() -> Path:
    from backend.core.workspace_resolution import workspace_agent_state_dir

    return workspace_agent_state_dir()


def scoped_agent_path(
    stem: str,
    extension: str,
    *,
    state: State | None = None,
    session_id: str | None = None,
) -> Path:
    """Return a session-scoped path under the workspace agent dir.

    Never returns legacy workspace-wide filenames (``stem.ext``). When session id
    cannot be resolved, returns a quarantined path that will not read old data.
    """
    sid = resolve_session_id(state=state, session_id=session_id)
    base = agent_state_dir()
    if sid:
        return base / f'{stem}_{sid}{extension}'
    logger.warning(
        'Session context unbound for %s%s — using quarantined path (no legacy fallback)',
        stem,
        extension,
    )
    return base / _UNBOUND_DIR / f'{stem}{extension}'
