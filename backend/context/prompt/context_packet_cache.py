"""Fingerprinted cache for prompt-time context packet assembly."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.context.prompt.prompt_window import event_fingerprint
from backend.core.logging.logger import app_logger as logger

if TYPE_CHECKING:
    from backend.context.prompt.context_packet import ContextPacket
    from backend.ledger.event import Event
    from backend.orchestration.state.state import State


@dataclass
class _SessionPacketCache:
    key: str
    content: str
    section_lengths: dict[str, int]


_CACHES: dict[str, _SessionPacketCache] = {}


def clear_context_packet_cache(session_id: str | None = None) -> None:
    """Drop cached packet(s) after compaction or other history-shaping events."""
    if session_id:
        _CACHES.pop(session_id, None)
    else:
        _CACHES.clear()


def get_cached_context_packet(
    state: State | None,
    cache_key: str,
) -> ContextPacket | None:
    session_id = _session_id(state)
    if not session_id:
        return None
    entry = _CACHES.get(session_id)
    if entry is None or entry.key != cache_key:
        return None
    from backend.context.prompt.context_packet import ContextPacket

    logger.debug(
        'Context packet cache hit session=%s key=%s', session_id, cache_key[:12]
    )
    return ContextPacket(content=entry.content, section_lengths=entry.section_lengths)


def store_context_packet_cache(
    state: State | None,
    cache_key: str,
    packet: ContextPacket,
) -> None:
    session_id = _session_id(state)
    if not session_id:
        return
    _CACHES[session_id] = _SessionPacketCache(
        key=cache_key,
        content=packet.content,
        section_lengths=dict(packet.section_lengths),
    )


def compute_context_packet_cache_key(
    *,
    events: list[Event],
    history: list[Event],
    state: State | None,
    snapshot: dict[str, Any] | None,
    just_compacted: bool,
    char_budget: int,
) -> str:
    """Cheap fingerprint of all inputs that affect packet content."""
    parts = [
        f'history_tail={_history_tail_token(history)}',
        f'projected={_projected_events_token(events)}',
        f'tasks={_json_path_token(_task_tracker_path)}',
        f'criteria={_json_path_token(_acceptance_store_path)}',
        f'snapshot={_snapshot_token(snapshot, state)}',
        f'drain={_turn_drain_token(state)}',
        f'summary={_boundary_summary_token(history)}',
        f'just_compacted={int(just_compacted)}',
        f'budget={char_budget}',
    ]
    payload = '|'.join(parts)
    return hashlib.sha256(payload.encode('utf-8'), usedforsecurity=False).hexdigest()


def _session_id(state: State | None) -> str | None:
    if state is None:
        return None
    session_id = getattr(state, 'session_id', None)
    if isinstance(session_id, str) and session_id.strip():
        return session_id.strip()
    return None


def _history_tail_token(history: list[Event]) -> str:
    if not history:
        return 'empty'
    last = history[-1]
    event_id = getattr(last, 'id', None)
    return f'{type(last).__name__}:{event_id}:{len(history)}'


def _projected_events_token(events: list[Event]) -> str:
    if not events:
        return 'empty'
    tail = events[-12:]
    return ';'.join(event_fingerprint(event) for event in tail)


def _json_path_token(path_resolver: object) -> str:
    try:
        path = path_resolver()
        if not isinstance(path, Path):
            return 'missing'
        return _path_stamp(path)
    except Exception:
        return 'missing'


def _task_tracker_path() -> Path:
    from backend.core.task_tracker import TaskTracker

    return TaskTracker().path


def _acceptance_store_path() -> Path:
    from backend.core.criteria.acceptance_criteria_store import AcceptanceCriteriaStore

    return AcceptanceCriteriaStore().path


def _path_stamp(path: Path) -> str:
    if not path.exists():
        return f'missing:{path.name}'
    stat = path.stat()
    return f'{path.name}:{stat.st_mtime_ns}:{stat.st_size}'


def _snapshot_token(snapshot: dict[str, Any] | None, state: State | None) -> str:
    if isinstance(snapshot, dict) and snapshot:
        payload = repr(
            (
                snapshot.get('user_messages'),
                snapshot.get('task_plan'),
                snapshot.get('test_results'),
                snapshot.get('background_tasks'),
                snapshot.get('recent_errors'),
            )
        )
        digest = hashlib.sha256(
            payload.encode('utf-8', 'ignore'),
            usedforsecurity=False,
        ).hexdigest()[:16]
        return f'inline:{digest}'
    if state is None:
        return 'none'
    try:
        from backend.context.compactor.pre_condensation_snapshot import (
            _snapshot_staging_path,
        )

        path = _snapshot_staging_path(state=state)  # type: ignore[arg-type]
        if isinstance(path, Path):
            return _path_stamp(path)
    except Exception:
        logger.debug('Snapshot path stamp failed', exc_info=True)
    return 'none'


def _turn_drain_token(state: State | None) -> str:
    if state is None:
        return 'none'
    try:
        from backend.execution.utils.shell.background_turn_sync import (
            read_turn_drain_extras,
        )

        extras = read_turn_drain_extras(state)
        if not extras:
            return 'empty'
        parts = sorted(f'{key}:{len(value)}' for key, value in extras.items())
        digest = hashlib.sha256(
            '|'.join(parts).encode('utf-8', 'ignore'),
            usedforsecurity=False,
        ).hexdigest()[:16]
        return digest
    except Exception:
        return 'error'


def _boundary_summary_token(history: list[Event]) -> str:
    from backend.ledger.observation.agent import AgentCondensationObservation

    skip_markers = (
        '<CONTEXT_PACKET>',
        '<CANONICAL_TASK_STATE>',
        '<DURABLE_WORKING_SET>',
        '<COMPACT_SNAPSHOT>',
        '<POST_COMPACT_RESTORE>',
        '<RESTORED_CONTEXT>',
    )
    for event in reversed(history):
        if not isinstance(event, AgentCondensationObservation):
            continue
        content = (event.content or '').strip()
        if not content:
            continue
        if any(marker in content for marker in skip_markers):
            continue
        event_id = getattr(event, 'id', None)
        digest = hashlib.sha256(
            content.encode('utf-8', 'ignore'),
            usedforsecurity=False,
        ).hexdigest()[:16]
        return f'{event_id}:{digest}'
    return 'none'


__all__ = [
    'clear_context_packet_cache',
    'compute_context_packet_cache_key',
    'get_cached_context_packet',
    'store_context_packet_cache',
]
