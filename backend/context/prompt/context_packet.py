"""Prompt-facing context packet built from canonical task state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from backend.context.canonical_state import (
    CANONICAL_STATE_MARKER,
    CanonicalTaskState,
    load_canonical_state,
    reduce_events_into_state,
    render_canonical_state_for_prompt,
)
from backend.context.compactor.pre_condensation_snapshot import load_snapshot
from backend.core.logging.logger import app_logger as logger
from backend.ledger.action import MessageAction
from backend.ledger.observation.agent import AgentCondensationObservation

if TYPE_CHECKING:
    from backend.ledger.event import Event
    from backend.orchestration.state.state import State

CONTEXT_PACKET_MARKER = '<CONTEXT_PACKET>'
DEFAULT_CONTEXT_PACKET_CHAR_BUDGET = 6_000
MIN_LARGE_CONTEXT_PACKET_CHAR_BUDGET = 8_000
MAX_CONTEXT_PACKET_CHAR_BUDGET = 32_000

_POST_COMPACT_FRAMING = (
    '⚠️ SYSTEM NOTE: Conversation history was compressed. '
    'The canonical task state and restored context above are your '
    'source of truth — do not hallucinate next actions. '
    'Continue from the next_action field.\n\n'
)


@dataclass(frozen=True)
class ContextPacket:
    content: str
    section_lengths: dict[str, int]


_UserTurn = tuple[int | str | None, str, str]


def build_context_packet_observation(
    events: list[Event],
    history: list[Event],
    *,
    state: State | None = None,
    llm_config: object | None = None,
    just_compacted: bool = False,
    char_budget: int = DEFAULT_CONTEXT_PACKET_CHAR_BUDGET,
) -> AgentCondensationObservation | None:
    packet = build_context_packet(
        events,
        history,
        state=state,
        llm_config=llm_config,
        just_compacted=just_compacted,
        char_budget=char_budget,
    )
    if packet is None:
        return None
    logger.info(
        'Context packet assembled (%d chars; sections=%s)',
        len(packet.content),
        packet.section_lengths,
    )
    return AgentCondensationObservation(
        content=packet.content,
        is_working_set=True,
    )


def build_context_packet(
    events: list[Event],
    history: list[Event],
    *,
    state: State | None = None,
    llm_config: object | None = None,
    just_compacted: bool = False,
    char_budget: int = DEFAULT_CONTEXT_PACKET_CHAR_BUDGET,
) -> ContextPacket | None:
    char_budget = _resolve_packet_char_budget(llm_config, char_budget)
    canonical = _canonical_for_packet(history, state=state)
    sections: list[tuple[str, str]] = []
    snapshot = _load_snapshot_for_request_context(state=state)
    user_context = _user_request_context(
        history,
        prompt_events=events,
        snapshot=snapshot,
    )
    if user_context:
        sections.append(
            (
                'recent_user_request_context',
                _bounded_section(
                    'Recent user request context',
                    user_context,
                    max(1400, int(char_budget * 0.11)),
                ),
            )
        )
    checkpoint = _operational_checkpoint(canonical)
    if checkpoint:
        sections.append(
            (
                'operational_checkpoint',
                _bounded_section(
                    'Operational checkpoint',
                    checkpoint,
                    max(1200, int(char_budget * 0.11)),
                ),
            )
        )
    if _canonical_has_packet_details(canonical):
        canonical_block = render_canonical_state_for_prompt(
            canonical,
            char_budget=max(4200, int(char_budget * 0.41)),
            include_objective=False,
            include_latest_directive=False,
            include_next_action=False,
        )
        if canonical_block:
            sections.append(('canonical_state', canonical_block))
    active_status = _active_status(canonical)
    if active_status:
        sections.append(
            (
                'active_status',
                _bounded_section(
                    'Active tool/background status',
                    active_status,
                    max(900, int(char_budget * 0.07)),
                ),
            )
        )
    summary = _latest_summary(history)
    if summary:
        sections.append(
            (
                'latest_validated_summary',
                _bounded_section(
                    'Latest validated summary',
                    summary,
                    max(900, int(char_budget * 0.09)),
                ),
            )
        )
    tail = _recent_tail_summary(events)
    if tail:
        sections.append(
            (
                'recent_causal_tail',
                _bounded_section(
                    'Recent causal tail',
                    tail,
                    max(1200, int(char_budget * 0.14)),
                ),
            )
        )
    restore_hints = (
        _restore_hints(
            state=state,
            include_latest_directive=not bool(user_context),
        )
        if just_compacted
        else ''
    )
    if restore_hints:
        sections.append(
            (
                'restore_hints',
                _bounded_section(
                    'Compact restore hints',
                    restore_hints,
                    max(900, int(char_budget * 0.07)),
                ),
            )
        )
    if not sections:
        return None
    content, lengths = _assemble_sections(sections, char_budget)
    if just_compacted:
        content = _POST_COMPACT_FRAMING + content
        lengths['_post_compact_framing'] = len(_POST_COMPACT_FRAMING)
    return ContextPacket(content=content, section_lengths=lengths)


def _resolve_packet_char_budget(llm_config: object | None, configured: int) -> int:
    try:
        from backend.inference.capabilities.context_limits import limits_from_config

        limits = limits_from_config(llm_config, unknown_default=False)
        usable = limits.usable_input_tokens
        if isinstance(usable, int) and usable >= 100_000:
            return max(
                MIN_LARGE_CONTEXT_PACKET_CHAR_BUDGET,
                min(MAX_CONTEXT_PACKET_CHAR_BUDGET, int(usable * 0.04)),
            )
    except Exception:
        logger.debug('Context packet budget resolution failed', exc_info=True)
    return configured


def _canonical_for_packet(
    history: list[Event],
    *,
    state: State | None,
) -> CanonicalTaskState:
    canonical = load_canonical_state(state=state)
    if history:
        canonical = reduce_events_into_state(
            history,
            canonical,
            state=state,
            persist=state is not None,
            source='context_packet',
        )
    return canonical


def _canonical_has_packet_details(canonical: CanonicalTaskState) -> bool:
    """True when canonical state adds facts not already covered by packet sections."""
    return bool(
        canonical.superseding_directive
        or canonical.active_plan
        or canonical.implementation_checkpoint
        or canonical.task_plan
        or canonical.active_files
        or canonical.verification.command
        or canonical.blockers
        or canonical.failed_approaches
        or canonical.background_tasks
        or canonical.recent_work
        or canonical.invalidated_assumptions
        or canonical.decisions
        or canonical.vcs_status
        or canonical.narrative_summary
    )


def _latest_summary(history: list[Event]) -> str:
    from backend.ledger.observation.agent import AgentCondensationObservation

    for event in reversed(history):
        if not isinstance(event, AgentCondensationObservation):
            continue
        content = (event.content or '').strip()
        if not content:
            continue
        if any(
            marker in content
            for marker in (
                CONTEXT_PACKET_MARKER,
                CANONICAL_STATE_MARKER,
                '<DURABLE_WORKING_SET>',
                '<POST_COMPACT_RESTORE>',
                '<RESTORED_CONTEXT>',
            )
        ):
            continue
        return content[:900]
    return ''


def _load_snapshot_for_request_context(*, state: State | None) -> dict | None:
    if state is None:
        return None
    try:
        return load_snapshot(state=state)
    except Exception:
        logger.debug('Request-context snapshot load failed', exc_info=True)
        return None


def _user_request_context(
    history: list[Event],
    *,
    prompt_events: list[Event],
    snapshot: dict | None = None,
) -> str:
    user_turns = _dedupe_user_turns(
        [*_user_turns_from_snapshot(snapshot), *_user_turns_from_events(history)]
    )
    prompt_turns = _user_turns_from_events(prompt_events)
    missing_turns = [
        turn for turn in user_turns if not _turn_is_present(turn, prompt_turns)
    ]
    if not missing_turns:
        history_user_count = len(_user_turns_from_events(history))
        if history_user_count > 1 and prompt_turns:
            logger.debug(
                'User request context skipped: history has %d user turn(s) and '
                'all appear present in prompt (%d prompt user turn(s))',
                history_user_count,
                len(prompt_turns),
            )
        return ''

    selected = missing_turns[-6:]
    lines: list[str] = []
    omitted = len(missing_turns) - len(selected)
    if omitted:
        lines.append(f'{omitted} older preserved user message(s) omitted.')
    lines.append('Preserved user messages not otherwise in prompt:')
    lines.extend('- ' + _format_user_turn(turn, 420) for turn in selected)
    return '\n'.join(lines)


def _user_turns_from_events(events: list[Event]) -> list[_UserTurn]:
    turns: list[_UserTurn] = []
    for event in events:
        if not isinstance(event, MessageAction):
            continue
        event_source = getattr(event, 'source', None)
        source_value = getattr(event_source, 'value', event_source)
        if str(source_value).lower() != 'user':
            continue
        text = _clean_user_text(getattr(event, 'content', ''))
        if not text:
            continue
        turns.append((_clean_event_id(getattr(event, 'id', None)), text, 'history'))
    return turns


def _user_turns_from_snapshot(snapshot: dict | None) -> list[_UserTurn]:
    if not isinstance(snapshot, dict):
        return []
    raw_turns = snapshot.get('recent_user_messages')
    turns: list[_UserTurn] = []
    if isinstance(raw_turns, list):
        for item in raw_turns:
            if not isinstance(item, dict):
                continue
            text = _clean_user_text(item.get('text', ''))
            if not text:
                continue
            turns.append((_clean_event_id(item.get('event_id')), text, 'snapshot'))
    if turns:
        return turns

    latest = _clean_user_text(snapshot.get('latest_directive', ''))
    if latest:
        turns.append(('snapshot:latest', latest, 'snapshot'))
    objective = _clean_user_text(snapshot.get('objective', ''))
    if objective and objective != latest:
        turns.insert(0, ('snapshot:objective', objective, 'snapshot'))
    return turns


def _dedupe_user_turns(turns: list[_UserTurn]) -> list[_UserTurn]:
    merged: list[_UserTurn] = []
    seen: set[tuple[str, str]] = set()
    for turn in turns:
        key = _turn_key(turn)
        if key in seen:
            continue
        seen.add(key)
        merged.append(turn)
    return merged


def _clean_user_text(value: object) -> str:
    return ' '.join(str(value or '').split())


def _clean_event_id(value: object) -> int | str | None:
    if isinstance(value, int | str):
        return value
    return None


def _format_user_turn(turn: _UserTurn, limit: int) -> str:
    event_id, text, source = turn
    prefix = f'id={event_id}' if event_id is not None else source
    return f'{prefix}: {_clip_inline(text, limit)}'


def _turn_is_present(turn: _UserTurn, turns: list[_UserTurn]) -> bool:
    key = _turn_key(turn)
    return any(_turn_key(candidate) == key for candidate in turns)


def _turn_key(turn: _UserTurn) -> tuple[str, str]:
    event_id, text, _source = turn
    return (str(event_id or ''), text)


def _clip_inline(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + '...'


def _recent_tail_summary(events: list[Event]) -> str:
    lines: list[str] = []
    for event in reversed(events):
        if isinstance(event, MessageAction):
            continue
        event_id = getattr(event, 'id', '?')
        label = type(event).__name__
        detail = _event_detail(event)
        if not detail:
            continue
        lines.append(f'- {label} id={event_id}: {detail}')
        if len(lines) >= 10:
            break
    return '\n'.join(reversed(lines))


def _operational_checkpoint(canonical: CanonicalTaskState) -> str:
    lines: list[str] = []
    if canonical.next_action:
        lines.append(f'Next action: {canonical.next_action}')
    if canonical.implementation_checkpoint:
        lines.append(f'Checkpoint: {canonical.implementation_checkpoint}')
    if canonical.active_files:
        lines.append('Active files: ' + ', '.join(canonical.active_files[-10:]))
    if canonical.task_plan:
        lines.append('Current task tracker:')
        for item in canonical.task_plan[-8:]:
            detail = f'- [{item.status}] {item.description}'
            if item.result:
                detail += f' -> {item.result}'
            lines.append(detail)
    return '\n'.join(lines)


def _event_detail(event: Event) -> str:
    for attr in ('command', 'path', 'session_id', 'content', 'thought', 'message'):
        value = getattr(event, attr, None)
        if isinstance(value, str) and value.strip():
            return ' '.join(value.strip().split())[:180]
    return ''


def _active_status(canonical: CanonicalTaskState) -> str:
    lines: list[str] = []
    if canonical.background_tasks:
        lines.append('Pending background tasks:')
        for task in canonical.background_tasks[-4:]:
            session = task.session_id or 'unknown session'
            lines.append(f'- {session}: {task.command} -> {task.next_action}')
    return '\n'.join(lines)


def _restore_hints(
    *,
    state: State | None,
    include_latest_directive: bool = True,
) -> str:
    snapshot = load_snapshot(state=state)
    if not snapshot:
        return ''
    lines: list[str] = []
    latest = str(snapshot.get('latest_directive', '')).strip()
    if latest and include_latest_directive:
        lines.append(f'Latest directive before compaction: {latest[:240]}')
    tests = snapshot.get('test_results')
    if isinstance(tests, list) and tests:
        latest_test = next(
            (item for item in reversed(tests) if isinstance(item, dict)), None
        )
        if latest_test:
            lines.append(
                'Last test before compaction: '
                f'{str(latest_test.get("status", "?")).upper()} '
                f'(exit={latest_test.get("exit_code")}): '
                f'{str(latest_test.get("command", ""))[:180]}'
            )
    tasks = snapshot.get('background_tasks')
    if isinstance(tasks, list) and tasks:
        lines.append('Background tasks before compaction:')
        for task in tasks[-3:]:
            if isinstance(task, dict):
                lines.append(
                    f'- {task.get("session_id", "unknown")}: '
                    f'{str(task.get("next_action", "terminal_read"))[:160]}'
                )
    errors = snapshot.get('recent_errors')
    if isinstance(errors, list) and errors:
        lines.append(f'Recent error: {str(errors[-1])[:240]}')
    return '\n'.join(lines)


def _bounded_section(title: str, body: str, limit: int) -> str:
    text = f'<{title.upper().replace(" ", "_")}>\n{body.strip()}\n</{title.upper().replace(" ", "_")}>'
    if len(text) <= limit:
        return text
    return text[: limit - 36].rstrip() + '\n... (section truncated)'


def _assemble_sections(
    sections: list[tuple[str, str]],
    char_budget: int,
) -> tuple[str, dict[str, int]]:
    selected: list[tuple[str, str]] = []
    lengths: dict[str, int] = {}
    for name, body in sections:
        candidate = _render_packet([*selected, (name, body)])
        if len(candidate) > char_budget:
            remaining = char_budget - len(_render_packet(selected)) - 80
            if remaining <= 160:
                continue
            body = body[:remaining].rstrip() + '\n... (section truncated)'
        selected.append((name, body))
        lengths[name] = len(body)
    return _render_packet(selected), lengths


def _render_packet(sections: list[tuple[str, str]]) -> str:
    lines = [CONTEXT_PACKET_MARKER]
    lines.extend(body for _name, body in sections if body.strip())
    lines.append(CONTEXT_PACKET_MARKER)
    return '\n\n'.join(lines)


__all__ = [
    'CONTEXT_PACKET_MARKER',
    'ContextPacket',
    'build_context_packet',
    'build_context_packet_observation',
]
