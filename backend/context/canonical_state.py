"""Canonical task state for long-running coding-agent continuity.

This module owns the durable, structured facts that must survive compaction.
Other context surfaces may render or enrich this state, but they should not be
independent sources of truth.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.core.logger import app_logger as logger

if TYPE_CHECKING:
    from backend.ledger.event import Event
    from backend.orchestration.state.state import State

SCHEMA_VERSION = 2
CANONICAL_STATE_MARKER = '<CANONICAL_TASK_STATE>'

# High-precision phrases that signal an EXPLICIT task pivot (not a refinement
# or clarification). Kept deliberately narrow so that additive clarifications
# ("also add tests", "make it faster") never trigger objective supersession.
_PIVOT_MARKERS = (
    'actually, forget',
    'actually forget',
    'forget the',
    'forget about',
    'scrap that',
    'scrap the',
    'never mind the',
    'nevermind the',
    'change of plan',
    'new task:',
    'new objective:',
    'instead of',
    'stop working on',
    'drop the',
    'abandon the',
)
_MAX_ACTIVE_FILES = 30
_MAX_BLOCKERS = 12
_MAX_DECISIONS = 12
_MAX_FAILED_APPROACHES = 12
_MAX_BACKGROUND_TASKS = 8
_MAX_INVALIDATED = 10
_MAX_RECENT_WORK = 16
_MAX_TASK_PLAN_ITEMS = 20
_MAX_OUTPUT_CHARS = 360
# Durable storage cap for verification output. Larger than the rendered slice
# so the full-enough failure tail survives in the canonical JSON for the
# continuity gate and post-compact recovery to consult, even though the
# prompt render itself stays bounded.
_MAX_VERIFICATION_OUTPUT_CHARS = 2000
# Rendered slice of verification output inside the prompt packet. Kept small so
# render char-budgets are respected; tail-preferred so the assertion/error line
# (which lives at the end of a traceback) is what survives.
_RENDER_VERIFICATION_OUTPUT_CHARS = 220


def clip_with_marker(
    text: str,
    limit: int,
    *,
    prefer: str = 'head',
) -> str:
    """Clip *text* to *limit* chars leaving a visible omission marker.

    Unlike a bare ``text[:limit]`` slice, this never cuts silently: when
    content is dropped an explicit ``... (N chars omitted) ...`` marker is
    inserted so the model knows it is reading a fragment and can choose to
    re-read the source.

    Args:
        text: The text to clip.
        limit: Maximum length of the returned string (including the marker).
        prefer: ``'tail'`` keeps the END of the text (use for tracebacks /
            failure output, where the actionable line is last); ``'head'``
            keeps the BEGINNING (use for forward-reading prose). ``'both'``
            keeps head and tail around a central marker.

    Returns:
        The original text when it already fits, otherwise a clipped string
        with an omission marker.
    """
    text = str(text)
    if limit <= 0 or len(text) <= limit:
        return text
    omitted = len(text)
    if prefer == 'tail':
        marker = '... ({} chars omitted) ...\n'
        body_len = max(0, limit - len(marker.format(omitted)))
        tail = text[-body_len:] if body_len else ''
        kept = len(tail)
        return marker.format(omitted - kept) + tail
    if prefer == 'both':
        marker = '\n... ({} chars omitted) ...\n'
        body_len = max(0, limit - len(marker.format(omitted)))
        half = body_len // 2
        if half <= 0:
            return text[:limit]
        head = text[:half]
        tail = text[-half:]
        kept = len(head) + len(tail)
        return head + marker.format(omitted - kept) + tail
    # head (default)
    marker = '\n... ({} chars omitted) ...'
    body_len = max(0, limit - len(marker.format(omitted)))
    head = text[:body_len] if body_len else ''
    kept = len(head)
    return head + marker.format(omitted - kept)


@dataclass
class FieldFreshness:
    """Event provenance for a canonical field."""

    event_id: int | None = None
    updated_at: str = ''
    source: str = ''


@dataclass
class VerificationState:
    """Latest known verification command result."""

    command: str = ''
    status: str = ''
    exit_code: int | None = None
    output: str = ''
    event_id: int | None = None
    updated_at: str = ''


@dataclass
class FailedApproach:
    """A failed action/strategy that should not be repeated unchanged."""

    kind: str = ''
    detail: str = ''
    outcome: str = ''
    fingerprint: str = ''
    event_id: int | None = None
    last_seen: str = ''


@dataclass
class BackgroundTaskState:
    """Detached background process that still needs explicit terminal polling."""

    session_id: str = ''
    command: str = ''
    status: str = 'still running'
    next_action: str = ''
    event_id: int | None = None
    updated_at: str = ''


@dataclass
class RecentWorkItem:
    """A compact factual ledger of work already inspected or run."""

    kind: str = ''
    detail: str = ''
    outcome: str = ''
    event_id: int | None = None
    updated_at: str = ''


@dataclass
class TaskPlanItem:
    """Latest task-tracker item preserved across compaction."""

    description: str = ''
    status: str = 'todo'
    result: str = ''
    task_id: str = ''
    event_id: int | None = None
    updated_at: str = ''


@dataclass
class CanonicalTaskState:
    """Durable compact task profile used by prompt packets and compaction gates."""

    schema_version: int = SCHEMA_VERSION
    objective: str = ''
    latest_directive: str = ''
    superseding_directive: str = ''
    active_plan: str = ''
    next_action: str = ''
    implementation_checkpoint: str = ''
    task_plan: list[TaskPlanItem] = field(default_factory=list)
    active_files: list[str] = field(default_factory=list)
    verification: VerificationState = field(default_factory=VerificationState)
    blockers: list[str] = field(default_factory=list)
    failed_approaches: list[FailedApproach] = field(default_factory=list)
    background_tasks: list[BackgroundTaskState] = field(default_factory=list)
    recent_work: list[RecentWorkItem] = field(default_factory=list)
    invalidated_assumptions: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    vcs_status: str = ''
    narrative_summary: str = ''
    source_event_ids: dict[str, int] = field(default_factory=dict)
    field_freshness: dict[str, FieldFreshness] = field(default_factory=dict)
    last_updated: str = ''

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'CanonicalTaskState':
        state = cls()
        for key in (
            'schema_version',
            'objective',
            'latest_directive',
            'superseding_directive',
            'active_plan',
            'next_action',
            'implementation_checkpoint',
            'active_files',
            'blockers',
            'invalidated_assumptions',
            'decisions',
            'vcs_status',
            'narrative_summary',
            'source_event_ids',
            'last_updated',
        ):
            if key in data:
                setattr(state, key, data[key])
        verification = data.get('verification')
        if isinstance(verification, dict):
            state.verification = VerificationState(
                **_known_dataclass_fields(VerificationState, verification)
            )
        state.failed_approaches = [
            FailedApproach(**_known_dataclass_fields(FailedApproach, item))
            for item in data.get('failed_approaches', [])
            if isinstance(item, dict)
        ]
        state.background_tasks = [
            BackgroundTaskState(**_known_dataclass_fields(BackgroundTaskState, item))
            for item in data.get('background_tasks', [])
            if isinstance(item, dict)
        ]
        state.recent_work = [
            RecentWorkItem(**_known_dataclass_fields(RecentWorkItem, item))
            for item in data.get('recent_work', [])
            if isinstance(item, dict)
        ][-_MAX_RECENT_WORK:]
        state.task_plan = [
            TaskPlanItem(**_known_dataclass_fields(TaskPlanItem, item))
            for item in data.get('task_plan', [])
            if isinstance(item, dict)
        ][-_MAX_TASK_PLAN_ITEMS:]
        freshness: dict[str, FieldFreshness] = {}
        raw_freshness = data.get('field_freshness', {})
        if isinstance(raw_freshness, dict):
            for key, value in raw_freshness.items():
                if isinstance(value, dict):
                    freshness[str(key)] = FieldFreshness(
                        **_known_dataclass_fields(FieldFreshness, value)
                    )
        state.field_freshness = freshness
        state.active_files = _string_list(state.active_files, _MAX_ACTIVE_FILES)
        state.blockers = _string_list(state.blockers, _MAX_BLOCKERS)
        state.invalidated_assumptions = _string_list(
            state.invalidated_assumptions, _MAX_INVALIDATED
        )
        state.decisions = _string_list(state.decisions, _MAX_DECISIONS)
        return state


@dataclass(frozen=True)
class CanonicalValidationResult:
    ok: bool
    missing: tuple[str, ...] = ()


def canonical_state_path(*, state: State | None = None) -> Path:
    from backend.context.session_context import scoped_agent_path

    return scoped_agent_path('canonical_task_state', '.json', state=state)


def load_canonical_state(*, state: State | None = None) -> CanonicalTaskState:
    path = canonical_state_path(state=state)
    if not path.is_file():
        return _import_legacy_state(state=state)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            return CanonicalTaskState.from_dict(data)
    except (OSError, json.JSONDecodeError, TypeError):
        logger.debug('Failed to load canonical task state', exc_info=True)
    return CanonicalTaskState()


def save_canonical_state(
    canonical: CanonicalTaskState,
    *,
    state: State | None = None,
) -> None:
    canonical.last_updated = _now()
    path = canonical_state_path(state=state)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(canonical.to_dict(), indent=2, ensure_ascii=False),
            encoding='utf-8',
        )
    except OSError:
        logger.debug('Failed to save canonical task state', exc_info=True)


def reduce_events_into_state(
    events: list[Event],
    previous: CanonicalTaskState | None = None,
    *,
    state: State | None = None,
    persist: bool = True,
    source: str = 'events',
) -> CanonicalTaskState:
    from backend.context.pre_condensation_snapshot import extract_snapshot

    canonical = previous or load_canonical_state(state=state)
    if not events:
        return canonical
    snapshot = extract_snapshot(events)
    reduced = reduce_snapshot_into_state(
        snapshot,
        canonical,
        latest_event_id=_latest_event_id(events),
        source=source,
    )
    _resolve_background_tasks_from_events(reduced, events)
    if persist:
        save_canonical_state(reduced, state=state)
    return reduced


def reduce_snapshot_into_state(
    snapshot: dict[str, Any],
    canonical: CanonicalTaskState | None = None,
    *,
    latest_event_id: int | None = None,
    source: str = 'snapshot',
    persist_state: State | None = None,
) -> CanonicalTaskState:
    canonical = canonical or load_canonical_state(state=persist_state)
    event_id = latest_event_id
    if event_id is None:
        event_id = _snapshot_latest_event_id(snapshot)

    objective = _clean(snapshot.get('objective'))
    if objective and not canonical.objective:
        _set_field(canonical, 'objective', objective, event_id, source)
    latest_directive = _clean(snapshot.get('latest_directive'))
    if latest_directive:
        _set_field(canonical, 'latest_directive', latest_directive, event_id, source)
        if (
            canonical.objective
            and _normalize(latest_directive) != _normalize(canonical.objective)
            and _is_pivot_directive(latest_directive)
        ):
            _set_field(
                canonical,
                'superseding_directive',
                latest_directive,
                event_id,
                source,
            )

    files = snapshot.get('files_touched', {})
    if isinstance(files, dict) and files:
        canonical.active_files = _merge_strings(
            canonical.active_files,
            [path for path in files if isinstance(path, str) and path],
            _MAX_ACTIVE_FILES,
        )
        _touch_field(canonical, 'active_files', event_id, source)

    latest_test = _latest_dict(snapshot.get('test_results', []))
    if latest_test:
        _update_verification(canonical, latest_test, event_id, source)

    _merge_failed_approaches(canonical, snapshot, event_id, source)
    _merge_background_tasks(canonical, snapshot, event_id, source)
    _merge_task_plan(canonical, snapshot, event_id, source)
    _merge_recent_work(canonical, snapshot, event_id, source)
    _update_blockers(canonical, snapshot, event_id, source)
    canonical.decisions = _merge_strings(
        canonical.decisions,
        _string_tail(snapshot.get('decisions', []), _MAX_DECISIONS, _MAX_OUTPUT_CHARS),
        _MAX_DECISIONS,
    )
    if canonical.decisions:
        _touch_field(canonical, 'decisions', event_id, source)
    canonical.invalidated_assumptions = _merge_strings(
        canonical.invalidated_assumptions,
        _string_tail(
            snapshot.get('invalidated_assumptions', []),
            _MAX_INVALIDATED,
            _MAX_OUTPUT_CHARS,
        ),
        _MAX_INVALIDATED,
    )
    if canonical.invalidated_assumptions:
        _touch_field(canonical, 'invalidated_assumptions', event_id, source)
    _update_vcs_status(canonical, snapshot, event_id, source)
    if not canonical.next_action:
        inferred = _infer_next_action(canonical)
        if inferred:
            _set_field(canonical, 'next_action', inferred, event_id, source)
    canonical.last_updated = _now()
    return canonical


def apply_canonical_patch(
    canonical: CanonicalTaskState,
    patch: dict[str, Any],
    *,
    event_id: int | None,
    source: str = 'llm_patch',
) -> CanonicalTaskState:
    """Apply low-authority LLM enrichment without overwriting newer facts."""
    text_fields = {
        'active_plan': 'active_plan',
        'next_action': 'next_action',
        'implementation_checkpoint': 'implementation_checkpoint',
        'narrative_summary': 'narrative_summary',
        'vcs_status': 'vcs_status',
    }
    for incoming, field_name in text_fields.items():
        value = _clean(patch.get(incoming))
        if value:
            _set_field(canonical, field_name, value, event_id, source)

    for incoming, field_name, limit in (
        ('blockers', 'blockers', _MAX_BLOCKERS),
        ('decisions', 'decisions', _MAX_DECISIONS),
        ('invalidated_assumptions', 'invalidated_assumptions', _MAX_INVALIDATED),
        ('active_files', 'active_files', _MAX_ACTIVE_FILES),
    ):
        values = _coerce_string_list(patch.get(incoming))
        if values:
            setattr(
                canonical,
                field_name,
                _merge_strings(getattr(canonical, field_name), values, limit),
            )
            _touch_field(canonical, field_name, event_id, source)
    canonical.last_updated = _now()
    return canonical


def render_canonical_state_for_prompt(
    canonical: CanonicalTaskState,
    *,
    char_budget: int = 2800,
) -> str:
    lines = [CANONICAL_STATE_MARKER, 'Canonical task state:']
    _append(lines, f'- Objective: {canonical.objective}')
    if canonical.superseding_directive:
        _append(
            lines,
            f'- \u26a0 Objective superseded by: {canonical.superseding_directive}',
        )
    if canonical.latest_directive and canonical.latest_directive != canonical.objective:
        _append(lines, f'- Latest directive: {canonical.latest_directive}')
    _append(lines, f'- Next action: {canonical.next_action}')
    _append(
        lines, f'- Implementation checkpoint: {canonical.implementation_checkpoint}'
    )
    if canonical.verification.command:
        status = canonical.verification.status.upper() or '?'
        _append(
            lines,
            f'- Latest verification: {status} '
            f'(exit={canonical.verification.exit_code}): {canonical.verification.command}',
        )
        _append(
            lines,
            '  Output: '
            + clip_with_marker(
                canonical.verification.output,
                _RENDER_VERIFICATION_OUTPUT_CHARS,
                prefer='tail',
            ),
        )
    _append(lines, f'- Active plan: {canonical.active_plan}')
    if canonical.task_plan:
        _append(lines, '- Task tracker:')
        for plan_item in canonical.task_plan[-10:]:
            detail = f'[{plan_item.status}] {plan_item.description}'
            if plan_item.result:
                detail += f' -> {plan_item.result}'
            _append(lines, f'  - {detail}')
    if canonical.active_files:
        _append(lines, '- Active files: ' + ', '.join(canonical.active_files[-12:]))
    _append_list(lines, 'Blockers', canonical.blockers[-6:])
    if canonical.background_tasks:
        _append(lines, '- Background tasks:')
        for task in canonical.background_tasks[-4:]:
            session = task.session_id or 'unknown session'
            _append(lines, f'  - {session}: {task.command} ({task.status})')
            _append(lines, f'    Next: {task.next_action}')
    if canonical.recent_work:
        _append(lines, '- Recent work ledger:')
        for work_item in canonical.recent_work[-8:]:
            detail = f'[{work_item.kind}] {work_item.detail}'
            if work_item.outcome:
                detail += f' -> {work_item.outcome}'
            _append(lines, f'  - {detail}')
    if canonical.failed_approaches:
        _append(lines, '- Failed approaches to avoid unless inputs changed:')
        for approach in canonical.failed_approaches[-6:]:
            _append(
                lines, f'  - [{approach.kind}] {approach.detail} -> {approach.outcome}'
            )
    _append_list(
        lines, 'Invalidated assumptions', canonical.invalidated_assumptions[-5:]
    )
    _append_list(lines, 'Decisions', canonical.decisions[-5:])
    _append(lines, f'- VCS status: {canonical.vcs_status}')
    _append(lines, f'- Summary: {canonical.narrative_summary}')
    lines.append(CANONICAL_STATE_MARKER)
    block = '\n'.join(line for line in lines if line.strip())
    if len(block) > char_budget:
        block = (
            block[: char_budget - 48].rstrip()
            + '\n... (canonical state truncated)\n'
            + CANONICAL_STATE_MARKER
        )
    return block


def validate_canonical_state_for_compaction(
    canonical: CanonicalTaskState,
    events: list[Event],
) -> CanonicalValidationResult:
    from backend.context.pre_condensation_snapshot import extract_snapshot

    snapshot = extract_snapshot(events)
    missing: list[str] = []
    if snapshot.get('latest_directive') and not canonical.latest_directive:
        missing.append('latest_directive')
    if snapshot.get('files_touched') and not canonical.active_files:
        missing.append('active_files')
    if snapshot.get('test_results') and not canonical.verification.command:
        missing.append('latest_verification')
    if snapshot.get('background_tasks') and not canonical.background_tasks:
        missing.append('background_tasks')
    if snapshot.get('task_plan') and not canonical.task_plan:
        missing.append('task_plan')
    if snapshot.get('task_plan') and not canonical.next_action:
        missing.append('next_action')
    fingerprints = [
        item.fingerprint for item in canonical.failed_approaches if item.fingerprint
    ]
    if len(fingerprints) != len(set(fingerprints)):
        missing.append('deduped_failed_approaches')
    if any(
        _is_control_noise(text) for text in [*canonical.decisions, *canonical.blockers]
    ):
        missing.append('control_noise_removed')
    return CanonicalValidationResult(ok=not missing, missing=tuple(missing))


def _import_legacy_state(*, state: State | None = None) -> CanonicalTaskState:
    canonical = CanonicalTaskState()
    try:
        from backend.engine.tools.working_memory import _load_memory

        memory = _load_memory()
        if isinstance(memory, dict):
            canonical.active_plan = _clean(memory.get('plan'))
            canonical.next_action = _extract_next_action(
                memory.get('current_state', '')
            )
            canonical.narrative_summary = _clean(memory.get('findings'))[:900]
            canonical.blockers = _coerce_string_list(memory.get('blockers'))[
                -_MAX_BLOCKERS:
            ]
            canonical.decisions = _coerce_string_list(memory.get('decisions'))[
                -_MAX_DECISIONS:
            ]
    except Exception:
        logger.debug('Legacy working memory import failed', exc_info=True)
    try:
        from backend.context.session_memory import get_content_for_compaction

        session_memory = get_content_for_compaction(state=state)
        if session_memory and not canonical.narrative_summary:
            canonical.narrative_summary = session_memory[:900]
    except Exception:
        logger.debug('Legacy session memory import failed', exc_info=True)
    return canonical


def _known_dataclass_fields(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    from dataclasses import fields

    field_names = {field.name for field in fields(cls)}
    return {key: value for key, value in data.items() if key in field_names}


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
        return f'Switch to the superseding directive: {canonical.superseding_directive}'[
            :240
        ]
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
