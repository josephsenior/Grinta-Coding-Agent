"""Durable working-set context for coding-agent continuity.

Keeps task state, test results, and condensation recovery available across
turns instead of one-shot snapshot injection.
"""

from __future__ import annotations

import time
from typing import Any

from backend.core.constants import DEFAULT_DURABLE_CONTEXT_CHAR_BUDGET
from backend.core.logger import app_logger as logger
from backend.ledger.action import MessageAction
from backend.ledger.event import Event, EventSource
from backend.ledger.observation.agent import AgentCondensationObservation

_WORKING_SET_MARKER = '<DURABLE_WORKING_SET>'
_MAX_FAILED_APPROACH_RECORDS = 8
_MAX_BACKGROUND_TASK_RECORDS = 5
_MAX_CURRENT_STATE_FILES = 12


def _sync_findings_block(
    memory: dict[str, Any], snapshot: dict[str, Any]
) -> str | None:
    from backend.context.pre_condensation_snapshot import format_snapshot_for_injection

    block = format_snapshot_for_injection(snapshot)
    if block and block.strip():
        memory['findings'] = block[:DEFAULT_DURABLE_CONTEXT_CHAR_BUDGET]
        return 'findings'
    return None


def _sync_test_results(memory: dict[str, Any], snapshot: dict[str, Any]) -> str | None:
    test_lines: list[str] = []
    for result in snapshot.get('test_results', [])[-5:]:
        if not isinstance(result, dict):
            continue
        status = str(result.get('status', '?')).upper()
        command = str(result.get('command', ''))[:120]
        exit_code = result.get('exit_code')
        output = str(result.get('output', '')).strip()
        line = f'{status} (exit={exit_code}): {command}'
        if output:
            line += f'\n  {output[:200]}'
        test_lines.append(line)
    if test_lines:
        memory['blockers'] = 'Recent verification results:\n' + '\n'.join(test_lines)
        return 'blockers'
    return None


def _sync_decisions(memory: dict[str, Any], snapshot: dict[str, Any]) -> str | None:
    decisions = snapshot.get('decisions', [])
    if isinstance(decisions, list) and decisions:
        memory['decisions'] = '\n'.join(str(d)[:300] for d in decisions[-8:])
        return 'decisions'
    return None


def _sync_failed_approaches(
    memory: dict[str, Any], snapshot: dict[str, Any]
) -> str | None:
    approaches = snapshot.get('attempted_approaches', [])
    if not (isinstance(approaches, list) and approaches):
        return None
    failed = [
        a
        for a in approaches
        if isinstance(a, dict) and 'FAILED' in str(a.get('outcome', ''))
    ]
    if not failed:
        return None
    existing = memory.get('_failed_approach_records')
    records = existing if isinstance(existing, list) else []
    by_fingerprint: dict[str, dict[str, str]] = {}
    for item in records:
        if not isinstance(item, dict):
            continue
        fingerprint = str(item.get('fingerprint', '')).strip()
        if fingerprint:
            by_fingerprint[fingerprint] = {
                'fingerprint': fingerprint,
                'type': str(item.get('type', '?'))[:80],
                'detail': str(item.get('detail', ''))[:240],
                'outcome': str(item.get('outcome', ''))[:240],
                'last_seen': str(item.get('last_seen', '')),
            }

    timestamp = str(snapshot.get('timestamp', ''))
    for approach in failed:
        fingerprint = _failed_approach_fingerprint(approach)
        if fingerprint in by_fingerprint:
            by_fingerprint.pop(fingerprint)
        by_fingerprint[fingerprint] = {
            'fingerprint': fingerprint,
            'type': str(approach.get('type', '?'))[:80],
            'detail': str(approach.get('detail', ''))[:240],
            'outcome': str(approach.get('outcome', ''))[:240],
            'last_seen': timestamp,
        }

    updated_records = list(by_fingerprint.values())[-_MAX_FAILED_APPROACH_RECORDS:]
    memory['_failed_approach_records'] = updated_records
    memory['failed_approaches'] = _render_failed_approaches(updated_records)
    return 'failed_approaches'


def _failed_approach_fingerprint(approach: dict[str, Any]) -> str:
    kind = _normalize_text(str(approach.get('type', '?')))
    detail = _normalize_text(str(approach.get('detail', '')))
    return f'{kind}:{detail}'


