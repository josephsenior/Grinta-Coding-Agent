"""Structured working memory tool — a cognitive workspace that survives condensation.

Unlike the flat key→value scratchpad (note/recall), working memory provides
structured sections that map to how an LLM agent actually thinks:
- hypothesis: current theory or approach
- findings: discovered facts and evidence
- blockers: obstacles and unresolved issues
- file_context: key files and their roles
- decisions: architectural/implementation choices made

All sections persist to ``.app/working_memory.json`` and are automatically
injected into post-condensation recovery context, ensuring the agent never
loses its cognitive workspace even after history compression.

Working memory is scoped per session: each conversation gets its own file
to prevent context pollution across unrelated tasks on the same workspace.
"""

from __future__ import annotations

import contextvars
import json
import time
from pathlib import Path
from typing import Any

from backend.ledger.action.memory_tools import WorkingMemoryAction
from backend.ledger.observation.memory_tools import WorkingMemoryObservation

_VALID_SECTIONS = (
    'hypothesis',
    'findings',
    'blockers',
    'file_context',
    'decisions',
    'plan',
)


# Session-scoped context: set at session start to isolate working memory
# across concurrent/sequential sessions on the same workspace.
_current_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    'working_memory_session_id', default=None
)


def set_current_session_id(session_id: str | None) -> None:
    """Set the session ID for working memory scoping. Call at session start."""
    _current_session_id.set(session_id)


def get_current_session_id() -> str | None:
    """Get the current session ID for working memory scoping."""
    return _current_session_id.get()


# --- Persistence ---


def _memory_path() -> Path:
    from backend.context.session_context import scoped_agent_path

    return scoped_agent_path('working_memory', '.json')


def _load_memory() -> dict[str, str]:
    p = _memory_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _save_memory(data: dict[str, str]) -> None:
    p = _memory_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')


# --- Action builders ---


def build_working_memory_action(arguments: dict[str, Any]) -> WorkingMemoryAction:
    """Build a runnable working-memory action from tool arguments."""
    return WorkingMemoryAction(
        command=str(arguments.get('command', 'get') or 'get'),
        section=str(arguments.get('section', 'all') or 'all'),
        content=str(arguments.get('content', '') or ''),
    )


def execute_working_memory(action: WorkingMemoryAction) -> WorkingMemoryObservation:
    """Execute a working-memory command and return a structured observation."""
    command = (action.command or 'get').strip().lower()
    if command == 'update':
        return _update_section(action.section, action.content)
    if command == 'clear_section':
        return _clear_section(action.section)
    return _get_section(action.section)


def _wm_obs(
    *,
    content: str,
    command: str,
    section: str = 'all',
    updated_sections: list[str] | None = None,
    ok: bool = True,
) -> WorkingMemoryObservation:
    snapshot = _load_memory() if command == 'get' else {}
    return WorkingMemoryObservation(
        content=content,
        command=command,
        section=section,
        updated_sections=list(updated_sections or []),
        memory_snapshot=dict(snapshot),
        ok=ok,
    )


