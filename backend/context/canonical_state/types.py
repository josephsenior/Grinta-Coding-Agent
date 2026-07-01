"""Split submodule — see package facade for public API."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


SCHEMA_VERSION = 3
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
_MAX_DEPENDENCIES = 20
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
class SessionMetadata:
    """Compaction tracking metadata (system-populated, not LLM-generated)."""

    compaction_timestamp: str = ''
    turn_count: int = 0
    compaction_sequence: int = 0


@dataclass
class EnvironmentState:
    """Runtime environment context (system-populated)."""

    running_processes: list[str] = field(default_factory=list)
    active_ports: list[int] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)
    auth_status: str = ''


@dataclass
class TestSummary:
    """LLM-generated overview of test suite status."""

    overall: str = ''
    failing: list[str] = field(default_factory=list)
    not_run: list[str] = field(default_factory=list)
    last_run_clean: bool = False


@dataclass
class DependencyEntry:
    """A dependency or package that was added or modified."""

    name: str = ''
    version: str = ''


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
    completed_tasks: str = ''
    session_metadata: SessionMetadata = field(default_factory=SessionMetadata)
    environment_state: EnvironmentState = field(default_factory=EnvironmentState)
    test_summary: TestSummary = field(default_factory=TestSummary)
    open_questions: str = ''
    dependencies: list[DependencyEntry] = field(default_factory=list)
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
            'completed_tasks',
            'open_questions',
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
        session_meta = data.get('session_metadata')
        if isinstance(session_meta, dict):
            state.session_metadata = SessionMetadata(
                **_known_dataclass_fields(SessionMetadata, session_meta)
            )
        env_state = data.get('environment_state')
        if isinstance(env_state, dict):
            state.environment_state = EnvironmentState(
                **_known_dataclass_fields(EnvironmentState, env_state)
            )
        test_summ = data.get('test_summary')
        if isinstance(test_summ, dict):
            state.test_summary = TestSummary(
                **_known_dataclass_fields(TestSummary, test_summ)
            )
        raw_deps = data.get('dependencies', [])
        if isinstance(raw_deps, list):
            state.dependencies = [
                DependencyEntry(**_known_dataclass_fields(DependencyEntry, item))
                for item in raw_deps
                if isinstance(item, dict)
            ][-_MAX_DEPENDENCIES:]
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
        from backend.context.canonical_state.private import _string_list

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


def _known_dataclass_fields(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    from dataclasses import fields

    field_names = {field.name for field in fields(cls)}
    return {key: value for key, value in data.items() if key in field_names}
