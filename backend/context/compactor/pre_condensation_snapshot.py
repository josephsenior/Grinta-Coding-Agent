"""Pre-condensation snapshot — auto-extracts critical context before condensation.

When condensation fires, the LLM loses all tool outputs and file contents.
This module extracts the most important context from the about-to-be-pruned
events and persists it under ``~/.grinta/workspaces/<id>/agent/pre_condensation_snapshot.json``.

The snapshot is then injected into the post-condensation recovery sequence,
giving the LLM a structured summary of what was lost — without requiring
the LLM to have manually noted everything.

Extracted context:
- Files read/edited with their last-known action
- Recent error messages and their surrounding context
- Key decisions expressed in think() calls
- Recent command outputs (truncated)
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.context.canonical_state import clip_with_marker
from backend.core.logging.logger import app_logger as logger

if TYPE_CHECKING:
    from backend.ledger.event import Event
    from backend.orchestration.state.state import State

# Limits to prevent the snapshot from becoming too large
_MAX_ERRORS = 10
_MAX_DECISIONS = 15
_MAX_COMMANDS = 10
_MAX_TEST_RESULTS = 8
_MAX_INVALIDATED_ASSUMPTIONS = 12
_MAX_CONTENT_LENGTH = 500
_MAX_TASKS = 20
# Cap file paths listed in compact snapshot and continuity checks (aligned).
MAX_FILES_IN_COMPACT_SNAPSHOT = 30


def active_file_paths_from_files_touched(
    files: object,
    *,
    max_files: int = MAX_FILES_IN_COMPACT_SNAPSHOT,
) -> list[str]:
    """Return capped path list derived from ``files_touched`` snapshot dict."""
    if not isinstance(files, dict) or max_files <= 0:
        return []
    return [
        path
        for path, _info in list(files.items())[:max_files]
        if isinstance(path, str) and path
    ]


def _agent_debug_log(
    hypothesis_id: str, location: str, message: str, data: dict
) -> None:
    logger.debug(
        message,
        extra={
            'msg_type': 'PRE_CONDENSATION_TRACE',
            'hypothesis_id': hypothesis_id,
            'location': location,
            'trace_data': data,
        },
    )


def _snapshot_path(*, state: State | None = None) -> Path:
    from backend.context.memory.session_context import scoped_agent_path

    return scoped_agent_path('pre_condensation_snapshot', '.json', state=state)


def _snapshot_staging_path(*, state: State | None = None) -> Path:
    from backend.context.memory.session_context import scoped_agent_path

    canonical = scoped_agent_path('pre_condensation_snapshot', '.json', state=state)
    return canonical.parent / f'.{canonical.name}.staging'


def save_snapshot(snapshot: dict[str, Any], *, state: State | None = None) -> None:
    """Persist the snapshot to a staging location.

    The staging file is promoted to the canonical path via
    ``commit_snapshot()`` only after compaction confirms it fired.
    This prevents a stale snapshot from leaking when compaction
    crashes or decides not to compact.

    See ``commit_snapshot`` and ``delete_snapshot``.
    """
    p = _snapshot_staging_path(state=state)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding='utf-8')
    logger.debug(
        'Pre-condensation snapshot staged: %d files, %d errors, %d decisions, '
        '%d user messages',
        len(snapshot.get('files_touched', {})),
        len(snapshot.get('recent_errors', [])),
        len(snapshot.get('decisions', [])),
        len(snapshot.get('user_messages', [])),
    )


_MAX_ATTEMPTED_APPROACHES = 20


def _file_edit_observation_indicates_failure(content: str) -> bool:
    """True only for known failure shapes; avoids treating diff/code containing 'error' as failure."""
    s = content.strip()
    low = s.lower()
    if low.startswith('skipped:'):
        return True
    if '[edit error:' in low:
        return True
    if s.startswith('ERROR:'):
        return True
    if 'critical verification failure' in low:
        return True
    return False


def commit_snapshot(*, state: State | None = None) -> None:
    """Promote the staging snapshot to the canonical path atomically.

    Only call after compaction successfully fires.  If this is never
    called the staging file is cleaned up on next startup or by the
    next ``save_snapshot`` call.
    """
    import os as _os

    staging = _snapshot_staging_path(state=state)
    if not staging.exists():
        return
    final = _snapshot_path(state=state)
    try:
        _os.replace(staging, final)
        logger.debug('Pre-condensation snapshot committed to %s', final)
    except OSError:
        logger.debug(
            'Pre-condensation snapshot commit failed (non-fatal)', exc_info=True
        )


def extract_snapshot(events: list[Event]) -> dict[str, Any]:
    """Extract critical context from events that are about to be condensed."""
    snapshot: dict[str, Any] = {
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'events_condensed': len(events),
        'user_messages': [],
        'files_touched': {},
        'recent_errors': [],
        'decisions': [],
        'invalidated_assumptions': [],
        'recent_commands': [],
        'test_results': [],
        'attempted_approaches': [],
        'background_tasks': [],
        'task_plan': {},
        'acceptance_criteria': {},
    }

    for event in events:
        _extract_user_directive(event, snapshot)
        _extract_task_plan(event, snapshot)
        _extract_acceptance_criteria(event, snapshot)
        _extract_file_info(event, snapshot)
        _extract_errors(event, snapshot)
        _extract_decisions(event, snapshot)
        _extract_invalidated_assumptions(event, snapshot)
        _extract_commands(event, snapshot)
        _extract_background_tasks(event, snapshot)

    _extract_attempted_approaches(events, snapshot)
    _extract_test_results(events, snapshot)
    return snapshot


def snapshot_user_objective(snapshot: dict[str, Any]) -> tuple[str, str]:
    """Extract (objective, latest_directive) from substantive user messages."""
    messages = snapshot.get('user_messages')
    if isinstance(messages, list) and messages:
        texts = [
            str(m.get('text', '')).strip()
            for m in messages
            if isinstance(m, dict)
            and _is_substantive_user_directive(str(m.get('text', '')))
        ]
        if texts:
            return texts[0], texts[-1]
    return (
        str(snapshot.get('objective', '')).strip(),
        str(snapshot.get('latest_directive', '')).strip(),
    )


def _is_substantive_user_directive(text: str) -> bool:
    stripped = str(text or '').strip()
    if not stripped:
        return False
    if stripped.startswith('/'):
        return False
    lowered = stripped.casefold()
    if any(
        marker in lowered
        for marker in (
            'memory condensed',
            'context condensed',
            'post compact restore',
            'restored context',
        )
    ):
        return False
    return True


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8', 'ignore')).hexdigest()


def _update_file_record(
    files: dict,
    path: str,
    *,
    action: str,
    record_type: str,
    content: str | None = None,
    content_hash: str | None = None,
    hash_source: str | None = None,
) -> None:
    if not path:
        return
    record = dict(files.get(path, {}))
    record.update({'action': action, 'type': record_type})
    if content_hash:
        record['sha256'] = content_hash
        if hash_source:
            record['hash_source'] = hash_source
    elif content is not None:
        record['sha256'] = _sha256_text(content)
        record['size'] = len(content)
        if hash_source:
            record['hash_source'] = hash_source
    files[path] = record


def _extract_edit_file_info(event: Event, files: dict) -> None:
    """Extract file path from FileEdit* events."""
    path = getattr(event, 'path', '')
    if path:
        command = getattr(event, 'command', 'edit')
        content_hash = getattr(event, 'new_content_hash', None)
        new_content = getattr(event, 'new_content', None)
        payload_content = (
            getattr(event, 'file_text', None)
            or getattr(event, 'new_str', None)
            or getattr(event, 'content', None)
        )
        if isinstance(content_hash, str) and content_hash:
            _update_file_record(
                files,
                path,
                action=command,
                record_type='edit',
                content_hash=content_hash,
                hash_source='edit_observation',
            )
        elif isinstance(new_content, str):
            _update_file_record(
                files,
                path,
                action=command,
                record_type='edit',
                content=new_content,
                hash_source='new_content',
            )
        elif isinstance(payload_content, str) and payload_content:
            _update_file_record(
                files,
                path,
                action=command,
                record_type='edit',
                content=payload_content,
                hash_source='edit_payload',
            )
        else:
            _update_file_record(files, path, action=command, record_type='edit')


def _extract_read_file_info(event: Event, files: dict) -> None:
    """Extract file path from FileRead* events."""
    path = getattr(event, 'path', '')
    if path and path not in files:
        content = getattr(event, 'content', None)
        if isinstance(content, str):
            _update_file_record(
                files,
                path,
                action='read',
                record_type='read',
                content=content,
                hash_source='read_observation',
            )
        else:
            _update_file_record(files, path, action='read', record_type='read')


def _extract_cmd_run_file_paths(event: Event, files: dict) -> None:
    """Extract file paths from simple cat/head/tail command reads."""
    cmd = getattr(event, 'command', '')
    if 'cat ' not in cmd and 'head ' not in cmd and 'tail ' not in cmd:
        return
    parts = cmd.split()
    for i, part in enumerate(parts):
        if part in ('cat', 'head', 'tail') and i + 1 < len(parts):
            path = parts[i + 1].strip('\'"')
            if path and path not in files:
                files[path] = {'action': 'read_via_cmd', 'type': 'read'}


def _extract_file_info(event: Event, snapshot: dict) -> None:
    """Extract file paths and actions from file-related events."""
    cls_name = type(event).__name__
    files = snapshot['files_touched']

    if cls_name in ('FileEditAction', 'FileEditObservation'):
        _extract_edit_file_info(event, files)
    elif cls_name in ('FileReadAction', 'FileReadObservation'):
        _extract_read_file_info(event, files)
    elif cls_name == 'CmdRunAction':
        _extract_cmd_run_file_paths(event, files)


def _extract_user_directive(event: Event, snapshot: dict) -> None:
    """Capture every user message verbatim for goal synthesis.

    All user messages are preserved in full — no truncation, no limit.
    The compactor uses these as ground truth to synthesize the evolving
    user goal across compactions.
    """
    if type(event).__name__ != 'MessageAction':
        return
    source = getattr(event, 'source', None)
    source_value = getattr(source, 'value', source)
    if str(source_value).lower() != 'user':
        return
    content = str(getattr(event, 'content', '')).strip()
    if not content:
        return
    _append_user_message(event, content, snapshot)


def _append_user_message(event: Event, content: str, snapshot: dict) -> None:
    messages = snapshot.setdefault('user_messages', [])
    if not isinstance(messages, list):
        messages = []
        snapshot['user_messages'] = messages
    event_id = getattr(event, 'id', None)
    item: dict[str, Any] = {'text': content}
    if isinstance(event_id, int) and event_id >= 0:
        item['event_id'] = event_id
    elif isinstance(event_id, str) and event_id:
        item['event_id'] = event_id
    messages.append(item)


def _extract_task_plan(event: Event, snapshot: dict) -> None:
    """Capture the latest structured task tracker state.

    Task tracker entries are already machine-readable, so they are a better
    compaction source of truth than prose thoughts about what to do next.
    """
    cls_name = type(event).__name__
    if cls_name == 'TaskStateObservation':
        state = getattr(event, 'state', {})
        plan = state.get('plan', {}) if isinstance(state, dict) else {}
        raw_tasks = plan.get('tasks', []) if isinstance(plan, dict) else []
        setattr(event, 'task_list', raw_tasks)
    elif cls_name not in ('TaskTrackingAction', 'TaskTrackingObservation'):
        return
    task_list = getattr(event, 'task_list', None)
    if not isinstance(task_list, list) or not task_list:
        return

    tasks: list[dict[str, Any]] = []
    for raw in task_list[:_MAX_TASKS]:
        if not isinstance(raw, dict):
            continue
        description = _task_description(raw)
        if not description:
            continue
        status = _normalize_task_status(raw.get('status'))
        tasks.append(
            {
                'id': str(raw.get('id', '') or '').strip()[:80],
                'description': description[:240],
                'status': status,
                'result': str(raw.get('result', '') or '').strip()[:240],
            }
        )

    if not tasks:
        return
    event_id = getattr(event, 'id', None)
    snapshot['task_plan'] = {
        'event_id': event_id if isinstance(event_id, int) else None,
        'command': str(getattr(event, 'command', '') or '').strip()[:80],
        'tasks': tasks,
        'next_action': _next_action_from_tasks(tasks),
    }


def _extract_acceptance_criteria(event: Event, snapshot: dict) -> None:
    """Capture the latest structured acceptance criteria state."""
    cls_name = type(event).__name__
    if cls_name == 'TaskStateObservation':
        state = getattr(event, 'state', {})
        contract = state.get('contract', {}) if isinstance(state, dict) else {}
        groups = ('requirements', 'constraints', 'success_conditions')
        setattr(
            event,
            'criteria_list',
            [
                {
                    'id': item.get('id', ''),
                    'assertion': item.get('text', ''),
                    'source': item.get('source', 'agent'),
                    'evidence': '; '.join(
                        str(e.get('summary', ''))
                        for e in item.get('evidence', [])
                        if isinstance(e, dict)
                    ),
                }
                for group in groups
                for item in (
                    contract.get(group, []) if isinstance(contract, dict) else []
                )
                if isinstance(item, dict)
            ],
        )
    elif cls_name not in ('AcceptanceCriteriaAction', 'AcceptanceCriteriaObservation'):
        return
    criteria_list = getattr(event, 'criteria_list', None)
    if not isinstance(criteria_list, list) or not criteria_list:
        return

    criteria: list[dict[str, Any]] = []
    for raw in criteria_list[:20]:
        if not isinstance(raw, dict):
            continue
        assertion = str(raw.get('assertion', '') or '').strip()
        if not assertion:
            continue
        criteria.append(
            {
                'id': str(raw.get('id', '') or '').strip()[:80],
                'assertion': assertion[:240],
                'evidence': str(raw.get('evidence', '') or '').strip()[:240],
                'source': str(raw.get('source', '') or '').strip()[:40] or 'stated',
            }
        )
    if not criteria:
        return
    event_id = getattr(event, 'id', None)
    snapshot['acceptance_criteria'] = {
        'event_id': event_id if isinstance(event_id, int) else None,
        'command': str(getattr(event, 'command', '') or '').strip()[:80],
        'criteria': criteria,
    }


def _task_description(task: dict[str, Any]) -> str:
    for key in ('description', 'title', 'task', 'content', 'name'):
        value = task.get(key)
        if isinstance(value, str) and value.strip():
            return ' '.join(value.strip().split())
    return ''


def _normalize_task_status(value: object) -> str:
    try:
        from backend.core.tasks.task_status import (
            TASK_STATUS_TODO,
            normalize_task_status,
        )

        return normalize_task_status(value, default=TASK_STATUS_TODO)
    except Exception:
        status = str(value or 'todo').strip().lower()
        return status or 'todo'


def _next_action_from_tasks(tasks: list[dict[str, Any]]) -> str:
    current = next(
        (task for task in tasks if task.get('status') == 'in_progress'),
        None,
    )
    if current is None:
        current = next((task for task in tasks if task.get('status') == 'todo'), None)
    if current is None:
        current = next(
            (task for task in tasks if task.get('status') == 'blocked'),
            None,
        )
    if not current:
        return ''
    description = str(current.get('description', '')).strip()
    if current.get('status') == 'blocked':
        return f'Unblock task: {description}'[:240]
    return description[:240]


def _extract_errors(event: Event, snapshot: dict) -> None:
    """Extract recent error messages from error-producing observations."""
    if len(snapshot['recent_errors']) >= _MAX_ERRORS:
        return

    cls_name = type(event).__name__
    if cls_name == 'ErrorObservation':
        if getattr(event, 'notify_ui_only', False):
            return
        content = str(getattr(event, 'content', ''))[:_MAX_CONTENT_LENGTH]
        if _is_recoverable_tool_error_text(content):
            return
        if content:
            snapshot['recent_errors'].append(content)
    elif cls_name == 'CmdOutputObservation':
        exit_code = getattr(event, 'exit_code', 0)
        if exit_code != 0:
            content = str(getattr(event, 'content', ''))
            lines = content.strip().split('\n')
            error_tail = clip_with_marker(
                '\n'.join(lines[-5:]), _MAX_CONTENT_LENGTH, prefer='tail'
            )
            if _is_recoverable_tool_error_text(error_tail):
                return
            if error_tail:
                snapshot['recent_errors'].append(
                    f'[exit_code={exit_code}] {error_tail}'
                )


def _extract_decisions(event: Event, snapshot: dict) -> None:
    """Extract decisions and key reasoning from think actions."""
    if len(snapshot['decisions']) >= _MAX_DECISIONS:
        return

    cls_name = type(event).__name__
    if cls_name in ('AgentThinkAction', 'SystemHintAction', 'AgentThinkObservation'):
        thought = str(getattr(event, 'thought', ''))
        # Skip recovery/reflection boilerplate — only capture real decisions
        skip_prefixes = (
            '⚡ CONTEXT CONDENSED',
            '🔍 SELF-REFLECTION',
            '[SCRATCHPAD]',
            '[SEMANTIC_RECALL',
        )
        should_skip = bool(thought) and any(
            thought.startswith(p) for p in skip_prefixes
        )
        # #region agent log
        if 'SELF-REFLECTION' in thought:
            _agent_debug_log(
                'H2_mojibake_prefix_mismatch',
                'backend/context/pre_condensation_snapshot.py:_extract_decisions',
                'decision-prefix-check',
                {
                    'raw_prefix': thought[:24],
                    'raw_prefix_codepoints': [ord(ch) for ch in thought[:6]],
                    'should_skip': should_skip,
                },
            )
        # #endregion
        if (
            thought
            and not should_skip
            and not _is_invalidated_assumption_text(thought)
            and not _is_control_noise_text(thought)
            and not _is_recoverable_tool_error_text(thought)
            and is_durable_decision_text(
                thought, source_tool=str(getattr(event, 'source_tool', '') or '')
            )
        ):
            snapshot['decisions'].append(thought[:_MAX_CONTENT_LENGTH])


def is_durable_decision_text(text: str, *, source_tool: str = '') -> bool:
    """Return true for explicit durable decisions/checkpoints, not inner monologue."""
    normalized = ' '.join(str(text).strip().split())
    if not normalized:
        return False
    if source_tool == 'checkpoint':
        return True
    lower = normalized.casefold()
    if len(normalized) > 700 and not any(
        marker in lower
        for marker in (
            'decision:',
            'decided',
            'next action:',
            'checkpoint:',
            'implemented',
            'created',
            'changed',
            'verified',
            'remaining:',
        )
    ):
        return False
    if lower.startswith(('let me ', 'i need to ', 'i should ', 'actually ')):
        return False
    if any(
        marker in lower
        for marker in (
            'decision:',
            'decided',
            'next action:',
            'checkpoint:',
            'current state:',
            'implemented',
            'created',
            'changed',
            'verified',
            'remaining:',
        )
    ):
        return True
    return lower.startswith(
        (
            'fix ',
            'use ',
            'keep ',
            'switch ',
            'implement ',
            'change ',
            'remove ',
            'add ',
            'preserve ',
            'avoid ',
            'update ',
            'choose ',
            'continue ',
            'create ',
            'write ',
            'run ',
            'verify ',
        )
    )


def _is_control_noise_text(text: str) -> bool:
    lower = ' '.join(text.casefold().split())
    control_markers = (
        'memory condensed',
        'context condensed',
        'resuming task',
        'resume the task',
        'post compact restore',
        'restored context',
    )
    return any(marker in lower for marker in control_markers)


def _is_recoverable_tool_error_text(text: str) -> bool:
    lower = ' '.join(str(text).casefold().split())
    if not lower:
        return False
    markers = (
        'missing required argument',
        'recover by emitting one corrected tool call',
        'strict json arguments',
        'line range requires both start_line and end_line',
        'tool call read',
    )
    return any(marker in lower for marker in markers)


_INVALIDATION_MARKERS = (
    'invalidated',
    'was wrong',
    'were wrong',
    'not true',
    'false assumption',
    'does not hold',
    'did not hold',
    'contradicted',
    'turns out',
)
_ASSUMPTION_MARKERS = (
    'assumption',
    'assumed',
    'hypothesis',
    'thought',
    'believed',
    'expected',
    'previously',
    'initially',
)


def _event_reasoning_text(event: Event) -> str:
    for attr in ('thought', 'content', 'message'):
        value = getattr(event, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ''


def _is_invalidated_assumption_text(text: str) -> bool:
    lower = text.lower()
    has_invalidation = any(marker in lower for marker in _INVALIDATION_MARKERS)
    has_assumption = any(marker in lower for marker in _ASSUMPTION_MARKERS)
    return has_invalidation and (has_assumption or 'turns out' in lower)


def _extract_invalidated_assumptions(event: Event, snapshot: dict) -> None:
    """Extract assumptions or hypotheses that were explicitly corrected."""
    invalidated = snapshot.get('invalidated_assumptions')
    if (
        not isinstance(invalidated, list)
        or len(invalidated) >= _MAX_INVALIDATED_ASSUMPTIONS
    ):
        return
    cls_name = type(event).__name__
    if cls_name not in (
        'AgentThinkAction',
        'SystemHintAction',
        'AgentThinkObservation',
        'MessageAction',
        'ErrorObservation',
    ):
        return
    text = _event_reasoning_text(event)
    if not text:
        return
    if _is_recoverable_tool_error_text(text):
        return
    if _is_invalidated_assumption_text(text):
        clipped = text[:_MAX_CONTENT_LENGTH]
        if clipped not in invalidated:
            invalidated.append(clipped)


def _extract_commands(event: Event, snapshot: dict) -> None:
    """Extract recent command+result pairs."""
    if len(snapshot['recent_commands']) >= _MAX_COMMANDS:
        return

    cls_name = type(event).__name__
    if cls_name == 'CmdRunAction':
        cmd = str(getattr(event, 'command', ''))[:_MAX_CONTENT_LENGTH]
        if cmd:
            snapshot['recent_commands'].append({'command': cmd})
    elif cls_name == 'CmdOutputObservation':
        # Attach output to the most recent command if available
        commands = snapshot['recent_commands']
        if commands and 'output' not in commands[-1]:
            content = str(getattr(event, 'content', ''))
            lines = content.strip().split('\n')
            # Keep first and last few lines
            if len(lines) > 10:
                truncated = lines[:3] + ['... (truncated) ...'] + lines[-3:]
            else:
                truncated = lines
            commands[-1]['output'] = '\n'.join(truncated)[:_MAX_CONTENT_LENGTH]


def _extract_background_tasks(event: Event, snapshot: dict) -> None:
    """Extract detached background commands that must be polled after compaction."""
    tasks = snapshot.get('background_tasks')
    if not isinstance(tasks, list) or len(tasks) >= 5:
        return
    if type(event).__name__ != 'CmdOutputObservation':
        return
    content = str(getattr(event, 'content', ''))
    metadata = getattr(event, 'metadata', None)
    exit_code = getattr(metadata, 'exit_code', getattr(event, 'exit_code', None))
    if exit_code != -2 and '[BACKGROUND_DETACH]' not in content:
        return
    still_running = getattr(metadata, 'command_still_running', True)
    if still_running is False:
        return
    suffix = str(getattr(metadata, 'suffix', '') or '')
    session_id = _extract_background_session_id(
        suffix
    ) or _extract_background_session_id(content)
    command = str(getattr(event, 'command', '')).strip()
    next_action = (
        f'terminal_read(session_id="{session_id}")'
        if session_id
        else 'terminal_read for the detached background session'
    )
    tasks.append(
        {
            'session_id': session_id,
            'command': command[:_MAX_CONTENT_LENGTH],
            'status': 'still running',
            'next_action': next_action,
        }
    )


def _extract_background_session_id(text: str) -> str:
    if 'session_id="' not in text:
        return ''
    try:
        return text.split('session_id="', 1)[1].split('"', 1)[0]
    except (IndexError, ValueError):
        return ''


def _summarize_command_output(content: str) -> str:
    lines = content.strip().split('\n')
    if len(lines) > 8:
        lines = lines[:2] + ['... (truncated) ...'] + lines[-3:]
    return clip_with_marker('\n'.join(lines), _MAX_CONTENT_LENGTH, prefer='tail')


def _extract_test_results(events: list[Event], snapshot: dict) -> None:
    """Extract command/output pairs for test runs."""
    from backend.validation.command_classification import is_test_run_command

    results = snapshot['test_results']
    pending: dict[str, Any] | None = None
    for event in events:
        if len(results) >= _MAX_TEST_RESULTS:
            return
        cls_name = type(event).__name__
        if cls_name == 'CmdRunAction':
            command = str(getattr(event, 'command', ''))
            pending = (
                {
                    'command': command[:_MAX_CONTENT_LENGTH],
                    'event_id': getattr(event, 'id', None),
                }
                if is_test_run_command(command)
                else None
            )
            continue
        if cls_name != 'CmdOutputObservation' or pending is None:
            continue
        exit_code = getattr(event, 'exit_code', None)
        status = 'passed' if exit_code == 0 else 'failed'
        result = {
            'command': pending['command'],
            'status': status,
            'exit_code': exit_code,
            'output': _summarize_command_output(str(getattr(event, 'content', ''))),
        }
        results.append(result)
        pending = None


def _extract_attempted_approaches(events: list[Event], snapshot: dict) -> None:
    """Extract action→outcome pairs to build a structured 'attempted approaches' record.

    This captures WHAT was tried and WHETHER it worked, so the LLM can avoid
    retrying failed strategies after condensation.
    """
    approaches = snapshot['attempted_approaches']
    if len(approaches) >= _MAX_ATTEMPTED_APPROACHES:
        return

    pending_action: dict[str, Any] | None = None
    for event in events:
        pending_action = _process_event_for_approaches(
            event, approaches, pending_action
        )


def _process_event_for_approaches(
    event: Event,
    approaches: list,
    pending: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Process one event for attempted-approaches extraction.

    Dispatches on event type: FileEditAction/CmdRunAction start a pending action;
    ErrorObservation/CmdOutputObservation/FileEditObservation resolve it and append
    to approaches. Returns the new pending action (or None if resolved).
    """
    cls_name = type(event).__name__
    if cls_name == 'FileEditAction':
        return _make_file_edit_action(event)
    if cls_name == 'CmdRunAction':
        return _make_cmd_run_action(event)
    if cls_name == 'ErrorObservation' and pending:
        content = str(getattr(event, 'content', ''))
        if not _is_recoverable_tool_error_text(content):
            _append_with_outcome(approaches, pending, f'FAILED: {content[:150]}')
        return None
    if cls_name == 'CmdOutputObservation' and pending:
        _handle_cmd_output(approaches, pending, event)
        return None
    if cls_name == 'FileEditObservation' and pending:
        _handle_file_edit_observation(approaches, pending, event)
        return None
    return pending