def _update_section(section: str, content: str) -> WorkingMemoryObservation:
    if section == 'all':
        return _update_all_sections(content)
    if section not in _VALID_SECTIONS:
        return _wm_obs(
            content=f'Invalid section: {section}. Valid: {", ".join(_VALID_SECTIONS)}',
            command='update',
            section=section,
            ok=False,
        )
    if not content:
        return _wm_obs(
            content="'content' is required for update.",
            command='update',
            section=section,
            ok=False,
        )
    memory = _load_memory()
    memory[section] = content
    memory['_last_updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
    _save_memory(memory)
    return _wm_obs(
        content=f"Updated '{section}' section.",
        command='update',
        section=section,
        updated_sections=[section],
    )


def _update_all_sections(content: str) -> WorkingMemoryObservation:
    """Update multiple working-memory sections in one call.

    Accepts either:
    - JSON object: {"hypothesis": "...", "findings": "...", ...}
    - A markdown-ish block with headings like "## HYPOTHESIS" or "[HYPOTHESIS]".
    - Otherwise, stores the entire content into the 'findings' section.
    """
    if not content:
        return _wm_obs(
            content="'content' is required for update.",
            command='update',
            section='all',
            ok=False,
        )

    memory = _load_memory()

    updated = _apply_json_sections(content, memory)
    if updated:
        return _save_and_respond(memory, updated)

    updated = _apply_text_sections(content, memory)
    if updated:
        return _save_and_respond(memory, updated)

    memory['findings'] = content
    memory['_last_updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
    _save_memory(memory)
    return _wm_obs(
        content="Updated 'findings' section (fallback from section='all').",
        command='update',
        section='all',
        updated_sections=['findings'],
    )


def _apply_json_sections(content: str, memory: dict[str, str]) -> list[str]:
    try:
        maybe = json.loads(content)
    except json.JSONDecodeError:
        return []
    if not isinstance(maybe, dict):
        return []
    updated: list[str] = []
    for sec in _VALID_SECTIONS:
        val = maybe.get(sec)
        if isinstance(val, str) and val.strip():
            memory[sec] = val
            updated.append(sec)
    return updated


def _apply_text_sections(content: str, memory: dict[str, str]) -> list[str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in content.splitlines():
        line = raw_line.strip()
        header = None
        if line.startswith('##'):
            header = line.lstrip('#').strip()
        elif line.startswith('[') and line.endswith(']'):
            header = line[1:-1].strip()

        if header:
            key = header.lower().strip()
            if key in _VALID_SECTIONS:
                current = key
                sections.setdefault(key, [])
                continue

        if current is not None:
            sections[current].append(raw_line)

    updated: list[str] = []
    for sec, lines in sections.items():
        val = '\n'.join(lines).strip('\n')
        if val.strip():
            memory[sec] = val
            updated.append(sec)
    return updated


def _save_and_respond(
    memory: dict[str, str], updated: list[str]
) -> WorkingMemoryObservation:
    memory['_last_updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
    _save_memory(memory)
    return _wm_obs(
        content=f'Updated sections: {", ".join(updated)}.',
        command='update',
        section='all',
        updated_sections=updated,
    )


def _get_section(section: str) -> WorkingMemoryObservation:
    memory = _load_memory()
    if not memory:
        return _wm_obs(content='Working memory is empty.', command='get', section=section)
    if section == 'all':
        parts = ['Full cognitive workspace:']
        for sec in _VALID_SECTIONS:
            val = memory.get(sec, '')
            if val:
                parts.append(f'\n## {sec.upper()}\n{val}')
        if len(parts) == 1:
            return _wm_obs(content='All sections are empty.', command='get', section='all')
        last = memory.get('_last_updated', '?')
        parts.append(f'\n(last updated: {last})')
        return _wm_obs(content='\n'.join(parts), command='get', section='all')

    if section not in _VALID_SECTIONS:
        return _wm_obs(
            content=f'Invalid section: {section}. Valid: {", ".join(_VALID_SECTIONS)}',
            command='get',
            section=section,
            ok=False,
        )
    val = memory.get(section, '')
    if not val:
        return _wm_obs(content=f"'{section}' is empty.", command='get', section=section)
    return _wm_obs(content=f'{section}:\n{val}', command='get', section=section)


def _clear_section(section: str) -> WorkingMemoryObservation:
    if section == 'all':
        memory = _load_memory()
        any_cleared = False
        for sec in _VALID_SECTIONS:
            if sec in memory:
                del memory[sec]
                any_cleared = True
        if any_cleared:
            _save_memory(memory)
        return _wm_obs(content='Cleared all sections.', command='clear_section', section='all')
    if section not in _VALID_SECTIONS:
        return _wm_obs(
            content=f'Invalid section: {section}. Valid: {", ".join(_VALID_SECTIONS)}',
            command='clear_section',
            section=section,
            ok=False,
        )
    memory = _load_memory()
    if section in memory:
        del memory[section]
        _save_memory(memory)
    return _wm_obs(content=f"Cleared '{section}' section.", command='clear_section', section=section)


def get_full_working_memory() -> str:
    """Load and format working memory for injection into context.

    Used by post-condensation recovery to restore the cognitive workspace.
    Returns an empty string if working memory is empty.
    """
    memory = _load_memory()
    if not memory:
        return ''

    parts = ['<WORKING_MEMORY>']
    for sec in _VALID_SECTIONS:
        val = memory.get(sec, '')
        if val:
            parts.append(f'[{sec.upper()}] {val}')

    if len(parts) == 1:
        return ''
    parts.append('</WORKING_MEMORY>')
    return '\n'.join(parts)


def get_working_memory_prompt_block(char_budget: int = 2000) -> str:
    """Return a bounded working-memory block for prompt or recovery injection."""
    memory = _load_memory()
    if not memory:
        return ''

    lines = ['<WORKING_MEMORY>', 'Your structured working memory:']
    for sec in _VALID_SECTIONS:
        val = memory.get(sec, '')
        if not val:
            continue
        line = f'[{sec.upper()}] {val}'
        if len('\n'.join(lines + [line, '</WORKING_MEMORY>'])) > char_budget:
            lines.append('... (additional working memory truncated)')
            break
        lines.append(line)
    if len(lines) == 2:
        return ''
    lines.append('</WORKING_MEMORY>')
    return '\n'.join(lines)


def _working_memory_already_contains_note(existing: str, key: str, value: str) -> bool:
    existing_text = existing.strip()
    note_text = value.strip()
    if not existing_text or not note_text:
        return False
    entry_text = f'[{key}] {note_text}'
    return note_text in existing_text or entry_text in existing_text


def sync_scratchpad_to_working_memory(notes: dict[str, str]) -> list[str]:
    """Sync scratchpad notes to working_memory sections.

    Maps scratchpad keys to working_memory sections intelligently:
    - 'findings', 'discovery', 'discovered' -> findings
    - 'decisions', 'decision', 'choice' -> decisions
    - 'blockers', 'blocker', 'issues', 'problems' -> blockers
    - 'hypothesis', 'hypotheses', 'theory', 'approach' -> hypothesis
    - 'files', 'file_context', 'context' -> file_context
    - 'plan', 'steps', 'todo' -> plan
    - 'lessons', 'lessons_learned' -> findings (append)

    Returns list of sections that were updated.
    """
    key_to_section: dict[str, str] = {
        'findings': 'findings',
        'discovery': 'findings',
        'discovered': 'findings',
        'decisions': 'decisions',
        'decision': 'decisions',
        'choice': 'decisions',
        'blockers': 'blockers',
        'blocker': 'blockers',
        'issues': 'blockers',
        'problems': 'blockers',
        'hypothesis': 'hypothesis',
        'hypotheses': 'hypothesis',
        'theory': 'hypothesis',
        'approach': 'hypothesis',
        'files': 'file_context',
        'file_context': 'file_context',
        'context': 'file_context',
        'plan': 'plan',
        'steps': 'plan',
        'todo': 'plan',
        'lessons': 'findings',
        'lessons_learned': 'findings',
    }

    memory = _load_memory()
    updated: list[str] = []

    for key, value in notes.items():
        # Skip metadata keys
        if key.startswith('_'):
            continue

        section = key_to_section.get(key.lower())
        if section and value.strip():
            # Append to existing content if section already has data
            existing = memory.get(section, '')
            if existing:
                if _working_memory_already_contains_note(existing, key, value):
                    continue
                memory[section] = f'{existing}\n\n[{key}] {value}'
            else:
                memory[section] = value
            if section not in updated:
                updated.append(section)

    if updated:
        memory['_last_updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
        _save_memory(memory)

    return updated
