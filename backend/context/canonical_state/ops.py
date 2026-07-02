"""Split submodule — see package facade for public API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.context.canonical_state.private import (
    _append,
    _append_list,
    _clean,
    _coerce_string_list,
    _extract_next_action,
    _infer_next_action,
    _is_control_noise,
    _is_pivot_directive,
    _latest_dict,
    _latest_event_id,
    _merge_background_tasks,
    _merge_failed_approaches,
    _merge_recent_work,
    _merge_strings,
    _merge_task_plan,
    _normalize,
    _now,
    _resolve_background_tasks_from_events,
    _set_field,
    _snapshot_latest_event_id,
    _string_tail,
    _touch_field,
    _update_blockers,
    _update_vcs_status,
    _update_verification,
)
from backend.context.canonical_state.types import (
    _MAX_ACTIVE_FILES,
    _MAX_BLOCKERS,
    _MAX_DECISIONS,
    _MAX_DEPENDENCIES,
    _MAX_INVALIDATED,
    _MAX_OUTPUT_CHARS,
    _RENDER_VERIFICATION_OUTPUT_CHARS,
    CANONICAL_STATE_MARKER,
    CanonicalTaskState,
    CanonicalValidationResult,
    DependencyEntry,
    EnvironmentState,
    SessionMetadata,
    TestSummary,
    clip_with_marker,
)
from backend.core.logging.logger import app_logger as logger

if TYPE_CHECKING:
    from backend.ledger.event import Event
    from backend.orchestration.state.state import State


def _canonical_state_path(*, state: State | None = None) -> Path:
    """Resolve path via facade module so tests can monkeypatch ``canonical_state_path``."""
    from backend.context import canonical_state as facade

    return facade.canonical_state_path(state=state)


def _merge_narrative(existing: str, incoming: str, *, max_chars: int = 1200) -> str:
    """Merge an incoming compaction narrative with the existing one.

    Prevents session-arc loss across compactions: if the incoming narrative
    focuses on recent work and doesn't contain key information from the
    existing narrative, the existing narrative is prepended.
    """
    existing = (existing or '').strip()
    incoming = (incoming or '').strip()
    if not existing:
        return incoming[:max_chars]
    if not incoming:
        return existing[:max_chars]
    if existing in incoming or incoming in existing:
        longer = existing if len(existing) >= len(incoming) else incoming
        return longer[:max_chars]
    overlap = _narrative_overlap(existing, incoming)
    if overlap > 0.4:
        return incoming[:max_chars]
    merged = f'{existing}\n\nRecent: {incoming}'
    return merged[:max_chars]


def _narrative_overlap(a: str, b: str) -> float:
    """Estimate fraction of ``a``'s content words also present in ``b``."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a:
        return 0.0
    return len(words_a & words_b) / len(words_a)


def canonical_state_path(*, state: State | None = None) -> Path:
    from backend.context.memory.session_context import scoped_agent_path

    return scoped_agent_path('canonical_task_state', '.json', state=state)


def load_canonical_state(*, state: State | None = None) -> CanonicalTaskState:
    path = _canonical_state_path(state=state)
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
    path = _canonical_state_path(state=state)
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
    from backend.context.compactor.pre_condensation_snapshot import extract_snapshot

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

    from backend.context.compactor.pre_condensation_snapshot import (
        snapshot_user_objective,
    )

    objective, latest_directive = snapshot_user_objective(snapshot)
    objective = _clean(objective)
    if objective and not canonical.objective:
        _set_field(canonical, 'objective', objective, event_id, source)
    latest_directive = _clean(latest_directive)
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
        'vcs_status': 'vcs_status',
    }
    for incoming, field_name in text_fields.items():
        value = _clean(patch.get(incoming))
        if value:
            _set_field(canonical, field_name, value, event_id, source)

    incoming_narrative = _clean(patch.get('narrative_summary'))
    if incoming_narrative:
        existing = getattr(canonical, 'narrative_summary', '')
        merged = _merge_narrative(existing, incoming_narrative)
        _set_field(canonical, 'narrative_summary', merged, event_id, source)

    incoming_completed = _clean(patch.get('completed_tasks'))
    if incoming_completed:
        _set_field(canonical, 'completed_tasks', incoming_completed, event_id, source)

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

    open_questions = _clean(patch.get('open_questions'))
    if open_questions:
        _set_field(canonical, 'open_questions', open_questions[:800], event_id, source)

    test_patch = patch.get('test_summary')
    if isinstance(test_patch, dict) and test_patch.get('overall'):
        canonical.test_summary = TestSummary(
            overall=str(test_patch.get('overall', ''))[:40],
            failing=[
                str(t)[:120]
                for t in test_patch.get('failing', [])
                if isinstance(t, (str, int)) and str(t).strip()
            ][-_MAX_DEPENDENCIES:],
            not_run=[
                str(t)[:120]
                for t in test_patch.get('not_run', [])
                if isinstance(t, (str, int)) and str(t).strip()
            ][-_MAX_DEPENDENCIES:],
            last_run_clean=bool(test_patch.get('last_run_clean', False)),
        )
        _touch_field(canonical, 'test_summary', event_id, source)

    deps_patch = patch.get('dependencies')
    if isinstance(deps_patch, list) and deps_patch:
        incoming_deps = [
            DependencyEntry(
                name=str(d.get('name', ''))[:120],
                version=str(d.get('version', ''))[:60],
            )
            for d in deps_patch
            if isinstance(d, dict) and d.get('name')
        ]
        if incoming_deps:
            by_name = {dep.name: dep for dep in canonical.dependencies}
            for dep in incoming_deps:
                by_name[dep.name] = dep
            canonical.dependencies = list(by_name.values())[-_MAX_DEPENDENCIES:]
            _touch_field(canonical, 'dependencies', event_id, source)

    session_meta = patch.get('session_metadata')
    if isinstance(session_meta, dict) and session_meta:
        canonical.session_metadata = SessionMetadata(
            compaction_timestamp=str(session_meta.get('compaction_timestamp', ''))[:40],
            turn_count=int(session_meta.get('turn_count', 0) or 0),
            compaction_sequence=int(session_meta.get('compaction_sequence', 0) or 0),
        )
        _touch_field(canonical, 'session_metadata', event_id, source)

    env_patch = patch.get('environment_state')
    if isinstance(env_patch, dict) and env_patch:
        canonical.environment_state = EnvironmentState(
            running_processes=[
                str(p)[:200]
                for p in env_patch.get('running_processes', [])
                if isinstance(p, (str, int)) and str(p).strip()
            ][-_MAX_DEPENDENCIES:],
            active_ports=[
                int(p)
                for p in env_patch.get('active_ports', [])
                if isinstance(p, int) or (isinstance(p, str) and p.isdigit())
            ][-_MAX_DEPENDENCIES:],
            env_vars={
                str(k)[:80]: str(v)[:200]
                for k, v in env_patch.get('env_vars', {}).items()
                if k and v
            }
            if isinstance(env_patch.get('env_vars'), dict)
            else {},
            auth_status=str(env_patch.get('auth_status', ''))[:200],
        )
        _touch_field(canonical, 'environment_state', event_id, source)

    canonical.last_updated = _now()
    return canonical