def _make_file_edit_action(event: Event) -> dict[str, Any]:
    """Build a file_edit pending action dict from a FileEditAction event."""
    path = getattr(event, 'path', '')
    command = getattr(event, 'command', 'edit')
    start = getattr(event, 'start_line', None)
    end = getattr(event, 'end_line', None)
    detail = f'{command} on {path}'
    if start is not None and end is not None:
        detail += f' [L{start}:L{end}]'
    return {'type': 'file_edit', 'detail': detail}


def _make_cmd_run_action(event: Event) -> dict[str, Any]:
    """Build a command pending action dict from a CmdRunAction event."""
    cmd = str(getattr(event, 'command', ''))[:150]
    return {'type': 'command', 'detail': cmd}


def _append_with_outcome(approaches: list, action: dict, outcome: str) -> None:
    """Append action with outcome to approaches if under the max limit."""
    if _is_recoverable_tool_error_text(outcome):
        return
    if len(approaches) < _MAX_ATTEMPTED_APPROACHES:
        action['outcome'] = outcome
        approaches.append(action)


def _handle_cmd_output(
    approaches: list, pending: dict[str, Any], event: Event
) -> dict[str, Any] | None:
    """Resolve pending action with CmdOutputObservation result (SUCCESS or FAILED)."""
    exit_code = getattr(event, 'exit_code', 0)
    if exit_code != 0:
        content = str(getattr(event, 'content', ''))
        if _is_recoverable_tool_error_text(content):
            return None
        lines = content.strip().split('\n')
        tail = lines[-1][:150] if lines else ''
        outcome = f'FAILED (exit={exit_code}): {tail}'
    else:
        outcome = 'SUCCESS'
    _append_with_outcome(approaches, pending, outcome)
    return None


