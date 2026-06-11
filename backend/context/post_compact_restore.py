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

_RESTORE_MARKER = '<POST_COMPACT_RESTORE>'
_RESTORE_SECTION_CHAR_BUDGET = 1_200


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
    *,
    state: object | None = None,
) -> str:
    parts: list[str] = [_RESTORE_MARKER]

    pytest_summary = extract_latest_pytest_summary(history)
    if pytest_summary:
        _append_clipped(parts, f'Latest pytest: {pytest_summary}')

    snapshot = load_snapshot(state=state)  # type: ignore[arg-type]
    parts.extend(_extract_snapshot_sections(snapshot))
    parts.extend(_extract_restored_files(snapshot, preserved_tail))

    parts.append('</POST_COMPACT_RESTORE>')
    block = '\n\n'.join(parts)
    budget_chars = DEFAULT_POST_COMPACT_TOKEN_BUDGET * 4
    if len(block) > budget_chars:
        block = block[: budget_chars - 60] + '\n... (post-compact restore truncated)\n'
    return block


def _append_clipped(parts: list[str], text: str) -> None:
    if len(text) > _RESTORE_SECTION_CHAR_BUDGET:
        text = (
            text[: _RESTORE_SECTION_CHAR_BUDGET - 32].rstrip()
            + '\n... (section clipped)'
        )
    parts.append(text)


def _extract_snapshot_sections(snapshot: dict | None) -> list[str]:
    sections: list[str] = []
    if not snapshot:
        return sections
    runtime = snapshot.get('runtime')
    if isinstance(runtime, dict):
        iteration = runtime.get('iteration')
        if iteration is not None:
            sections.append(f'Resume at iteration: {iteration}')
    latest_directive = str(snapshot.get('latest_directive', '')).strip()
    if latest_directive:
        sections.append(f'Latest directive: {latest_directive[:300]}')
    test_results = snapshot.get('test_results')
    if isinstance(test_results, list) and test_results:
        latest = test_results[-1]
        if isinstance(latest, dict):
            status = latest.get('status', '?')
            command = str(latest.get('command', ''))[:120]
            sections.append(f'Last test run: {status} — {command}')
    background_tasks = snapshot.get('background_tasks')
    if isinstance(background_tasks, list) and background_tasks:
        for task in background_tasks[-2:]:
            if not isinstance(task, dict):
                continue
            session_id = str(task.get('session_id', '')).strip() or 'unknown session'
            next_action = str(task.get('next_action', 'terminal_read'))[:150]
            sections.append(
                f'Pending background task: {session_id}; next action: {next_action}'
            )
    recent_errors = snapshot.get('recent_errors')
    if isinstance(recent_errors, list) and recent_errors:
        sections.append('Recent blocker: ' + str(recent_errors[-1])[:250])
    return sections


def _extract_restored_files(
    snapshot: dict | None, preserved_tail: list[Event]
) -> list[str]:
    files = snapshot.get('files_touched', {}) if isinstance(snapshot, dict) else {}
    if not isinstance(files, dict):
        return []
    tail_contents = _tail_content_set(preserved_tail)
    parts: list[str] = []
    restored_files = 0
    prioritized = _prioritized_file_paths(files)
    for path in prioritized:
        if restored_files >= DEFAULT_POST_COMPACT_MAX_FILES:
            break
        if not isinstance(path, str) or not path:
            continue
        if path in tail_contents:
            continue
        preview = _read_file_preview(
            path, max_chars=DEFAULT_POST_COMPACT_FILE_PREVIEW_CHARS
        )
        if preview:
            parts.append(f'File: {path}\n```\n{preview}\n```')
            restored_files += 1
    return parts


def _prioritized_file_paths(files: dict) -> list[str]:
    edited: list[str] = []
    read_only: list[str] = []
    for path, info in reversed(list(files.items())):
        if not isinstance(path, str) or not path:
            continue
        if isinstance(info, dict) and (
            info.get('type') == 'edit' or info.get('action') in {'edit', 'write'}
        ):
            edited.append(path)
        else:
            read_only.append(path)
    return [*edited, *read_only]


def _tail_content_set(events: list[Event]) -> set[str]:
    return {
        getattr(event, 'content', '')
        for event in events
        if isinstance(getattr(event, 'content', ''), str)
        and getattr(event, 'content', '')
    }


def inject_post_compact_restore(
    events: list[Event],
    history: list[Event],
    *,
    just_compacted: bool = False,
    state: object | None = None,
) -> list[Event]:
    """Re-inject pytest, file, and task context after compaction."""
    if not just_compacted or not events:
        return events
    if _has_existing_restore(events):
        return events
    block = _build_restore_block(history, events, state=state)
    if (
        not block.strip()
        or block == '<POST_COMPACT_RESTORE>\n\n</POST_COMPACT_RESTORE>'
    ):
        return events
    if (
        estimate_events_tokens(events) + len(block) // 4
        > DEFAULT_POST_COMPACT_TOKEN_BUDGET * 2
    ):
        logger.debug('Skipping post-compact restore: would exceed budget')
        return events
    observation = AgentCondensationObservation(content=block)
    logger.info('Injected post-compact restore block (%d chars)', len(block))
    return [observation, *events]


def _has_existing_restore(events: list[Event]) -> bool:
    for event in events:
        content = getattr(event, 'content', None)
        if isinstance(content, str) and _RESTORE_MARKER in content:
            return True
    return False


__all__ = ['inject_post_compact_restore']
