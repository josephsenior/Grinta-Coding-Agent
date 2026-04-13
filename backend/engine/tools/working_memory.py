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
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.common import create_tool_definition
from backend.ledger.action.agent import AgentThinkAction

WORKING_MEMORY_TOOL_NAME = 'working_memory'

_VALID_SECTIONS = (
    'hypothesis',
    'findings',
    'blockers',
    'file_context',
    'decisions',
    'plan',
)

_DESCRIPTION = (
    'Structured cognitive workspace that survives context condensation. '
    'Sections: hypothesis, findings, blockers, file_context, decisions, plan. '
    "Commands: update (append/replace section content), get (retrieve section or 'all'), "
    'clear_section (reset a section). Auto-restored after condensation.'
)


def create_working_memory_tool() -> ChatCompletionToolParam:
    """Create the working memory tool definition."""
    return create_tool_definition(
        name=WORKING_MEMORY_TOOL_NAME,
        description=_DESCRIPTION,
        properties={
            'command': {
                'type': 'string',
                'enum': ['update', 'get', 'clear_section'],
                'description': (
                    'update: set/append content to a section. '
                    "get: retrieve a section (or 'all'). "
                    'clear_section: reset a section.'
                ),
            },
            'section': {
                'type': 'string',
                'enum': [*list(_VALID_SECTIONS), 'all'],
                'description': "The working memory section to operate on (or 'all').",
            },
            'content': {
                'type': 'string',
                'description': "For 'update': the content to store. Replaces existing content in the section.",
            },
        },
        required=['command', 'section'],
    )


# --- Persistence ---


def _memory_path() -> Path:
    from backend.core.workspace_resolution import workspace_agent_state_dir

    return workspace_agent_state_dir() / 'working_memory.json'


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


def build_working_memory_action(arguments: dict) -> AgentThinkAction:
    """Execute a working_memory command and return a think action with results."""
    command = arguments.get('command', 'get')
    section = arguments.get('section', 'all')
    content = arguments.get('content', '')

    if command == 'update':
        return _update_section(section, content)
    elif command == 'clear_section':
        return _clear_section(section)
    else:
        return _get_section(section)


def _update_section(section: str, content: str) -> AgentThinkAction:
    if section == 'all':
        return _update_all_sections(content)
    if section not in _VALID_SECTIONS:
        return AgentThinkAction(
            thought=f'[WORKING_MEMORY] Invalid section: {section}. Valid: {", ".join(_VALID_SECTIONS)}'
        )
    if not content:
        return AgentThinkAction(
            thought="[WORKING_MEMORY] 'content' is required for update."
        )
    memory = _load_memory()
    memory[section] = content
    memory['_last_updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
    _save_memory(memory)
    return AgentThinkAction(thought=f"[WORKING_MEMORY] Updated '{section}' section.")


def _update_all_sections(content: str) -> AgentThinkAction:
    """Update multiple working-memory sections in one call.

    Accepts either:
    - JSON object: {"hypothesis": "...", "findings": "...", ...}
    - A markdown-ish block with headings like "## HYPOTHESIS" or "[HYPOTHESIS]".
    - Otherwise, stores the entire content into the 'findings' section.
    """
    if not content:
        return AgentThinkAction(thought="[WORKING_MEMORY] 'content' is required for update.")

    memory = _load_memory()
    updated: list[str] = []

    # 1) Try JSON mapping first.
    try:
        maybe = json.loads(content)
    except json.JSONDecodeError:
        maybe = None

    if isinstance(maybe, dict):
        for sec in _VALID_SECTIONS:
            val = maybe.get(sec)
            if isinstance(val, str) and val.strip():
                memory[sec] = val
                updated.append(sec)

        if updated:
            memory['_last_updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
            _save_memory(memory)
            return AgentThinkAction(
                thought=f"[WORKING_MEMORY] Updated sections: {', '.join(updated)}."
            )

    # 2) Parse a simple multi-section text block.
    # Supported headers:
    #   ## HYPOTHESIS
    #   [HYPOTHESIS]
    # (case-insensitive)
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

    for sec, lines in sections.items():
        val = '\n'.join(lines).strip('\n')
        if val.strip():
            memory[sec] = val
            updated.append(sec)

    if updated:
        memory['_last_updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
        _save_memory(memory)
        return AgentThinkAction(thought=f"[WORKING_MEMORY] Updated sections: {', '.join(updated)}.")

    # 3) Fallback: store everything as findings.
    memory['findings'] = content
    memory['_last_updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
    _save_memory(memory)
    return AgentThinkAction(
        thought="[WORKING_MEMORY] Updated 'findings' section (fallback from section='all')."
    )


def _get_section(section: str) -> AgentThinkAction:
    memory = _load_memory()
    if not memory:
        return AgentThinkAction(thought='[WORKING_MEMORY] Working memory is empty.')
    if section == 'all':
        parts = ['[WORKING_MEMORY] Full cognitive workspace:']
        for sec in _VALID_SECTIONS:
            val = memory.get(sec, '')
            if val:
                parts.append(f'\n## {sec.upper()}\n{val}')
        if len(parts) == 1:
            return AgentThinkAction(thought='[WORKING_MEMORY] All sections are empty.')
        last = memory.get('_last_updated', '?')
        parts.append(f'\n(last updated: {last})')
        return AgentThinkAction(thought='\n'.join(parts))

    if section not in _VALID_SECTIONS:
        return AgentThinkAction(
            thought=f'[WORKING_MEMORY] Invalid section: {section}. Valid: {", ".join(_VALID_SECTIONS)}'
        )
    val = memory.get(section, '')
    if not val:
        return AgentThinkAction(thought=f"[WORKING_MEMORY] '{section}' is empty.")
    return AgentThinkAction(thought=f'[WORKING_MEMORY] {section}:\n{val}')


def _clear_section(section: str) -> AgentThinkAction:
    if section == 'all':
        memory = _load_memory()
        any_cleared = False
        for sec in _VALID_SECTIONS:
            if sec in memory:
                del memory[sec]
                any_cleared = True
        if any_cleared:
            _save_memory(memory)
        return AgentThinkAction(thought='[WORKING_MEMORY] Cleared all sections.')
    if section not in _VALID_SECTIONS:
        return AgentThinkAction(
            thought=f'[WORKING_MEMORY] Invalid section: {section}. Valid: {", ".join(_VALID_SECTIONS)}'
        )
    memory = _load_memory()
    if section in memory:
        del memory[section]
        _save_memory(memory)
    return AgentThinkAction(thought=f"[WORKING_MEMORY] Cleared '{section}' section.")


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