def _handle_file_edit_observation(
    approaches: list, pending: dict[str, Any], event: Event
) -> dict[str, Any] | None:
    """Resolve pending action with FileEditObservation result (SUCCESS or FAILED)."""
    content = str(getattr(event, 'content', ''))
    failed = _file_edit_observation_indicates_failure(content)
    outcome = f'FAILED: {content[:150]}' if failed else 'SUCCESS'
    _append_with_outcome(approaches, pending, outcome)
    return None


def load_snapshot(*, state: State | None = None) -> dict[str, Any] | None:
    """Load the most recent committed snapshot from disk.

    Falls back to the staging path (written during a prior run that
    crashed before commit).  Snapshots are durable across turns and are
    also synced into working memory after compaction.
    """
    for getter in (
        lambda: _snapshot_path(state=state),
        lambda: _snapshot_staging_path(state=state),
    ):
        p = getter()
        if not p.exists():
            continue
        try:
            return json.loads(p.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            pass
    return None


def delete_snapshot(*, state: State | None = None) -> None:
    """Delete the on-disk snapshot and staging file if they exist.

    Called **after** the canonical snapshot has been consumed via
    ``load_snapshot()``, so it cannot be injected a second time.
    Deletes both the canonical and staging paths.
    """
    for getter in (
        lambda: _snapshot_path(state=state),
        lambda: _snapshot_staging_path(state=state),
    ):
        try:
            p = getter()
            if p.exists():
                p.unlink()
        except OSError:
            pass


def delete_staging_snapshot(*, state: State | None = None) -> None:
    """Delete only the staging snapshot file.

    Called when compaction did NOT fire (the ``View`` branch of
    ``condense_history``), so the eagerly-written staging file is cleaned up
    without touching the canonical snapshot.  The canonical file must remain
    intact so that the ``AgentCondensationObservation`` from the *previous*
    compaction turn can still inject its snapshot block on the current turn.
    """
    try:
        p = _snapshot_staging_path(state=state)
        if p.exists():
            p.unlink()
    except OSError:
        pass


def format_snapshot_body_lines(
    snapshot: dict[str, Any],
    *,
    state: object | None = None,
    include_synthesized_goal: bool = False,
) -> list[str]:
    """Return inner compact-snapshot lines (no XML wrapper)."""
    if not isinstance(snapshot, dict) or not snapshot:
        return []
    lines = [f'Events condensed: {snapshot.get("events_condensed", "?")}']
    if include_synthesized_goal:
        lines.extend(_format_directive_section(snapshot, state=state))
    lines.extend(_format_runtime_section(snapshot.get('runtime', {})))
    lines.extend(_format_files_section(snapshot.get('files_touched', {})))
    lines.extend(_format_errors_section(snapshot.get('recent_errors', [])))
    lines.extend(_format_decisions_section(snapshot.get('decisions', [])))
    lines.extend(
        _format_invalidated_assumptions_section(
            snapshot.get('invalidated_assumptions', [])
        )
    )
    lines.extend(_format_commands_section(snapshot.get('recent_commands', [])))
    lines.extend(_format_test_results_section(snapshot.get('test_results', [])))
    lines.extend(_format_background_tasks_section(snapshot.get('background_tasks', [])))
    lines.extend(_format_approaches_section(snapshot.get('attempted_approaches', [])))
    return lines


def format_snapshot_for_injection(
    snapshot: dict[str, Any],
    *,
    state: object | None = None,
    include_synthesized_goal: bool = False,
) -> str:
    """Format a snapshot into a ``<COMPACT_SNAPSHOT>`` block for prompt injection."""
    lines = format_snapshot_body_lines(
        snapshot,
        state=state,
        include_synthesized_goal=include_synthesized_goal,
    )
    if not lines:
        return ''
    return '<COMPACT_SNAPSHOT>\n' + '\n'.join(lines) + '\n</COMPACT_SNAPSHOT>'


def _format_directive_section(
    snapshot: dict[str, Any],
    *,
    state: object | None = None,
) -> list[str]:
    """Synthesized goal context — never verbatim user transcripts."""
    try:
        from backend.context.context_pipeline.goal_context import (
            build_goal_context_for_compaction,
        )

        goal = build_goal_context_for_compaction(state=state, snapshot=snapshot)
    except Exception:
        goal = ''
    if not goal.strip():
        return []
    return ['\nSynthesized goal context:', goal]


def _format_runtime_section(runtime: dict) -> list[str]:
    """Format live runtime position captured immediately before condensation."""
    if not isinstance(runtime, dict) or not runtime:
        return []
    lines = ['\nRuntime position before condensation:']
    iteration = runtime.get('iteration')
    max_iterations = runtime.get('max_iterations')
    if isinstance(iteration, int):
        if isinstance(max_iterations, int):
            lines.append(f'  iteration: {iteration}/{max_iterations}')
        else:
            lines.append(f'  iteration: {iteration}')
    memory_pressure = runtime.get('memory_pressure')
    if isinstance(memory_pressure, str) and memory_pressure:
        lines.append(f'  memory_pressure: {memory_pressure}')
    session_id = runtime.get('session_id')
    if isinstance(session_id, str) and session_id:
        lines.append(f'  session_id: {session_id}')
    return lines if len(lines) > 1 else []


def _format_task_plan_section(task_plan: dict) -> list[str]:
    if not isinstance(task_plan, dict) or not task_plan:
        return []
    tasks = task_plan.get('tasks')
    if not isinstance(tasks, list) or not tasks:
        return []
    lines = ['\nActive task tracker state before condensation:']
    next_action = str(task_plan.get('next_action', '') or '').strip()
    if next_action:
        lines.append(f'  next action: {next_action[:240]}')
    for task in tasks[:12]:
        if not isinstance(task, dict):
            continue
        status = str(task.get('status', '?') or '?')
        desc = str(task.get('description', '') or '').strip()
        if not desc:
            continue
        result = str(task.get('result', '') or '').strip()
        suffix = f' -> {result[:120]}' if result else ''
        lines.append(f'  - [{status}] {desc[:180]}{suffix}')
    return lines if len(lines) > 1 else []


def _format_files_section(files: dict) -> list[str]:
    """Format files touched section."""
    if not files:
        return []
    lines = ['\nFiles touched before condensation:']
    for path, info in list(files.items())[:MAX_FILES_IN_COMPACT_SNAPSHOT]:
        suffix = ''
        file_hash = info.get('sha256')
        if isinstance(file_hash, str) and file_hash:
            short_hash = file_hash[:16]
            size = info.get('size')
            suffix = f' [sha256:{short_hash}'
            if isinstance(size, int):
                suffix += f', size={size}'
            suffix += ']'
        lines.append(f'  {info.get("action", "?")}: {path}{suffix}')
    return lines


def _format_errors_section(errors: list) -> list[str]:
    """Format recent errors section."""
    if not errors:
        return []
    lines = [f'\nRecent errors ({len(errors)}):']
    for err in errors[-5:]:
        lines.append('  • ' + clip_with_marker(str(err), 200, prefer='tail'))
    # #region agent log
    if lines:
        _agent_debug_log(
            'H3_unicode_bullet_expectation',
            'backend/context/pre_condensation_snapshot.py:_format_errors_section',
            'formatted-errors-bullet',
            {
                'sample_line': lines[-1],
                'sample_codepoints': [ord(ch) for ch in lines[-1][:4]],
            },
        )
    # #endregion
    return lines


def _format_decisions_section(decisions: list) -> list[str]:
    """Format key reasoning/decisions section."""
    if not decisions:
        return []
    lines = [f'\nKey reasoning/decisions ({len(decisions)}):']
    for dec in decisions[-8:]:
        lines.append(f'  • {dec[:200]}')
    return lines


def _format_invalidated_assumptions_section(invalidated: list) -> list[str]:
    """Format assumptions that should not be relied on after recovery."""
    if not invalidated:
        return []
    lines = [f'\nInvalidated assumptions ({len(invalidated)}) - do not rely on these:']
    for item in invalidated[-8:]:
        lines.append(f'  - {str(item)[:200]}')
    return lines


def _format_commands_section(commands: list) -> list[str]:
    """Format recent commands section."""
    if not commands:
        return []
    lines = [f'\nRecent commands ({len(commands)}):']
    for cmd_info in commands[-5:]:
        cmd = cmd_info.get('command', '')[:150]
        lines.append(f'  $ {cmd}')
        if 'output' in cmd_info:
            lines.append(f'    → {cmd_info["output"][:150]}')
    return lines


def _format_test_results_section(results: list) -> list[str]:
    """Format recent test command outcomes."""
    if not results:
        return []
    lines = [f'\nTest results before condensation ({len(results)}):']
    for result in results[-5:]:
        command = str(result.get('command', ''))[:150]
        status = str(result.get('status', '?')).upper()
        exit_code = result.get('exit_code')
        lines.append(f'  {status} (exit={exit_code}): {command}')
        output = str(result.get('output', '')).strip()
        if output:
            lines.append('    output: ' + clip_with_marker(output, 200, prefer='tail'))
    return lines


def _format_background_tasks_section(tasks: list) -> list[str]:
    """Format pending background commands that require terminal reads."""
    if not tasks:
        return []
    lines = [f'\nPending background tasks ({len(tasks)}):']
    for task in tasks[-5:]:
        if not isinstance(task, dict):
            continue
        session_id = str(task.get('session_id', '')).strip() or 'unknown session'
        command = str(task.get('command', ''))[:150]
        next_action = str(task.get('next_action', 'terminal_read'))[:150]
        lines.append(f'  - {session_id}: {command}')
        lines.append(f'    next: {next_action}')
    return lines


def _format_approaches_section(approaches: list) -> list[str]:
    """Format attempted approaches (failed/succeeded) section."""
    if not approaches:
        return []
    failed = [a for a in approaches if 'FAILED' in a.get('outcome', '')]
    succeeded = [a for a in approaches if a.get('outcome') == 'SUCCESS']
    lines = [
        f'\nAttempted approaches ({len(approaches)} total, {len(failed)} failed, {len(succeeded)} succeeded):',
        'FAILED approaches (DO NOT retry these):',
    ]
    for a in failed[-10:]:
        lines.append(f'  ✗ [{a.get("type", "?")}] {a.get("detail", "")[:200]}')
        lines.append(f'    → {a.get("outcome", "")[:200]}')
    if succeeded:
        lines.append('Succeeded approaches:')
        for a in succeeded[-5:]:
            lines.append(f'  ✓ [{a.get("type", "?")}] {a.get("detail", "")[:200]}')
    return lines
