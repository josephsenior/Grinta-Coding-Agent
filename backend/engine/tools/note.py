"""Persistent scratchpad tools for stable key-value memory.

This is the canonical home for flat scratchpad storage and prompt injection
helpers. Legacy modules may re-export these functions for compatibility.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from backend.core.constants import NOTE_TOOL_NAME, RECALL_TOOL_NAME
from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.common import create_tool_definition
from backend.ledger.action import AgentThinkAction

_NOTE_DESCRIPTION = (
    'Store a persistent note in your scratchpad. '
    'Notes are written to .app/agent_notes.json inside the workspace root '
    'and survive context condensation — use them to remember decisions, '
    'constraints, or interim findings across a long session.\n\n'
    "Examples: key='auth_decision', value='using JWT with 1-hour expiry'.\n"
    "          key='db_url',        value='postgres://localhost/myapp'."
)

_RECALL_DESCRIPTION = (
    'Retrieve a value from your persistent scratchpad.\n\n'
    'Pass a specific key to get one value, or key="all" to dump the entire scratchpad.'
)

_NOTES_RELPATH = os.path.join('.grinta', 'agent_notes.json')
_SCRATCHPAD_META_KEY = '__app_scratchpad_meta__'


def create_note_tool() -> ChatCompletionToolParam:
    """Create the persistent-note tool definition."""
    return create_tool_definition(
        name=NOTE_TOOL_NAME,
        description=_NOTE_DESCRIPTION,
        properties={
            'key': {
                'type': 'string',
                'description': (
                    'Short identifier for this note '
                    "(e.g. 'auth_decision', 'db_schema', 'test_command')."
                ),
            },
            'value': {
                'type': 'string',
                'description': 'The value to store. May be multi-line, any text.',
            },
        },
        required=['key', 'value'],
    )


def create_recall_tool() -> ChatCompletionToolParam:
    """Create the scratchpad-recall tool definition."""
    return create_tool_definition(
        name=RECALL_TOOL_NAME,
        description=_RECALL_DESCRIPTION,
        properties={
            'key': {
                'type': 'string',
                'description': 'The key to retrieve. Use "all" to list every stored note.',
            },
        },
        required=['key'],
    )


def _notes_path() -> Path:
    """Return the absolute path to the scratchpad JSON file."""
    from backend.core.workspace_resolution import require_effective_workspace_root

    return require_effective_workspace_root() / _NOTES_RELPATH


def _read_notes_blob() -> dict:
    """Load raw JSON object from disk, or {} if missing/corrupt."""
    p = _notes_path()
    if not p.exists():
        return {}
    try:
        with open(p, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _parse_notes_blob(raw: dict) -> tuple[dict[str, str], dict[str, float]]:
    """Split user notes from internal metadata; coerce timestamps to float."""
    blob = dict(raw)
    meta = blob.pop(_SCRATCHPAD_META_KEY, None)
    updated: dict[str, float] = {}
    if isinstance(meta, dict):
        u = meta.get('updated')
        if isinstance(u, dict):
            for k, v in u.items():
                if isinstance(k, str) and isinstance(v, (int, float)):
                    updated[k] = float(v)
    notes: dict[str, str] = {}
    for k, v in blob.items():
        if isinstance(v, str):
            notes[k] = v
    return notes, updated


def _write_notes_blob(notes: dict[str, str], updated: dict[str, float]) -> None:
    """Persist notes plus update timestamps."""
    p = _notes_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    out: dict = {**notes, _SCRATCHPAD_META_KEY: {'updated': updated}}
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2, ensure_ascii=False)


def _load_notes() -> dict[str, str]:
    """Load user-visible scratchpad keys only (no internal metadata)."""
    return _parse_notes_blob(_read_notes_blob())[0]


def scratchpad_entries_for_prompt() -> list[tuple[str, str]]:
    """Return (key, value) pairs for prompt injection: deduped, newest first."""
    notes, ts = _parse_notes_blob(_read_notes_blob())
    merged: dict[str, tuple[str, str, float]] = {}
    for k, v in notes.items():
        ks = k.strip()
        if not ks:
            continue
        t = float(ts.get(k, 0.0))
        cf = ks.casefold()
        prev = merged.get(cf)
        if prev is None or t >= prev[2]:
            merged[cf] = (ks, v, t)
    rows = list(merged.values())
    if rows and any(r[2] > 0.0 for r in rows):
        rows.sort(key=lambda r: r[2], reverse=True)
    else:
        rows.sort(key=lambda r: r[0].casefold())
    return [(r[0], r[1]) for r in rows]


def build_note_action(key: str, value: str) -> AgentThinkAction:
    """Persist key->value to the scratchpad."""
    notes, updated = _parse_notes_blob(_read_notes_blob())
    notes[key] = value
    updated[key] = time.time()
    _write_notes_blob(notes, updated)
    return AgentThinkAction(thought=f'[SCRATCHPAD] Noted [{key}]')


def build_recall_action(key: str) -> AgentThinkAction:
    """Retrieve key (or all keys) from the scratchpad."""
    notes = _load_notes()
    if key == 'all':
        body = (
            json.dumps(notes, indent=2, ensure_ascii=False)
            if notes
            else '(scratchpad is empty)'
        )
        return AgentThinkAction(thought=f'[SCRATCHPAD] All notes:\n{body}')
    if key in notes:
        return AgentThinkAction(thought=f'[SCRATCHPAD] [{key}] = {notes[key]!r}')
    return AgentThinkAction(thought=f'[SCRATCHPAD] (no note for [{key}])')


__all__ = [
    '_SCRATCHPAD_META_KEY',
    '_load_notes',
    'build_note_action',
    'build_recall_action',
    'create_note_tool',
    'create_recall_tool',
    'scratchpad_entries_for_prompt',
]
