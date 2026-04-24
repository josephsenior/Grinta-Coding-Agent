"""Constants for tool names used in function calling."""

from backend.core.constants import (
    FINISH_TOOL_NAME,
    LLM_BASED_EDIT_TOOL_NAME,
    STR_REPLACE_EDITOR_TOOL_NAME,
    TASK_TRACKER_TOOL_NAME,
)

STRUCTURE_EDITOR_TOOL_NAME = 'edit_code'

__all__ = [
    'FINISH_TOOL_NAME',
    'LLM_BASED_EDIT_TOOL_NAME',
    'STR_REPLACE_EDITOR_TOOL_NAME',
    'TASK_TRACKER_TOOL_NAME',
    'STRUCTURE_EDITOR_TOOL_NAME',
]