def _normalize_text(text: str) -> str:
    return ' '.join(text.casefold().split())


def _render_failed_approaches(records: list[dict[str, str]]) -> str:
    lines = ['Failed approaches to avoid unless inputs changed:']
    for record in records:
        detail = record.get('detail', '')[:180]
        outcome = record.get('outcome', '')[:180]
        kind = record.get('type', '?')
        lines.append(f'- [{kind}] {detail} -> {outcome}')
    return '\n'.join(lines)


def _sync_background_tasks(
    memory: dict[str, Any], snapshot: dict[str, Any]
) -> str | None:
    tasks = snapshot.get('background_tasks', [])
    if not (isinstance(tasks, list) and tasks):
        return None
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for task in reversed(tasks):
        if not isinstance(task, dict):
            continue
        session_id = str(task.get('session_id', '')).strip()
        command = str(task.get('command', '')).strip()
        fingerprint = session_id or _normalize_text(command)
        if not fingerprint or fingerprint in seen:
            continue
        seen.add(fingerprint)
        records.append(
            {
                'session_id': session_id,
                'command': command[:180],
                'status': str(task.get('status', 'still running'))[:80],
                'next_action': str(task.get('next_action', 'terminal_read'))[:160],
            }
        )
        if len(records) >= _MAX_BACKGROUND_TASK_RECORDS:
            break
    records.reverse()
    if not records:
        return None
    memory['_background_task_records'] = records
    memory['background_tasks'] = _render_background_tasks(records)
    return 'background_tasks'


def _render_background_tasks(records: list[dict[str, str]]) -> str:
    lines = ['Pending background processes:']
    for record in records:
        session_id = record.get('session_id') or 'unknown session'
        command = record.get('command') or 'unknown command'
        next_action = record.get('next_action') or 'terminal_read'
        lines.append(f'- {session_id}: {command} ({record.get("status", "pending")})')
        lines.append(f'  Next: {next_action}')
    return '\n'.join(lines)


def _sync_current_state(memory: dict[str, Any], snapshot: dict[str, Any]) -> str | None:
    state = _build_current_state(snapshot)
    if not any(value for value in state.values()):
        return None
    memory['_current_state'] = state
    memory['current_state'] = _render_current_state(state)
    return 'current_state'


def _build_current_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    latest_test = _latest_test_result(snapshot)
    background_tasks = snapshot.get('background_tasks', [])
    blockers = _current_blockers(snapshot, latest_test)
    return {
        'objective': str(snapshot.get('objective', '')).strip()[:500],
        'latest_directive': str(snapshot.get('latest_directive', '')).strip()[:500],
        'active_files': _active_files(snapshot),
        'latest_test': latest_test,
        'unresolved_blockers': blockers,
        'invalidated_assumptions': _string_tail(
            snapshot.get('invalidated_assumptions', []), 5, 220
        ),
        'next_action': _infer_next_action(snapshot, latest_test, background_tasks),
    }


