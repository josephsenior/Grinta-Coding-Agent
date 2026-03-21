"""Re-export scratchpad note utilities for backward compatibility.

_load_notes is implemented in memory_manager_temp1.
"""
from backend.engines.orchestrator.tools.memory_manager_temp1 import _load_notes

__all__ = ["_load_notes"]
