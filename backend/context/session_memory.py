"""Continuous session memory substrate for unified context compaction."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.context.pre_condensation_snapshot import (
    extract_snapshot,
    format_snapshot_for_injection,
)
from backend.context.prompt_window import estimate_events_tokens
from backend.core.constants import (
    DEFAULT_SESSION_MEMORY_INIT_TOKENS,
    DEFAULT_SESSION_MEMORY_UPDATE_TOKENS,
    DEFAULT_SESSION_MEMORY_UPDATE_TOOL_CALLS,
)
from backend.core.logger import app_logger as logger
from backend.ledger.observation import Observation

if TYPE_CHECKING:
    from backend.ledger.event import Event
    from backend.orchestration.state.state import State

SESSION_MEMORY_FILENAME = 'session_memory.md'
_PIPELINE_STATE_KEY = 'context_pipeline_state'


def _session_memory_path(state: State | None = None) -> Path:
    from backend.context.session_context import scoped_agent_path

    return scoped_agent_path('session_memory', '.md', state=state)


def _pipeline_state(state: State | None) -> dict[str, Any]:
    if state is None:
        return {}
    extra = getattr(state, 'extra_data', None)
    if not isinstance(extra, dict):
        return {}
    raw = extra.get(_PIPELINE_STATE_KEY)
    return raw if isinstance(raw, dict) else {}


def _set_pipeline_state(state: State, updates: dict[str, Any]) -> None:
    current = dict(_pipeline_state(state))
    current.update(updates)
    state.set_extra(_PIPELINE_STATE_KEY, current, source='SessionMemoryWriter')


def _read_metadata(content: str) -> dict[str, Any]:
    if not content.startswith('---\n'):
        return {}
    end = content.find('\n---\n', 4)
    if end < 0:
        return {}
    try:
        block = content[4:end]
        meta: dict[str, Any] = {}
        for line in block.splitlines():
            if ':' not in line:
                continue
            key, value = line.split(':', 1)
            meta[key.strip()] = value.strip()
        return meta
    except Exception:
        return {}


def _format_session_memory(snapshot: dict[str, Any], *, last_event_id: int | None) -> str:
    body = format_snapshot_for_injection(snapshot)
    if not body.strip():
        body = '_No structured facts extracted yet._'
    meta_lines = [
        '---',
        f'last_updated: {time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}',
    ]
    if last_event_id is not None:
        meta_lines.append(f'last_summarized_event_id: {last_event_id}')
    meta_lines.append('---')
    return '\n'.join(meta_lines) + '\n\n# Session Memory\n\n' + body


def load_session_memory(*, state: State | None = None) -> str:
    """Return the current session memory markdown, or empty string."""
    path = _session_memory_path(state)
    if not path.is_file():
        return ''
    try:
        return path.read_text(encoding='utf-8')
    except OSError:
        logger.debug('Failed to read session memory', exc_info=True)
        return ''


def get_content_for_compaction(*, state: State | None = None) -> str:
    """Return session memory body suitable for compaction summaries."""
    content = load_session_memory(state=state)
    if not content:
        return ''
    if content.startswith('---\n'):
        end = content.find('\n---\n', 4)
        if end >= 0:
            return content[end + 5 :].strip()
    return content.strip()


def session_memory_exists(*, state: State | None = None) -> bool:
    path = _session_memory_path(state)
    return path.is_file() and path.stat().st_size > 0


def _count_tool_calls_since(events: list[Event], since_id: int | None) -> int:
    count = 0
    for event in events:
        event_id = getattr(event, 'id', None)
        if since_id is not None and isinstance(event_id, int) and event_id <= since_id:
            continue
        if isinstance(event, Observation):
            count += 1
    return count


def _should_skip_during_condensation_loop(state: State | None) -> bool:
    """Skip expensive session-memory writes during condensation-only loops."""
    pipe = _pipeline_state(state)
    if pipe.get('consecutive_condensation_steps', 0) >= 1:
        return True
    if pipe.get('skip_compaction_until_event_id') is not None:
        return True
    return False


def maybe_update(
    state: State | None,
    events: list[Event],
    *,
    llm_config: object | None = None,
) -> bool:
    """Update session_memory.md when token or tool-call thresholds are crossed."""
    from backend.context.session_context import bind_session_context

    bind_session_context(state=state)
    if not events:
        return False
    if _should_skip_during_condensation_loop(state):
        return False
    estimated = estimate_events_tokens(events)
    pipe = _pipeline_state(state)
    last_event_id = pipe.get('last_session_memory_event_id')
    if not isinstance(last_event_id, int):
        last_event_id = None
    last_tokens = pipe.get('last_session_memory_tokens')
    if not isinstance(last_tokens, int):
        last_tokens = 0
    tool_calls = _count_tool_calls_since(events, last_event_id)
    tokens_delta = max(0, estimated - last_tokens)

    should_init = (
        not session_memory_exists(state=state) and estimated >= DEFAULT_SESSION_MEMORY_INIT_TOKENS
    )
    should_update = session_memory_exists(state=state) and (
        tokens_delta >= DEFAULT_SESSION_MEMORY_UPDATE_TOKENS
        or tool_calls >= DEFAULT_SESSION_MEMORY_UPDATE_TOOL_CALLS
    )
    if not (should_init or should_update):
        return False

    snapshot = extract_snapshot(events)
    latest_id = getattr(events[-1], 'id', None)
    last_summarized = latest_id if isinstance(latest_id, int) else last_event_id
    markdown = _format_session_memory(snapshot, last_event_id=last_summarized)
    path = _session_memory_path(state)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding='utf-8')
    except OSError:
        logger.debug('Failed to write session memory', exc_info=True)
        return False

    if state is not None:
        _set_pipeline_state(
            state,
            {
                'last_session_memory_event_id': last_summarized,
                'last_session_memory_tokens': estimated,
                'last_session_memory_updated_at': time.time(),
            },
        )
    try:
        from backend.context.canonical_state import (
            reduce_snapshot_into_state,
            save_canonical_state,
        )

        canonical = reduce_snapshot_into_state(
            snapshot,
            latest_event_id=last_summarized,
            source='session_memory',
            persist_state=state,
        )
        save_canonical_state(canonical, state=state)
    except Exception:
        logger.debug('Session memory canonical-state sync failed', exc_info=True)
    try:
        from backend.context.working_set import sync_snapshot_to_working_memory

        sync_snapshot_to_working_memory(snapshot)
    except Exception:
        logger.debug('Session memory working-set sync failed', exc_info=True)
    logger.info(
        'Session memory updated (%d events, ~%d tokens, tool_calls_since=%d)',
        len(events),
        estimated,
        tool_calls,
    )
    return True


def build_compaction_summary(
    *,
    include_snapshot: bool = True,
    state: State | None = None,
) -> str:
    """Build a summary from session memory and optional live snapshot."""
    parts: list[str] = []
    memory = get_content_for_compaction(state=state)
    if memory:
        parts.append(memory)
    if include_snapshot:
        try:
            from backend.context.pre_condensation_snapshot import load_snapshot

            snapshot = load_snapshot(state=state)
            if snapshot:
                block = format_snapshot_for_injection(snapshot)
                if block and block not in memory:
                    parts.append(block)
        except Exception:
            logger.debug('Snapshot merge for compaction summary failed', exc_info=True)
    return '\n\n'.join(part for part in parts if part.strip())


def metadata(*, state: State | None = None) -> dict[str, Any]:
    content = load_session_memory(state=state)
    if not content:
        return {}
    meta = _read_metadata(content)
    path = _session_memory_path(state)
    if path.is_file():
        meta['path'] = str(path)
        meta['size_bytes'] = path.stat().st_size
    return meta


__all__ = [
    'SESSION_MEMORY_FILENAME',
    'build_compaction_summary',
    'get_content_for_compaction',
    'load_session_memory',
    'maybe_update',
    'metadata',
    'session_memory_exists',
]
