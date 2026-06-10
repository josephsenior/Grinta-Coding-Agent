"""Durable working-set context for coding-agent continuity.

Keeps task state, test results, and condensation recovery available across
turns instead of one-shot snapshot injection.
"""

from __future__ import annotations

import time
from typing import Any

from backend.core.constants import DEFAULT_DURABLE_CONTEXT_CHAR_BUDGET
from backend.core.logger import app_logger as logger
from backend.ledger.action import MessageAction
from backend.ledger.event import Event, EventSource
from backend.ledger.observation.agent import AgentCondensationObservation

_WORKING_SET_MARKER = '<DURABLE_WORKING_SET>'


def _sync_findings_block(memory: dict[str, Any], snapshot: dict[str, Any]) -> str | None:
    from backend.context.pre_condensation_snapshot import format_snapshot_for_injection

    block = format_snapshot_for_injection(snapshot)
    if block and block.strip():
        memory['findings'] = block[: DEFAULT_DURABLE_CONTEXT_CHAR_BUDGET * 2]
        return 'findings'
    return None


def _sync_test_results(memory: dict[str, Any], snapshot: dict[str, Any]) -> str | None:
    test_lines: list[str] = []
    for result in snapshot.get('test_results', [])[-5:]:
        if not isinstance(result, dict):
            continue
        status = str(result.get('status', '?')).upper()
        command = str(result.get('command', ''))[:120]
        exit_code = result.get('exit_code')
        output = str(result.get('output', '')).strip()
        line = f'{status} (exit={exit_code}): {command}'
        if output:
            line += f'\n  {output[:200]}'
        test_lines.append(line)
    if test_lines:
        memory['blockers'] = 'Recent test results:\n' + '\n'.join(test_lines)
        return 'blockers'
    return None


def _sync_decisions(memory: dict[str, Any], snapshot: dict[str, Any]) -> str | None:
    decisions = snapshot.get('decisions', [])
    if isinstance(decisions, list) and decisions:
        memory['decisions'] = '\n'.join(str(d)[:300] for d in decisions[-8:])
        return 'decisions'
    return None


def _sync_failed_approaches(memory: dict[str, Any], snapshot: dict[str, Any]) -> str | None:
    approaches = snapshot.get('attempted_approaches', [])
    if not (isinstance(approaches, list) and approaches):
        return None
    failed = [
        a for a in approaches if isinstance(a, dict) and 'FAILED' in str(a.get('outcome', ''))
    ]
    if not failed:
        return None
    lines = [
        f"✗ {a.get('type', '?')}: {str(a.get('detail', ''))[:120]}"
        for a in failed[-6:]
    ]
    existing = memory.get('hypothesis', '')
    hint = 'Do not retry these failed approaches:\n' + '\n'.join(lines)
    memory['hypothesis'] = f'{existing}\n\n{hint}'.strip() if existing else hint
    return 'hypothesis'


def sync_snapshot_to_working_memory(snapshot: dict[str, Any] | None) -> list[str]:
    """Persist condensation snapshot facts into structured working memory."""
    if not snapshot:
        return []
    try:
        from backend.context.pre_condensation_snapshot import format_snapshot_for_injection  # noqa: F401
        from backend.engine.tools.working_memory import _load_memory, _save_memory
    except Exception:
        logger.debug('Working memory sync unavailable', exc_info=True)
        return []

    memory = _load_memory()
    updated: list[str] = []

    for sync_fn in (
        _sync_findings_block,
        _sync_test_results,
        _sync_decisions,
        _sync_failed_approaches,
    ):
        result = sync_fn(memory, snapshot)
        if result:
            updated.append(result)

    if updated:
        memory['_last_updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
        memory['_snapshot_synced_at'] = memory['_last_updated']
        _save_memory(memory)
    return updated


def _session_has_durable_artifacts(*, state: object | None = None) -> bool:
    """True when this session has persisted snapshot or working-memory data on disk."""
    try:
        from backend.context.pre_condensation_snapshot import load_snapshot
        from backend.engine.tools.working_memory import _load_memory

        if load_snapshot(state=state):  # type: ignore[arg-type]
            return True
        memory = _load_memory()
        return any(
            isinstance(value, str) and value.strip()
            for key, value in memory.items()
            if not str(key).startswith('_')
        )
    except Exception:
        logger.debug('Durable artifact probe failed', exc_info=True)
        return False


def get_durable_context_block(
    events: list[Event] | None = None,
    *,
    char_budget: int = DEFAULT_DURABLE_CONTEXT_CHAR_BUDGET,
    state: object | None = None,
    include_task_from_history: bool = False,
) -> str:
    """Build a compact durable context block for prompt protection."""
    parts: list[str] = [_WORKING_SET_MARKER]

    if events and include_task_from_history:
        from backend.context.tool_result_storage import extract_latest_pytest_summary
        from backend.ledger.action import MessageAction

        first_user = _first_user_message(events)
        last_user = _last_user_message(events)
        if first_user:
            parts.append(f'Task: {first_user[:600]}')
        if last_user and last_user != first_user:
            parts.append(f'Latest directive: {last_user[:400]}')
        pytest_summary = extract_latest_pytest_summary(events)
        if pytest_summary:
            parts.append(f'Latest pytest: {pytest_summary}')

    try:
        from backend.context.pre_condensation_snapshot import (
            format_snapshot_for_injection,
            load_snapshot,
        )
        from backend.engine.tools.working_memory import get_working_memory_prompt_block

        snapshot = load_snapshot(state=state)  # type: ignore[arg-type]
        if snapshot:
            snapshot_block = format_snapshot_for_injection(snapshot)
            if snapshot_block:
                parts.append(snapshot_block)
        wm_block = get_working_memory_prompt_block(char_budget=char_budget // 2)
        if wm_block:
            parts.append(wm_block)
    except Exception:
        logger.debug('Durable context assembly failed', exc_info=True)

    parts.append(_WORKING_SET_MARKER)
    if len(parts) <= 2:
        return ''
    block = '\n'.join(parts)
    if len(block) > char_budget:
        block = block[: char_budget - 40] + '\n... (working set truncated)\n' + _WORKING_SET_MARKER
    return block


def build_working_set_observation(
    events: list[Event],
    *,
    state: object | None = None,
) -> AgentCondensationObservation | None:
    """Create a durable working-set observation after compaction or restore.

    Fresh sessions with no compaction history and no persisted artifacts must
    not inject this — it is rendered through the condensation observation path
    and would falsely tell the model that context was already condensed.
    """
    from backend.context.compact_boundary import find_last_condensation_action

    has_compacted = find_last_condensation_action(events) is not None
    if not has_compacted and not _session_has_durable_artifacts(state=state):
        return None

    content = get_durable_context_block(
        events,
        state=state,
        include_task_from_history=has_compacted,
    )
    if not content:
        return None
    return AgentCondensationObservation(content=content, is_working_set=True)


def _first_user_message(events: list[Event]) -> str | None:
    for event in events:
        if isinstance(event, MessageAction) and event.source == EventSource.USER:
            text = (event.content or '').strip()
            if text:
                return text
    return None


def _last_user_message(events: list[Event]) -> str | None:
    for event in reversed(events):
        if isinstance(event, MessageAction) and event.source == EventSource.USER:
            text = (event.content or '').strip()
            if text:
                return text
    return None


__all__ = [
    'build_working_set_observation',
    'get_durable_context_block',
    'sync_snapshot_to_working_memory',
]
