"""Synthesized goal context for compaction — no verbatim user transcripts."""

from __future__ import annotations

import difflib
import re
from typing import TYPE_CHECKING, Any

from backend.core.constants import DEFAULT_GOAL_CONTEXT_MAX_CHARS
from backend.core.logging.logger import app_logger as logger

if TYPE_CHECKING:
    pass

_USER_GOAL_HEADER = '## USER GOAL'


def build_goal_context_for_compaction(
    state: object | None = None,
    snapshot: dict[str, Any] | None = None,
    *,
    max_chars: int = DEFAULT_GOAL_CONTEXT_MAX_CHARS,
) -> str:
    """Build a compact goal contract from canonical state, task tracker, and AC."""
    lines: list[str] = []

    canonical_block = _canonical_goal_lines(state)
    lines.extend(canonical_block)

    if snapshot is None and state is not None:
        snapshot = _load_snapshot_safe(state)
    if isinstance(snapshot, dict):
        lines.extend(_task_plan_lines(snapshot.get('task_plan')))

    lines.extend(_acceptance_criteria_lines())

    if not lines:
        return ''

    body = '\n'.join(lines).strip()
    if len(body) > max_chars:
        body = body[: max_chars - 3].rstrip() + '...'
    return body


def strip_verbatim_user_echo(
    summary: str,
    *,
    state: object | None = None,
    snapshot: dict[str, Any] | None = None,
) -> str:
    """Replace USER GOAL sections that echo raw user messages with synthesized goal."""
    if not summary or _USER_GOAL_HEADER not in summary:
        return summary

    if snapshot is None and state is not None:
        snapshot = _load_snapshot_safe(state)
    user_texts = _user_message_texts(snapshot)
    if not user_texts:
        return summary

    goal = _extract_section(summary, _USER_GOAL_HEADER)
    if not goal:
        return summary

    for raw in user_texts:
        if len(raw) < 40:
            continue
        ratio = difflib.SequenceMatcher(None, goal.lower(), raw.lower()).ratio()
        if ratio >= 0.8 or raw.strip() in goal:
            synthesized = build_goal_context_for_compaction(
                state=state, snapshot=snapshot
            )
            if not synthesized:
                continue
            replacement = f'{_USER_GOAL_HEADER}\n{synthesized}'
            logger.info(
                'Compaction summary USER GOAL echoed verbatim user text (%.0f%%); '
                'replacing with synthesized goal context',
                ratio * 100,
            )
            return summary.replace(
                f'{_USER_GOAL_HEADER}\n{goal}',
                replacement,
                1,
            )
    return summary


def _load_snapshot_safe(state: object) -> dict[str, Any] | None:
    try:
        from backend.context.compactor.pre_condensation_snapshot import load_snapshot

        raw = load_snapshot(state=state)  # type: ignore[arg-type]
        return raw if isinstance(raw, dict) else None
    except Exception:
        logger.debug('Failed to load snapshot for goal context', exc_info=True)
        return None


def _canonical_goal_lines(state: object | None) -> list[str]:
    if state is None:
        return []
    try:
        from backend.context.canonical_state import load_canonical_state

        canonical = load_canonical_state(state=state)  # type: ignore[arg-type]
    except Exception:
        return []

    lines: list[str] = []
    objective = str(getattr(canonical, 'objective', '') or '').strip()
    if objective:
        lines.append(f'- Objective: {_cap_line(objective, 240)}')
    directive = str(getattr(canonical, 'latest_directive', '') or '').strip()
    if directive and directive != objective:
        lines.append(f'- Latest directive: {_cap_line(directive, 200)}')
    next_action = str(getattr(canonical, 'next_action', '') or '').strip()
    if next_action:
        lines.append(f'- Next action: {_cap_line(next_action, 200)}')
    return lines


def _task_plan_lines(task_plan: object) -> list[str]:
    if not isinstance(task_plan, dict):
        return []
    tasks = task_plan.get('tasks')
    if not isinstance(tasks, list) or not tasks:
        return []
    lines = ['- Active scope:']
    for task in tasks[:8]:
        if not isinstance(task, dict):
            continue
        status = str(task.get('status', '') or '').strip().lower()
        if status in {'done', 'completed', 'cancelled'}:
            continue
        desc = str(task.get('description', '') or '').strip()
        if desc:
            lines.append(f'  - [{status or "?"}] {_cap_line(desc, 160)}')
    return lines if len(lines) > 1 else []


def _acceptance_criteria_lines() -> list[str]:
    try:
        from backend.core.criteria import AcceptanceCriteriaStore

        criteria = AcceptanceCriteriaStore().load_from_file()
    except Exception:
        return []
    if not criteria:
        return []
    lines = ['- Acceptance gates:']
    for item in criteria[:10]:
        if not isinstance(item, dict):
            continue
        assertion = str(item.get('assertion', '') or '').strip()
        if not assertion:
            continue
        evidence = str(item.get('evidence', '') or '').strip()
        suffix = f' (evidence: {_cap_line(evidence, 80)})' if evidence else ''
        lines.append(f'  - {_cap_line(assertion, 180)}{suffix}')
    return lines if len(lines) > 1 else []


def _user_message_texts(snapshot: dict[str, Any] | None) -> list[str]:
    if not isinstance(snapshot, dict):
        return []
    messages = snapshot.get('user_messages')
    if not isinstance(messages, list):
        return []
    texts: list[str] = []
    for item in messages:
        if isinstance(item, dict):
            text = str(item.get('text', '') or '').strip()
            if text:
                texts.append(text)
    return texts


def _extract_section(text: str, header: str) -> str:
    pattern = re.compile(
        rf'^{re.escape(header)}\s*\n(.*?)(?=^##\s|\Z)',
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    return match.group(1).strip() if match else ''


def _cap_line(text: str, limit: int) -> str:
    cleaned = ' '.join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + '...'


__all__ = [
    'build_goal_context_for_compaction',
    'strip_verbatim_user_echo',
]