def _latest_test_result(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    results = snapshot.get('test_results', [])
    if not isinstance(results, list) or not results:
        return None
    latest = results[-1]
    return latest if isinstance(latest, dict) else None


def _active_files(snapshot: dict[str, Any]) -> list[str]:
    files = snapshot.get('files_touched', {})
    if not isinstance(files, dict):
        return []
    return [
        path
        for path in list(files.keys())[-_MAX_CURRENT_STATE_FILES:]
        if isinstance(path, str)
    ]


def _current_blockers(
    snapshot: dict[str, Any], latest_test: dict[str, Any] | None
) -> list[str]:
    blockers: list[str] = []
    background_tasks = snapshot.get('background_tasks', [])
    if isinstance(background_tasks, list) and background_tasks:
        blockers.append('Background command still running; poll it before new actions.')
    if (
        latest_test is not None
        and str(latest_test.get('status', '')).lower() != 'passed'
    ):
        command = str(latest_test.get('command', '')).strip()
        blockers.append(f'Latest verification is failing: {command}')
    blockers.extend(_string_tail(snapshot.get('recent_errors', []), 4, 220))
    return blockers[:6]


def _string_tail(value: object, count: int, max_chars: int) -> list[str]:
    if not isinstance(value, list):
        return []
    items = [str(item).strip()[:max_chars] for item in value if str(item).strip()]
    return items[-count:]


def _infer_next_action(
    snapshot: dict[str, Any],
    latest_test: dict[str, Any] | None,
    background_tasks: object,
) -> str:
    if isinstance(background_tasks, list) and background_tasks:
        latest = next(
            (task for task in reversed(background_tasks) if isinstance(task, dict)),
            None,
        )
        if latest is not None:
            session_id = str(latest.get('session_id', '')).strip()
            if session_id:
                return f'Call terminal_read for background session {session_id} before starting another command.'
        return 'Read the pending background terminal before starting another command.'
    if latest_test is not None:
        command = str(latest_test.get('command', '')).strip()
        status = str(latest_test.get('status', '')).lower()
        if status != 'passed':
            return f'Use the latest failing output from {command} to make the next fix.'
        return 'Continue from the latest directive; verification was last passing.'
    latest_directive = str(snapshot.get('latest_directive', '')).strip()
    if latest_directive:
        return 'Continue from the latest user directive.'
    return ''


def _render_current_state(state: dict[str, Any]) -> str:
    lines = ['Canonical current state:']
    if state.get('objective'):
        lines.append(f'- Objective: {state["objective"]}')
    if state.get('latest_directive') and state.get('latest_directive') != state.get(
        'objective'
    ):
        lines.append(f'- Latest directive: {state["latest_directive"]}')
    active_files = state.get('active_files')
    if isinstance(active_files, list) and active_files:
        lines.append('- Active files: ' + ', '.join(str(path) for path in active_files))
    latest_test = state.get('latest_test')
    if isinstance(latest_test, dict):
        status = str(latest_test.get('status', '?')).upper()
        exit_code = latest_test.get('exit_code')
        command = str(latest_test.get('command', ''))[:160]
        lines.append(f'- Latest verification: {status} (exit={exit_code}): {command}')
    blockers = state.get('unresolved_blockers')
    if isinstance(blockers, list) and blockers:
        lines.append('- Unresolved blockers:')
        lines.extend(f'  - {item}' for item in blockers)
    invalidated = state.get('invalidated_assumptions')
    if isinstance(invalidated, list) and invalidated:
        lines.append('- Invalidated assumptions:')
        lines.extend(f'  - {item}' for item in invalidated)
    if state.get('next_action'):
        lines.append(f'- Next action: {state["next_action"]}')
    return '\n'.join(lines)


def sync_snapshot_to_working_memory(
    snapshot: dict[str, Any] | None,
    *,
    state: object | None = None,
) -> list[str]:
    """Persist condensation snapshot facts into structured working memory."""
    if not snapshot:
        return []
    try:
        from backend.context.canonical_state import (
            reduce_snapshot_into_state,
            save_canonical_state,
        )
        from backend.context.pre_condensation_snapshot import (
            format_snapshot_for_injection,  # noqa: F401
        )
        from backend.context.session_context import bind_session_context
        from backend.engine.tools.working_memory import _load_memory, _save_memory
    except Exception:
        logger.debug('Working memory sync unavailable', exc_info=True)
        return []

    bind_session_context(state=state)  # type: ignore[arg-type]
    try:
        canonical = reduce_snapshot_into_state(
            snapshot,
            source='working_set_sync',
            persist_state=state,  # type: ignore[arg-type]
        )
        save_canonical_state(canonical, state=state)  # type: ignore[arg-type]
    except Exception:
        logger.debug('Canonical state sync unavailable', exc_info=True)

    memory = _load_memory()
    updated: list[str] = []

    for sync_fn in (
        _sync_current_state,
        _sync_findings_block,
        _sync_test_results,
        _sync_background_tasks,
        _sync_decisions,
        _sync_failed_approaches,
    ):
        result = sync_fn(memory, snapshot)
        if result:
            updated.append(result)

    if updated:
        memory['_last_updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
        memory['_snapshot_synced_at'] = memory['_last_updated']
        _save_memory(memory)
    return updated


def _session_has_durable_artifacts(*, state: object | None = None) -> bool:
    """True when this session has persisted snapshot or working-memory data on disk."""
    try:
        from backend.context.pre_condensation_snapshot import load_snapshot
        from backend.engine.tools.working_memory import _load_memory

        if load_snapshot(state=state):  # type: ignore[arg-type]
            return True
        memory = _load_memory()
        return any(
            isinstance(value, str) and value.strip()
            for key, value in memory.items()
            if not str(key).startswith('_')
        )
    except Exception:
        logger.debug('Durable artifact probe failed', exc_info=True)
        return False


def get_durable_context_block(
    events: list[Event] | None = None,
    *,
    char_budget: int = DEFAULT_DURABLE_CONTEXT_CHAR_BUDGET,
    state: object | None = None,
    include_task_from_history: bool = False,
) -> str:
    """Build a compact durable context block for prompt protection."""
    parts: list[str] = [_WORKING_SET_MARKER]

    if events and include_task_from_history:
        from backend.context.tool_result_storage import extract_latest_pytest_summary

        first_user = _first_user_message(events)
        last_user = _last_user_message(events)
        if first_user:
            parts.append(f'Task: {first_user[:600]}')
        if last_user and last_user != first_user:
            parts.append(f'Latest directive: {last_user[:400]}')
        pytest_summary = extract_latest_pytest_summary(events)
        if pytest_summary:
            parts.append(f'Latest pytest: {pytest_summary}')

    try:
        from backend.context.canonical_state import (
            load_canonical_state,
            reduce_events_into_state,
            render_canonical_state_for_prompt,
        )

        canonical = load_canonical_state(state=state)  # type: ignore[arg-type]
        if events:
            canonical = reduce_events_into_state(
                events,
                canonical,
                state=state,  # type: ignore[arg-type]
                persist=state is not None,
                source='durable_context',
            )
        canonical_block = render_canonical_state_for_prompt(
            canonical,
            char_budget=max(1200, char_budget // 2),
        )
        if canonical_block:
            parts.append(canonical_block)
    except Exception:
        logger.debug('Canonical durable context assembly failed', exc_info=True)

    try:
        from backend.context.pre_condensation_snapshot import (
            format_snapshot_for_injection,
            load_snapshot,
        )
        from backend.engine.tools.working_memory import get_working_memory_prompt_block

        snapshot = load_snapshot(state=state)  # type: ignore[arg-type]
        if snapshot:
            snapshot_block = format_snapshot_for_injection(snapshot)
            if snapshot_block:
                parts.append(snapshot_block)
        wm_block = get_working_memory_prompt_block(char_budget=char_budget // 2)
        if wm_block:
            parts.append(wm_block)
    except Exception:
        logger.debug('Durable context assembly failed', exc_info=True)

    parts.append(_WORKING_SET_MARKER)
    if len(parts) <= 2:
        return ''
    block = '\n'.join(parts)
    if len(block) > char_budget:
        block = (
            block[: char_budget - 40]
            + '\n... (working set truncated)\n'
            + _WORKING_SET_MARKER
        )
    return block


def build_working_set_observation(
    events: list[Event],
    *,
    state: object | None = None,
) -> AgentCondensationObservation | None:
    """Create a durable working-set observation after compaction or restore.

    Fresh sessions with no compaction history and no persisted artifacts must
    not inject this — it is rendered through the condensation observation path
    and would falsely tell the model that context was already condensed.
    """
    from backend.context.compact_boundary import find_last_condensation_action

    has_compacted = find_last_condensation_action(events) is not None
    if not has_compacted and not _session_has_durable_artifacts(state=state):
        return None

    content = get_durable_context_block(
        events,
        state=state,
        include_task_from_history=has_compacted,
    )
    if not content:
        return None
    return AgentCondensationObservation(content=content, is_working_set=True)


def _first_user_message(events: list[Event]) -> str | None:
    for event in events:
        if isinstance(event, MessageAction) and event.source == EventSource.USER:
            text = (event.content or '').strip()
            if text:
                return text
    return None


def _last_user_message(events: list[Event]) -> str | None:
    for event in reversed(events):
        if isinstance(event, MessageAction) and event.source == EventSource.USER:
            text = (event.content or '').strip()
            if text:
                return text
    return None


__all__ = [
    'build_working_set_observation',
    'get_durable_context_block',
    'sync_snapshot_to_working_memory',
]
