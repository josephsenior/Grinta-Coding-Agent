"""Legacy compatibility shim for scratchpad and working-memory helpers.

Prefer `note.py` for flat scratchpad state and `working_memory.py` for
structured working memory. This module remains only so older imports and tests
continue to resolve during the migration.
"""

from backend.engines.orchestrator.tools.note import (
    _SCRATCHPAD_META_KEY,
    _load_notes,
    build_note_action,
    build_recall_action,
    create_note_tool,
    create_recall_tool,
    scratchpad_entries_for_prompt,
)
from backend.engines.orchestrator.tools.working_memory import (
    WORKING_MEMORY_TOOL_NAME,
    build_working_memory_action,
    create_working_memory_tool,
    get_full_working_memory,
)

__all__ = [
    "_SCRATCHPAD_META_KEY",
    "_load_notes",
    "WORKING_MEMORY_TOOL_NAME",
    "build_note_action",
    "build_recall_action",
    "build_working_memory_action",
    "create_note_tool",
    "create_recall_tool",
    "create_working_memory_tool",
    "get_full_working_memory",
    "scratchpad_entries_for_prompt",
]
