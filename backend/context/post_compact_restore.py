"""Post-compaction context restoration (Layer 7)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from backend.context.pre_condensation_snapshot import load_snapshot
from backend.context.prompt_window import estimate_events_tokens
from backend.context.tool_result_storage import extract_latest_pytest_summary
from backend.core.constants import (
    DEFAULT_POST_COMPACT_FILE_PREVIEW_CHARS,
    DEFAULT_POST_COMPACT_MAX_FILES,
    DEFAULT_POST_COMPACT_TOKEN_BUDGET,
)
from backend.core.logger import app_logger as logger
from backend.ledger.event import Event
from backend.ledger.observation.agent import AgentCondensationObservation

if TYPE_CHECKING:
    pass


def _tail_event_ids(events: list[Event]) -> set[int]:
    ids: set[int] = set()
    for event in events:
        event_id = getattr(event, 'id', None)
        if isinstance(event_id, int):
            ids.add(event_id)
    return ids


def _read_file_preview(path: str, *, max_chars: int) -> str | None:
    try:
        resolved = Path(path)
        if not resolved.is_file():
            return None
        text = resolved.read_text(encoding='utf-8', errors='replace')
        if len(text) <= max_chars:
            return text
        half = max_chars // 2
        return (
            text[:half]
            + f'\n\n[... {len(text):,} chars truncated ...]\n\n'
            + text[-half:]
        )
    except OSError:
        return None


def _build_restore_block(
    history: list[Event],
    preserved_tail: list[Event],
) -> str:
    parts: list[str] = ['<POST_COMPACT_RESTORE>']

    pytest_summary = extract_latest_pytest_summary(history)
    if pytest_summary:
        parts.append(f'Latest pytest: {pytest_summary}')

    snapshot = load_snapshot()
    if snapshot:
        runtime = snapshot.get('runtime')
        if isinstance(runtime, dict):
            iteration = runtime.get('iteration')
            if iteration is not None:
                parts.append(f'Resume at iteration: {iteration}')
        test_results = snapshot.get('test_results')
        if isinstance(test_results, list) and test_results:
            latest = test_results[-1]
            if isinstance(latest, dict):
                status = latest.get('status', '?')
                command = str(latest.get('command', ''))[:120]
                parts.append(f'Last test run: {status} — {command}')

    tail_ids = _tail_event_ids(preserved_tail)
    files = snapshot.get('files_touched', {}) if isinstance(snapshot, dict) else {}
    if isinstance(files, dict):
        restored_files = 0
        for path in reversed(list(files.keys())):
            if restored_files >= DEFAULT_POST_COMPACT_MAX_FILES:
                break
            if not isinstance(path, str) or not path:
                continue
            if any(
                isinstance(getattr(event, 'content', ''), str)
                and path in getattr(event, 'content', '')
                for event in preserved_tail
            ):
                continue
            preview = _read_file_preview(
                path, max_chars=DEFAULT_POST_COMPACT_FILE_PREVIEW_CHARS
            )
            if preview:
                parts.append(f'File: {path}\n```\n{preview}\n```')
                restored_files += 1

    parts.append('</POST_COMPACT_RESTORE>')
    block = '\n\n'.join(parts)
    budget_chars = DEFAULT_POST_COMPACT_TOKEN_BUDGET * 4
    if len(block) > budget_chars:
        block = block[: budget_chars - 60] + '\n... (post-compact restore truncated)\n'
    return block


def inject_post_compact_restore(
    events: list[Event],
    history: list[Event],
    *,
    just_compacted: bool = False,
) -> list[Event]:
    """Re-inject pytest, file, and task context after compaction."""
    if not just_compacted or not events:
        return events
    block = _build_restore_block(history, events)
    if not block.strip() or block == '<POST_COMPACT_RESTORE>\n\n</POST_COMPACT_RESTORE>':
        return events
    if estimate_events_tokens(events) + len(block) // 4 > DEFAULT_POST_COMPACT_TOKEN_BUDGET * 2:
        logger.debug('Skipping post-compact restore: would exceed budget')
        return events
    observation = AgentCondensationObservation(content=block)
    logger.info('Injected post-compact restore block (%d chars)', len(block))
    return [observation, *events]


__all__ = ['inject_post_compact_restore']