def render_canonical_state_for_prompt(
    canonical: CanonicalTaskState,
    *,
    char_budget: int = 2800,
    include_objective: bool = True,
    include_latest_directive: bool = True,
    include_next_action: bool = True,
) -> str:
    lines = [CANONICAL_STATE_MARKER, 'Canonical task state:']
    if include_objective:
        _append(lines, f'- Objective: {canonical.objective}')
    if canonical.superseding_directive:
        _append(
            lines,
            f'- \u26a0 Objective superseded by: {canonical.superseding_directive}',
        )
    if (
        include_latest_directive
        and canonical.latest_directive
        and canonical.latest_directive != canonical.objective
    ):
        _append(lines, f'- Latest directive: {canonical.latest_directive}')
    if include_next_action:
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
            if task.recent_output:
                snippet = task.recent_output
                if len(snippet) > 800:
                    snippet = snippet[:800] + '...'
                _append(lines, f'    Recent output: {snippet}')
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
    if canonical.completed_tasks:
        _append(
            lines,
            f'- Work completed this session: {canonical.completed_tasks[:600]}',
        )
    if canonical.test_summary.overall:
        test_line = f'- Test summary: {canonical.test_summary.overall}'
        if canonical.test_summary.failing:
            test_line += f' (failing: {", ".join(canonical.test_summary.failing[:8])})'
        if canonical.test_summary.last_run_clean:
            test_line += ' [last run clean]'
        _append(lines, test_line)
    if canonical.dependencies:
        deps_str = ', '.join(
            f'{d.name}@{d.version}' for d in canonical.dependencies[-10:]
        )
        _append(lines, f'- Dependencies: {deps_str}')
    if canonical.open_questions:
        _append(lines, f'- Open questions: {canonical.open_questions[:400]}')
    if canonical.session_metadata.compaction_timestamp:
        meta = canonical.session_metadata
        _append(
            lines,
            f'- Session metadata: turn={meta.turn_count}, '
            f'compaction=#{meta.compaction_sequence}, '
            f'at={meta.compaction_timestamp}',
        )
    if canonical.environment_state.running_processes:
        env = canonical.environment_state
        _append(lines, '- Environment state:')
        for proc in env.running_processes[-5:]:
            _append(lines, f'  - Running: {proc}')
        if env.active_ports:
            _append(lines, f'  - Active ports: {", ".join(str(p) for p in env.active_ports)}')
        if env.auth_status:
            _append(lines, f'  - Auth: {env.auth_status}')
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
    from backend.context.compactor.pre_condensation_snapshot import extract_snapshot

    snapshot = extract_snapshot(events)
    missing: list[str] = []
    from backend.context.compactor.pre_condensation_snapshot import (
        snapshot_user_objective,
    )

    _, latest_directive = snapshot_user_objective(snapshot)
    if latest_directive and not canonical.latest_directive:
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
        from backend.context.memory.session_memory import get_content_for_compaction

        session_memory = get_content_for_compaction(state=state)
        if session_memory and not canonical.narrative_summary:
            canonical.narrative_summary = session_memory[:900]
    except Exception:
        logger.debug('Legacy session memory import failed', exc_info=True)
    return canonical
