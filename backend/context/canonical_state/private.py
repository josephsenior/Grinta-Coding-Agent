"""Split submodule — see package facade for public API."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.core.logger import app_logger as logger


from backend.context.canonical_state.types import (
    BackgroundTaskState,
    CanonicalTaskState,
    FailedApproach,
    FieldFreshness,
    RecentWorkItem,
    TaskPlanItem,
    VerificationState,
    _MAX_BACKGROUND_TASKS,
    _MAX_BLOCKERS,
    _MAX_FAILED_APPROACHES,
    _MAX_OUTPUT_CHARS,
    _MAX_RECENT_WORK,
    _MAX_TASK_PLAN_ITEMS,
    _MAX_VERIFICATION_OUTPUT_CHARS,
    _PIVOT_MARKERS,
    clip_with_marker,
)

if TYPE_CHECKING:
    from backend.ledger.event import Event
    from backend.orchestration.state.state import State



def _set_field(
    canonical: CanonicalTaskState,
    field_name: str,
    value: Any,
    event_id: int | None,
    source: str,
) -> None:
    if not value:
        return
    if not _can_update(canonical, field_name, event_id):
        return
    setattr(canonical, field_name, value)
    _touch_field(canonical, field_name, event_id, source)


def _touch_field(
    canonical: CanonicalTaskState,
    field_name: str,
    event_id: int | None,
    source: str,
) -> None:
    canonical.field_freshness[field_name] = FieldFreshness(
        event_id=event_id,
        updated_at=_now(),
        source=source,
    )
    if event_id is not None:
        canonical.source_event_ids[field_name] = event_id


def _can_update(
    canonical: CanonicalTaskState,
    field_name: str,
    event_id: int | None,
) -> bool:
    if event_id is None:
        return True
    existing = canonical.field_freshness.get(field_name)
    if existing is None or existing.event_id is None:
        return True
    return event_id >= existing.event_id


def _update_verification(
    canonical: CanonicalTaskState,
    result: dict[str, Any],
    event_id: int | None,
    source: str,
) -> None:
    result_event_id = result.get('event_id')
    if not isinstance(result_event_id, int):
        result_event_id = event_id
    if not _can_update(canonical, 'verification', result_event_id):
        return
    canonical.verification = VerificationState(
        command=str(result.get('command', ''))[:240],
        status=str(result.get('status', '')).lower(),
        exit_code=result.get('exit_code')
        if isinstance(result.get('exit_code'), int)
        else None,
        output=clip_with_marker(
            str(result.get('output', '')),
            _MAX_VERIFICATION_OUTPUT_CHARS,
            prefer='tail',
        ),
        event_id=result_event_id,
        updated_at=_now(),
    )
    _touch_field(canonical, 'verification', result_event_id, source)


def _merge_failed_approaches(
    canonical: CanonicalTaskState,
    snapshot: dict[str, Any],
    event_id: int | None,
    source: str,
) -> None:
    approaches = snapshot.get('attempted_approaches', [])
    if not isinstance(approaches, list):
        return
    by_fingerprint = {
        approach.fingerprint: approach
        for approach in canonical.failed_approaches
        if approach.fingerprint
    }
    changed = False
    for item in approaches:
        if not isinstance(item, dict) or 'FAILED' not in str(item.get('outcome', '')):
            continue
        fingerprint = _failed_fingerprint(item)
        if fingerprint in by_fingerprint:
            by_fingerprint.pop(fingerprint)
        by_fingerprint[fingerprint] = FailedApproach(
            kind=str(item.get('type', '?'))[:80],
            detail=str(item.get('detail', ''))[:240],
            outcome=str(item.get('outcome', ''))[:240],
            fingerprint=fingerprint,
            event_id=event_id,
            last_seen=str(snapshot.get('timestamp', _now())),
        )
        changed = True
    if changed:
        canonical.failed_approaches = list(by_fingerprint.values())[
            -_MAX_FAILED_APPROACHES:
        ]
        _touch_field(canonical, 'failed_approaches', event_id, source)


def _merge_background_tasks(
    canonical: CanonicalTaskState,
    snapshot: dict[str, Any],
    event_id: int | None,
    source: str,
) -> None:
    tasks = snapshot.get('background_tasks', [])
    if not isinstance(tasks, list):
        return
    by_key = {
        task.session_id or _normalize(task.command): task
        for task in canonical.background_tasks
        if task.session_id or task.command
    }
    changed = False
    for item in tasks:
        if not isinstance(item, dict):
            continue
        session_id = str(item.get('session_id', '')).strip()
        command = str(item.get('command', '')).strip()
        key = session_id or _normalize(command)
        if not key:
            continue
        by_key[key] = BackgroundTaskState(
            session_id=session_id,
            command=command[:240],
            status=str(item.get('status', 'still running'))[:80],
            next_action=str(item.get('next_action', 'terminal_read'))[:200],
            event_id=event_id,
            updated_at=_now(),
        )
        changed = True
    if changed:
        canonical.background_tasks = list(by_key.values())[-_MAX_BACKGROUND_TASKS:]
        _touch_field(canonical, 'background_tasks', event_id, source)


def _merge_task_plan(
    canonical: CanonicalTaskState,
    snapshot: dict[str, Any],
    event_id: int | None,
    source: str,
) -> None:
    raw_plan = snapshot.get('task_plan')
    if not isinstance(raw_plan, dict) or not raw_plan:
        return
    plan_event_id = raw_plan.get('event_id')
    if not isinstance(plan_event_id, int):
        plan_event_id = event_id
    if not _can_update(canonical, 'task_plan', plan_event_id):
        return
    tasks = _coerce_task_plan(raw_plan.get('tasks'), plan_event_id)
    if not tasks:
        return
    canonical.task_plan = tasks[-_MAX_TASK_PLAN_ITEMS:]
    _touch_field(canonical, 'task_plan', plan_event_id, source)

    active_plan = _render_active_plan(tasks)
    if active_plan:
        _set_field(canonical, 'active_plan', active_plan, plan_event_id, source)
    next_action = _clean(raw_plan.get('next_action')) or _next_action_from_task_plan(
        tasks
    )
    if next_action:
        _set_field(canonical, 'next_action', next_action, plan_event_id, source)
    checkpoint = _implementation_checkpoint_from_task_plan(tasks)
    if checkpoint:
        _set_field(
            canonical,
            'implementation_checkpoint',
            checkpoint,
            plan_event_id,
            source,
        )


def _coerce_task_plan(value: object, event_id: int | None) -> list[TaskPlanItem]:
    if not isinstance(value, list):
        return []
    tasks: list[TaskPlanItem] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        description = _clean(item.get('description'))[:240]
        if not description:
            continue
        tasks.append(
            TaskPlanItem(
                description=description,
                status=_normalize_task_status(item.get('status')),
                result=_clean(item.get('result'))[:240],
                task_id=_clean(item.get('id') or item.get('task_id'))[:80],
                event_id=event_id,
                updated_at=_now(),
            )
        )
    return tasks


def _normalize_task_status(value: object) -> str:
    try:
        from backend.core.task_status import TASK_STATUS_TODO, normalize_task_status

        return normalize_task_status(value, default=TASK_STATUS_TODO)
    except Exception:
        status = str(value or 'todo').strip().lower()
        return status or 'todo'


def _render_active_plan(tasks: list[TaskPlanItem]) -> str:
    parts: list[str] = []
    for item in tasks[:12]:
        detail = f'[{item.status}] {item.description}'
        if item.result:
            detail += f' -> {item.result}'
        parts.append(detail[:260])
    return '; '.join(parts)[:1200]


def _next_action_from_task_plan(tasks: list[TaskPlanItem]) -> str:
    for status in ('in_progress', 'todo', 'blocked'):
        item = next((task for task in tasks if task.status == status), None)
        if item is None:
            continue
        if status == 'blocked':
            return f'Unblock task: {item.description}'[:240]
        return item.description[:240]
    return ''


def _implementation_checkpoint_from_task_plan(tasks: list[TaskPlanItem]) -> str:
    done = [task.description for task in tasks if task.status == 'done']
    current = [
        task.description for task in tasks if task.status in {'in_progress', 'blocked'}
    ]
    remaining = [task.description for task in tasks if task.status == 'todo']
    pieces: list[str] = []
    if done:
        pieces.append('done: ' + ', '.join(done[-5:]))
    if current:
        pieces.append('current: ' + ', '.join(current[:3]))
    if remaining:
        pieces.append('remaining: ' + ', '.join(remaining[:8]))
    if not pieces and tasks:
        pieces.append('task tracker has no active remaining items')
    return ' | '.join(pieces)[:900]


def _resolve_background_tasks_from_events(
    canonical: CanonicalTaskState,
    events: list[Event],
) -> None:
    resolved: set[str] = set()
    for event in events:
        if type(event).__name__ != 'TerminalObservation':
            continue
        session_id = str(getattr(event, 'session_id', '')).strip()
        state = str(getattr(event, 'state', '') or '').lower()
        content = str(getattr(event, 'content', '') or '').lower()
        if session_id and (
            state in {'done', 'exited', 'finished', 'closed'}
            or 'process exited' in content
            or 'exit code' in content
        ):
            resolved.add(session_id)
    if resolved:
        canonical.background_tasks = [
            task
            for task in canonical.background_tasks
            if task.session_id not in resolved
        ]
        _touch_field(
            canonical,
            'background_tasks',
            _latest_event_id(events),
            'terminal_observation',
        )


def _merge_recent_work(
    canonical: CanonicalTaskState,
    snapshot: dict[str, Any],
    event_id: int | None,
    source: str,
) -> None:
    incoming: list[RecentWorkItem] = []
    files = snapshot.get('files_touched', {})
    if isinstance(files, dict):
        for path, info in list(files.items())[-12:]:
            if not isinstance(path, str) or not path:
                continue
            action = '?'
            outcome = ''
            if isinstance(info, dict):
                action = str(info.get('action', '?'))[:40]
                file_hash = info.get('sha256')
                if isinstance(file_hash, str) and file_hash:
                    outcome = f'sha256:{file_hash[:12]}'
            incoming.append(
                RecentWorkItem(
                    kind='file',
                    detail=f'{action}: {path}'[:300],
                    outcome=outcome,
                    event_id=event_id,
                    updated_at=_now(),
                )
            )

    commands = snapshot.get('recent_commands', [])
    if isinstance(commands, list):
        for item in commands[-10:]:
            if not isinstance(item, dict):
                continue
            command = str(item.get('command', '')).strip()
            if not command:
                continue
            incoming.append(
                RecentWorkItem(
                    kind='command',
                    detail=command[:240],
                    outcome=_summarize_work_output(item.get('output', '')),
                    event_id=event_id,
                    updated_at=_now(),
                )
            )

    latest_test = _latest_dict(snapshot.get('test_results', []))
    if latest_test:
        command = str(latest_test.get('command', '')).strip()
        status = str(latest_test.get('status', '')).upper()
        if command:
            incoming.append(
                RecentWorkItem(
                    kind='verification',
                    detail=command[:240],
                    outcome=f'{status} exit={latest_test.get("exit_code")}',
                    event_id=latest_test.get('event_id')
                    if isinstance(latest_test.get('event_id'), int)
                    else event_id,
                    updated_at=_now(),
                )
            )

    raw_plan = snapshot.get('task_plan')
    if isinstance(raw_plan, dict):
        next_action = str(raw_plan.get('next_action', '') or '').strip()
        tasks = raw_plan.get('tasks')
        task_count = len(tasks) if isinstance(tasks, list) else 0
        if next_action or task_count:
            incoming.append(
                RecentWorkItem(
                    kind='plan',
                    detail=(next_action or f'{task_count} task tracker items')[:240],
                    outcome=f'{task_count} tasks' if task_count else '',
                    event_id=raw_plan.get('event_id')
                    if isinstance(raw_plan.get('event_id'), int)
                    else event_id,
                    updated_at=_now(),
                )
            )

    if not incoming:
        return
    by_key = {
        _recent_work_key(item): item
        for item in canonical.recent_work
        if item.kind or item.detail
    }
    for item in incoming:
        key = _recent_work_key(item)
        if key in by_key:
            by_key.pop(key)
        by_key[key] = item
    canonical.recent_work = list(by_key.values())[-_MAX_RECENT_WORK:]
    _touch_field(canonical, 'recent_work', event_id, source)


def _update_blockers(
    canonical: CanonicalTaskState,
    snapshot: dict[str, Any],
    event_id: int | None,
    source: str,
) -> None:
    blockers: list[str] = []
    if canonical.background_tasks:
        blockers.append(
            'Pending background command must be polled before starting another long command.'
        )
    if canonical.verification.command and canonical.verification.status != 'passed':
        blockers.append(
            f'Latest verification is failing: {canonical.verification.command}'
        )
    blockers.extend(
        _string_tail(snapshot.get('recent_errors', []), 6, _MAX_OUTPUT_CHARS)
    )
    canonical.blockers = _merge_strings([], blockers, _MAX_BLOCKERS)
    if blockers:
        _touch_field(canonical, 'blockers', event_id, source)


def _update_vcs_status(
    canonical: CanonicalTaskState,
    snapshot: dict[str, Any],
    event_id: int | None,
    source: str,
) -> None:
    commands = snapshot.get('recent_commands', [])
    if not isinstance(commands, list):
        return
    for command_info in reversed(commands):
        if not isinstance(command_info, dict):
            continue
        command = str(command_info.get('command', ''))
        if command.strip().startswith('git status'):
            output = str(command_info.get('output', ''))[:_MAX_OUTPUT_CHARS]
            _set_field(canonical, 'vcs_status', output or command, event_id, source)
            return


def _infer_next_action(canonical: CanonicalTaskState) -> str:
    if canonical.task_plan:
        next_action = _next_action_from_task_plan(canonical.task_plan)
        if next_action:
            return next_action
    if canonical.background_tasks:
        task = canonical.background_tasks[-1]
        return task.next_action or f'Read background terminal {task.session_id}.'
    if canonical.verification.command and canonical.verification.status != 'passed':
        return f'Use the latest failing output from {canonical.verification.command} to make the next fix.'
    if canonical.superseding_directive:
        return (
            f'Switch to the superseding directive: {canonical.superseding_directive}'[
                :240
            ]
        )
    if canonical.latest_directive:
        return 'Continue from the latest user directive.'
    return ''


def _is_pivot_directive(text: str) -> bool:
    """True only for explicit task pivots, not refinements/clarifications.

    Uses a narrow allow-list of high-precision phrases so additive requests
    ("also add tests", "make it faster") never trigger objective supersession.
    """
    lowered = _normalize(text)
    if not lowered:
        return False
    return any(marker in lowered for marker in _PIVOT_MARKERS)


def _latest_event_id(events: list[Event]) -> int | None:
    ids = [getattr(event, 'id', None) for event in events]
    int_ids = [event_id for event_id in ids if isinstance(event_id, int)]
    return max(int_ids) if int_ids else None


def _snapshot_latest_event_id(snapshot: dict[str, Any]) -> int | None:
    ids: list[int] = []
    task_plan = snapshot.get('task_plan')
    if isinstance(task_plan, dict) and isinstance(task_plan.get('event_id'), int):
        ids.append(task_plan['event_id'])
    for result in (
        snapshot.get('test_results', [])
        if isinstance(snapshot.get('test_results'), list)
        else []
    ):
        if isinstance(result, dict) and isinstance(result.get('event_id'), int):
            ids.append(result['event_id'])
    return max(ids) if ids else None


def _latest_dict(value: object) -> dict[str, Any] | None:
    if not isinstance(value, list) or not value:
        return None
    for item in reversed(value):
        if isinstance(item, dict):
            return item
    return None


def _string_list(value: object, limit: int) -> list[str]:
    return _coerce_string_list(value)[-limit:]


def _string_tail(value: object, count: int, max_chars: int) -> list[str]:
    if not isinstance(value, list):
        return []
    items = [str(item).strip()[:max_chars] for item in value if str(item).strip()]
    return items[-count:]


def _coerce_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        lines = [line.strip(' -') for line in value.splitlines() if line.strip(' -')]
        return lines or [value.strip()]
    return []


def _merge_strings(existing: list[str], incoming: list[str], limit: int) -> list[str]:
    by_key: dict[str, str] = {}
    for item in [*existing, *incoming]:
        text = str(item).strip()
        if not text or _is_control_noise(text):
            continue
        key = _normalize(text)
        if key in by_key:
            by_key.pop(key)
        by_key[key] = text
    return list(by_key.values())[-limit:]


def _recent_work_key(item: RecentWorkItem) -> str:
    return f'{_normalize(item.kind)}:{_normalize(item.detail)}'


def _summarize_work_output(value: object) -> str:
    text = str(value or '').strip()
    if not text:
        return ''
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ''
    return ' | '.join(lines[-3:])[:220]


def _failed_fingerprint(item: dict[str, Any]) -> str:
    return f'{_normalize(str(item.get("type", "?")))}:{_normalize(str(item.get("detail", "")))}'


def _normalize(text: str) -> str:
    return ' '.join(text.casefold().split())


def _clean(value: object) -> str:
    return str(value).strip() if value is not None else ''


def _now() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _append(lines: list[str], line: str) -> None:
    if line and not line.endswith(': '):
        value = line.split(': ', 1)[-1] if ': ' in line else line
        if value.strip():
            lines.append(line)


def _append_list(lines: list[str], title: str, values: list[str]) -> None:
    if not values:
        return
    lines.append(f'- {title}:')
    lines.extend(f'  - {value}' for value in values if value.strip())


def _extract_next_action(text: object) -> str:
    if not isinstance(text, str):
        return ''
    for line in text.splitlines():
        if 'next action:' in line.casefold():
            return line.split(':', 1)[-1].strip()
    return ''


def _is_control_noise(text: str) -> bool:
    lowered = _normalize(text)
    return any(
        marker in lowered
        for marker in (
            'memory condensed',
            'context condensed',
            'resuming task',
            'resume the task',
            'post compact restore',
            'restored context',
        )
    )


__all__ = [
    'CANONICAL_STATE_MARKER',
    'BackgroundTaskState',
    'CanonicalTaskState',
    'CanonicalValidationResult',
    'FailedApproach',
    'FieldFreshness',
    'RecentWorkItem',
    'VerificationState',
    'apply_canonical_patch',
    'canonical_state_path',
    'load_canonical_state',
    'reduce_events_into_state',
    'reduce_snapshot_into_state',
    'render_canonical_state_for_prompt',
    'save_canonical_state',
    'validate_canonical_state_for_compaction',
]
