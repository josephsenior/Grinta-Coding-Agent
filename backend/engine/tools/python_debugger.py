"""Compatibility aliases for the generic DAP debugger tool."""

from __future__ import annotations

from backend.engine.tools.debugger import (
    DEBUGGER_TOOL_NAME,
    PYTHON_DEBUGGER_TOOL_NAME,
    create_debugger_tool,
    create_python_debugger_tool,
    handle_debugger_tool,
    handle_python_debugger_tool,
)

__all__ = [
    'DEBUGGER_TOOL_NAME',
    'PYTHON_DEBUGGER_TOOL_NAME',
    'create_debugger_tool',
    'create_python_debugger_tool',
    'handle_debugger_tool',
    'handle_python_debugger_tool',
]

