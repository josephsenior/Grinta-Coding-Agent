"""Synthesized goal context for compaction — no verbatim user transcripts."""

from __future__ import annotations

import difflib
import re
from typing import TYPE_CHECKING, Any

from backend.context.render.execution_contract import build_execution_contract
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
    return build_execution_contract(
        state=state,
        snapshot=snapshot,
        max_chars=max_chars,
        only_open_tasks=True,
        show_empty_states=True,
    )


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


__all__ = [
    'build_goal_context_for_compaction',
    'strip_verbatim_user_echo',
]
