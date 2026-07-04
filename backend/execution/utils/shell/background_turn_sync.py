"""Turn-boundary background output sync for agent context injection."""

from __future__ import annotations

from typing import Any

from backend.core.logging.logger import app_logger as logger

_BACKGROUND_TURN_DRAIN_KEY = 'background_turn_drain'
_DEFAULT_MAX_LINES = 20
_DEFAULT_MAX_CHARS = 2000


def cap_background_output(
    text: str,
    *,
    max_lines: int = _DEFAULT_MAX_LINES,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> str:
    """Trim background output for prompt injection."""
    if not text:
        return ''
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = ['[... earlier lines omitted ...]', *lines[-max_lines:]]
    capped = '\n'.join(lines)
    if len(capped) > max_chars:
        capped = '[... output truncated ...]\n' + capped[-max_chars:]
    return capped


def _session_is_running(session: Any) -> bool:
    proc = getattr(session, '_process', None)
    if proc is not None and hasattr(proc, 'poll'):
        return proc.poll() is None
    return True


def drain_background_session_delta(
    executor: Any,
    session_id: str,
    session: Any,
) -> str:
    """Drain new delta output for one session and advance the read cursor."""
    from backend.execution.aes.helpers import (
        advance_terminal_read_cursor,
        get_terminal_read_cursor,
        read_terminal_with_mode,
    )

    offset = get_terminal_read_cursor(executor, session_id)
    content, next_offset, has_new_output, _ = read_terminal_with_mode(
        executor,
        session=session,
        mode='delta',
        offset=offset,
    )
    if not has_new_output or not content:
        return ''
    advance_terminal_read_cursor(
        executor,
        session_id,
        next_offset,
        mode='delta',
    )
    return cap_background_output(content)


def sync_background_output_for_turn(executor: Any) -> dict[str, str]:
    """Drain live non-default sessions and return capped output by session id."""
    session_manager = getattr(executor, 'session_manager', None)
    if session_manager is None:
        return {}

    drains: dict[str, str] = {}
    for session_id in list(getattr(session_manager, 'sessions', {}).keys()):
        if session_id == 'default':
            continue
        session = session_manager.sessions.get(session_id)
        if session is None:
            continue
        if not _session_is_running(session):
            continue
        try:
            chunk = drain_background_session_delta(executor, session_id, session)
        except Exception:
            logger.debug(
                'background_turn_sync: drain failed for %s',
                session_id,
                exc_info=True,
            )
            continue
        if chunk:
            drains[session_id] = chunk
    return drains


def apply_background_drain_to_state(state: Any, drains: dict[str, str]) -> None:
    """Merge drained background output into canonical state / turn extras."""
    if not drains or state is None:
        return

    from backend.context.canonical_state import (
        load_canonical_state,
        save_canonical_state,
    )

    canonical = load_canonical_state(state=state)
    known_ids = {
        task.session_id for task in canonical.background_tasks if task.session_id
    }
    updated = False
    for task in canonical.background_tasks:
        chunk = drains.get(task.session_id)
        if chunk:
            task.recent_output = chunk
            updated = True

    extra_drains = {sid: chunk for sid, chunk in drains.items() if sid not in known_ids}
    if extra_drains:
        state.set_extra(
            _BACKGROUND_TURN_DRAIN_KEY,
            extra_drains,
            source='background_turn_sync',
        )
    if updated:
        save_canonical_state(canonical, state=state)


def read_turn_drain_extras(state: Any | None) -> dict[str, str]:
    """Return extra drained output not yet tied to canonical background tasks."""
    if state is None:
        return {}
    extra = getattr(state, 'extra_data', None)
    if not isinstance(extra, dict):
        return {}
    raw = extra.get(_BACKGROUND_TURN_DRAIN_KEY)
    if not isinstance(raw, dict):
        return {}
    return {
        str(sid): str(content)
        for sid, content in raw.items()
        if isinstance(content, str) and content.strip()
    }


__all__ = [
    'apply_background_drain_to_state',
    'cap_background_output',
    'drain_background_session_delta',
    'read_turn_drain_extras',
    'sync_background_output_for_turn',
]
