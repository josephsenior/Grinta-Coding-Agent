"""Budgeted post-compact context re-injection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.constants import (
    DEFAULT_POST_COMPACT_FILE_PREVIEW_CHARS,
    DEFAULT_POST_COMPACT_MAX_FILES,
    DEFAULT_POST_COMPACT_TOKEN_BUDGET,
)

if TYPE_CHECKING:
    from backend.ledger.event import Event
    from backend.orchestration.state.state import State


def build_post_compact_attachment_text(
    state: State | None,
    events: list[Event],
) -> str:
    """Build a compact re-injection block for the first prompt after compaction.

    Task plan and acceptance criteria live in the per-turn ``<EXECUTION_CONTRACT>``
    context-packet section; this block only restores recently touched files.
    """
    if state is None:
        return ''

    parts: list[str] = ['<POST_COMPACT_RESTORE>']
    budget = DEFAULT_POST_COMPACT_TOKEN_BUDGET

    files_block = _recent_files_block(state, events, budget)
    if files_block:
        parts.append(files_block)

    parts.append('</POST_COMPACT_RESTORE>')
    body = '\n'.join(parts)
    if body == '<POST_COMPACT_RESTORE>\n</POST_COMPACT_RESTORE>':
        return ''
    return body


def _recent_files_block(state: State, events: list[Event], budget: int) -> str:
    paths: list[str] = []
    seen: set[str] = set()
    try:
        from backend.context.compactor.pre_condensation_snapshot import load_snapshot

        snapshot = load_snapshot(state=state)
        files = snapshot.get('files_touched', {}) if isinstance(snapshot, dict) else {}
        if isinstance(files, dict):
            for path in list(files.keys())[-DEFAULT_POST_COMPACT_MAX_FILES:]:
                if isinstance(path, str) and path not in seen:
                    seen.add(path)
                    paths.append(path)
    except Exception:
        paths = []
    if not paths:
        return ''
    lines = ['Recently touched files:']
    preview = DEFAULT_POST_COMPACT_FILE_PREVIEW_CHARS
    for path in paths[:DEFAULT_POST_COMPACT_MAX_FILES]:
        lines.append(f'- {path[:preview]}')
    block = '\n'.join(lines)
    return block[:budget] if len(block) > budget else block


__all__ = ['build_post_compact_attachment_text']
