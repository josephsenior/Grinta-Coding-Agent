"""Re-export scratchpad note utilities for backward compatibility.

Implemented in memory_manager_temp1.
"""
from backend.engines.orchestrator.tools.memory_manager_temp1 import (
    _load_notes,
    scratchpad_entries_for_prompt,
)

__all__ = ["_load_notes", "scratchpad_entries_for_prompt"]
