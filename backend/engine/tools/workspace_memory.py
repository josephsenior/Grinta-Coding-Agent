"""Workspace-scoped durable memory — curated facts that survive across sessions."""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from backend.engine.tools.lesson_store import lessons_are_similar, normalize_lesson_text

_MEMORY_QUERY_MAX_CHARS = 500

_WORKSPACE_MEMORY_FILE = 'workspace_memory.json'
_VALID_KINDS = frozenset(
    {
        'convention',
        'command',
        'architecture',
        'lesson',
        'strategy',
        'heuristic',
        'decision',
        'preference',
    }
)
_MAX_ENTRIES = 50
_DEFAULT_PROMPT_CHAR_BUDGET = 800
_DEFAULT_RANKED_ENTRIES = 8


def _memory_path() -> Path:
    from backend.core.workspace_resolution import workspace_agent_state_dir

    return workspace_agent_state_dir() / _WORKSPACE_MEMORY_FILE


def _load_store() -> dict[str, Any]:
    path = _memory_path()
    if not path.is_file():
        return {'entries': []}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(data, dict) and isinstance(data.get('entries'), list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {'entries': []}


def _save_store(store: dict[str, Any]) -> None:
    path = _memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding='utf-8')


def _normalize_entry(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get('kind', 'lesson')).strip().lower()
    key = str(raw.get('key', '')).strip()
    value = str(raw.get('value', '')).strip()
    if not key or not value:
        return None
    if kind not in _VALID_KINDS:
        kind = 'lesson'
    seen = raw.get('seen_count', 1)
    try:
        seen_count = max(1, int(seen))
    except (TypeError, ValueError):
        seen_count = 1
    return {
        'id': str(raw.get('id') or uuid.uuid4().hex[:12]),
        'kind': kind,
        'key': key,
        'value': value,
        'created': str(
            raw.get('created') or time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        ),
        'updated': str(
            raw.get('updated') or time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        ),
        'seen_count': seen_count,
    }


def list_entries() -> list[dict[str, Any]]:
    """Return normalized workspace memory entries."""
    store = _load_store()
    entries: list[dict[str, Any]] = []
    for raw in store.get('entries', []):
        entry = _normalize_entry(raw)
        if entry is not None:
            entries.append(entry)
    return entries


def _entry_tokens(text: str) -> set[str]:
    return {
        tok
        for tok in re.split(r'[^a-z0-9_]+', normalize_lesson_text(text))
        if len(tok) >= 3
    }


def _score_entry(entry: dict[str, Any], query: str | None) -> float:
    score = float(entry.get('seen_count', 1))
    updated = str(entry.get('updated', ''))
    if updated:
        score += 0.1
    if not query:
        return score
    query_tokens = _entry_tokens(query)
    if not query_tokens:
        return score
    hay = ' '.join(
        (
            str(entry.get('key', '')),
            str(entry.get('value', '')),
            str(entry.get('kind', '')),
        )
    )
    entry_tokens = _entry_tokens(hay)
    overlap = len(query_tokens & entry_tokens)
    return score + overlap * 2.0


def rank_entries(
    query: str | None = None,
    *,
    max_entries: int = _DEFAULT_RANKED_ENTRIES,
) -> list[dict[str, Any]]:
    """Rank workspace entries for prompt injection or recall listing."""
    ranked = sorted(
        list_entries(),
        key=lambda entry: _score_entry(entry, query),
        reverse=True,
    )
    return ranked[: max(0, max_entries)]


def persist_entry(
    *,
    kind: str,
    key: str,
    value: str,
) -> tuple[bool, str]:
    """Persist a workspace memory entry with deduplication.

    Returns (inserted, message).
    """
    key = key.strip()
    value = value.strip()
    if not key or not value:
        return False, 'key and value are required for persist.'
    kind_norm = kind.strip().lower()
    if kind_norm not in _VALID_KINDS:
        kind_norm = 'lesson'

    store = _load_store()
    entries = [
        e for e in (_normalize_entry(raw) for raw in store.get('entries', [])) if e
    ]

    for entry in entries:
        same_key = entry['key'].casefold() == key.casefold()
        similar = lessons_are_similar(entry['value'], value)
        if same_key or similar:
            entry['seen_count'] = int(entry.get('seen_count', 1)) + 1
            entry['updated'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            if same_key or similar:
                entry['value'] = value
            store['entries'] = entries
            _save_store(store)
            return False, f"Updated existing workspace memory '{entry['key']}'."

    now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    entries.append(
        {
            'id': uuid.uuid4().hex[:12],
            'kind': kind_norm,
            'key': key,
            'value': value,
            'created': now,
            'updated': now,
            'seen_count': 1,
        }
    )
    if len(entries) > _MAX_ENTRIES:
        entries.sort(
            key=lambda e: (int(e.get('seen_count', 1)), str(e.get('updated', '')))
        )
        entries = entries[-_MAX_ENTRIES:]
    store['entries'] = entries
    _save_store(store)
    return True, f"Persisted workspace memory '{key}'."


def get_entry(key: str) -> dict[str, Any] | None:
    target = key.strip().casefold()
    if not target:
        return None
    for entry in list_entries():
        if entry['key'].casefold() == target:
            return entry
    return None


def memory_query_from_text(
    text: object, *, max_chars: int = _MEMORY_QUERY_MAX_CHARS
) -> str | None:
    """Normalize user task text for ranked workspace-memory injection."""
    normalized = str(text or '').strip()
    if not normalized:
        return None
    if len(normalized) > max_chars:
        return normalized[:max_chars]
    return normalized


def memory_query_from_events(
    events: list[Any],
    *,
    initial_user_action: object | None = None,
) -> str | None:
    """Derive a memory ranking query from the session's first user message."""
    if initial_user_action is not None:
        query = memory_query_from_text(getattr(initial_user_action, 'content', ''))
        if query:
            return query

    from backend.ledger.action import MessageAction
    from backend.ledger.event import EventSource

    for event in events:
        if not isinstance(event, MessageAction):
            continue
        if getattr(event, 'source', None) != EventSource.USER:
            continue
        query = memory_query_from_text(getattr(event, 'content', ''))
        if query:
            return query
    return None


def format_prompt_block(
    query: str | None = None,
    *,
    char_budget: int = _DEFAULT_PROMPT_CHAR_BUDGET,
) -> str:
    """Return a bounded workspace-memory block for system-prompt injection."""
    try:
        from backend.context.memory.project_memory import (
            ProjectMemoryService,
            migrate_legacy_memories,
        )

        # Automatically migrate legacy memories on first run
        migrate_legacy_memories()

        service = ProjectMemoryService()
        ranked = service.retrieve_relevant(query or '', limit=10)
        if not ranked:
            return ''

        lines = ['<WORKSPACE_MEMORY>', 'Durable workspace facts (ranked by relevance):']
        for entry in ranked:
            line = f'- [{entry.kind}] {entry.fact}'
            candidate = '\n'.join(lines + [line, '</WORKSPACE_MEMORY>'])
            if len(candidate) > char_budget:
                lines.append('... (additional workspace memory truncated)')
                break
            lines.append(line)

        if len(lines) == 2:
            return ''
        lines.append('</WORKSPACE_MEMORY>')
        return '\n'.join(lines)
    except Exception:
        return ''


__all__ = [
    'format_prompt_block',
    'get_entry',
    'list_entries',
    'memory_query_from_events',
    'memory_query_from_text',
    'persist_entry',
    'rank_entries',
]
