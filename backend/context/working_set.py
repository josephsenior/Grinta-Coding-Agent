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


def sync_snapshot_to_working_memory(snapshot: dict[str, Any] | None) -> list[str]:
    """Persist condensation snapshot facts into structured working memory."""
    if not snapshot:
        return []
    try:
        from backend.context.pre_condensation_snapshot import format_snapshot_for_injection
        from backend.engine.tools.working_memory import _load_memory, _save_memory
    except Exception:
        logger.debug('Working memory sync unavailable', exc_info=True)
        return []

    memory = _load_memory()
    updated: list[str] = []

    block = format_snapshot_for_injection(snapshot)
    if block and block.strip():
        memory['findings'] = block[: DEFAULT_DURABLE_CONTEXT_CHAR_BUDGET * 2]
        updated.append('findings')

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
        updated.append('blockers')

    decisions = snapshot.get('decisions', [])
    if isinstance(decisions, list) and decisions:
        memory['decisions'] = '\n'.join(str(d)[:300] for d in decisions[-8:])
        updated.append('decisions')

    approaches = snapshot.get('attempted_approaches', [])
    if isinstance(approaches, list) and approaches:
        failed = [
            a for a in approaches if isinstance(a, dict) and 'FAILED' in str(a.get('outcome', ''))
        ]
        if failed:
            lines = [
                f"✗ {a.get('type', '?')}: {str(a.get('detail', ''))[:120]}"
                for a in failed[-6:]
            ]
            existing = memory.get('hypothesis', '')
            hint = 'Do not retry these failed approaches:\n' + '\n'.join(lines)
            memory['hypothesis'] = f'{existing}\n\n{hint}'.strip() if existing else hint
            updated.append('hypothesis')

    if updated:
        memory['_last_updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
        memory['_snapshot_synced_at'] = memory['_last_updated']
        _save_memory(memory)
    return updated


def get_durable_context_block(
    events: list[Event] | None = None,
    *,
    char_budget: int = DEFAULT_DURABLE_CONTEXT_CHAR_BUDGET,
) -> str:
    """Build a compact durable context block for prompt protection."""
    parts: list[str] = [_WORKING_SET_MARKER]

    if events:
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

        snapshot = load_snapshot()
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


def build_working_set_observation(events: list[Event]) -> AgentCondensationObservation | None:
    """Create a synthetic condensation observation carrying durable context."""
    content = get_durable_context_block(events)
    if not content:
        return None
    return AgentCondensationObservation(content=content)


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
