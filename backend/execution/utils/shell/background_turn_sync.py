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


def background_session_lifecycle(session: Any) -> dict[str, Any]:
    """Return a conservative, machine-readable lifecycle for a terminal session.

    A background terminal is execution evidence, not task-progress evidence.
    Only a process handle with a final return code establishes completion.  For
    backends that cannot expose one (for example a detached tmux pane), report
    ``unknown`` rather than inferring success from a quiet terminal.
    """
    proc = getattr(session, '_process', None)
    if proc is None or not hasattr(proc, 'poll'):
        return {'status': 'unknown', 'exit_code': None, 'outcome_known': False}
    exit_code = proc.poll()
    if exit_code is None:
        return {'status': 'running', 'exit_code': None, 'outcome_known': False}
    exit_code = int(exit_code)
    return {
        'status': 'completed' if exit_code == 0 else 'failed',
        'exit_code': exit_code,
        'outcome_known': True,
    }


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
    """Drain non-default sessions, including final output after process exit."""
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


def background_lifecycles_for_turn(executor: Any) -> dict[str, dict[str, Any]]:
    """Return authoritative lifecycle records for active background sessions."""
    session_manager = getattr(executor, 'session_manager', None)
    if session_manager is None:
        return {}
    return {
        session_id: background_session_lifecycle(session)
        for session_id, session in list(
            getattr(session_manager, 'sessions', {}).items()
        )
        if session_id != 'default' and session is not None
    }


def _apply_background_lifecycle(task: Any, lifecycle: dict[str, Any]) -> bool:
    status = str(lifecycle.get('status', 'unknown'))
    exit_code = lifecycle.get('exit_code')
    outcome_known = bool(lifecycle.get('outcome_known'))
    if (
        task.status != status
        or task.exit_code != exit_code
        or task.outcome_known != outcome_known
    ):
        task.status = status
        task.exit_code = exit_code if isinstance(exit_code, int) else None
        task.outcome_known = outcome_known
        task.next_action = (
            'inspect the final terminal output before relying on this command'
            if outcome_known
            else task.next_action
        )
        return True
    return False


def _apply_background_task_updates(
    tasks: Any,
    drains: dict[str, str],
    lifecycles: dict[str, dict[str, Any]],
) -> bool:
    updated = False
    for task in tasks:
        chunk = drains.get(task.session_id)
        if chunk:
            task.recent_output = chunk
            updated = True
        lifecycle = lifecycles.get(task.session_id)
        if lifecycle and _apply_background_lifecycle(task, lifecycle):
            updated = True
    return updated


def _store_extra_drains(
    state: Any,
    drains: dict[str, str],
    known_ids: set[str],
) -> None:
    extra_drains = {sid: chunk for sid, chunk in drains.items() if sid not in known_ids}
    if extra_drains:
        state.set_extra(
            _BACKGROUND_TURN_DRAIN_KEY,
            extra_drains,
            source='background_turn_sync',
        )


def apply_background_drain_to_state(
    state: Any,
    drains: dict[str, str],
    lifecycles: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Merge terminal facts into canonical context without touching task state."""
    if (not drains and not lifecycles) or state is None:
        return

    from backend.context.canonical_state import (
        load_canonical_state,
        save_canonical_state,
    )

    canonical = load_canonical_state(state=state)
    known_ids = {
        task.session_id for task in canonical.background_tasks if task.session_id
    }
    updated = _apply_background_task_updates(
        canonical.background_tasks,
        drains,
        lifecycles or {},
    )

    _store_extra_drains(state, drains, known_ids)

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
    'background_lifecycles_for_turn',
    'background_session_lifecycle',
    'cap_background_output',
    'drain_background_session_delta',
    'read_turn_drain_extras',
    'sync_background_output_for_turn',
]
