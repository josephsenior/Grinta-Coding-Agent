"""Tools for managing interactive PTY terminal sessions."""

from typing import Any

from backend.events.action.terminal import (
    TerminalInputAction,
    TerminalReadAction,
    TerminalRunAction,
)

TERMINAL_OPEN_TOOL_NAME = "terminal_open"
TERMINAL_INPUT_TOOL_NAME = "terminal_input"
TERMINAL_READ_TOOL_NAME = "terminal_read"


def create_terminal_open_tool() -> dict[str, Any]:
    """Create the terminal_open tool definition."""
    return {
        "type": "function",
        "function": {
            "name": TERMINAL_OPEN_TOOL_NAME,
            "description": (
                "Open a new interactive PTY terminal session. Useful for starting long-running "
                "processes (like servers, REPLs, interactive prompts) that you want to interact "
                "with asynchronously. Returns a session ID."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The command to run to start the session (e.g., 'python', 'npm start').",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Optional working directory for the session.",
                    },
                },
                "required": ["command"],
            },
        },
    }


def create_terminal_input_tool() -> dict[str, Any]:
    """Create the terminal_input tool definition."""
    return {
        "type": "function",
        "function": {
            "name": TERMINAL_INPUT_TOOL_NAME,
            "description": (
                "Send input to an existing interactive PTY terminal session. "
                "Can send regular text or control characters (e.g., 'C-c' for SIGINT)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "The ID of the terminal session.",
                    },
                    "input": {
                        "type": "string",
                        "description": "The text or control character to send.",
                    },
                    "is_control": {
                        "type": "boolean",
                        "description": "Set to true if sending a control character sequence like 'C-c'.",
                    },
                },
                "required": ["session_id", "input"],
            },
        },
    }


def create_terminal_read_tool() -> dict[str, Any]:
    """Create the terminal_read tool definition."""
    return {
        "type": "function",
        "function": {
            "name": TERMINAL_READ_TOOL_NAME,
            "description": (
                "Read the latest output buffer from an existing terminal session."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "The ID of the terminal session.",
                    },
                },
                "required": ["session_id"],
            },
        },
    }


def build_terminal_open_action(arguments: dict) -> TerminalRunAction:
    """Build a TerminalRunAction."""
    return TerminalRunAction(
        command=arguments["command"],
        cwd=arguments.get("cwd"),
    )


def build_terminal_input_action(arguments: dict) -> TerminalInputAction:
    """Build a TerminalInputAction."""
    is_control = arguments.get("is_control", False)
    if isinstance(is_control, str):
        is_control = is_control.lower() == "true"
    return TerminalInputAction(
        session_id=arguments["session_id"],
        input=arguments["input"],
        is_control=is_control,
    )


def build_terminal_read_action(arguments: dict) -> TerminalReadAction:
    """Build a TerminalReadAction."""
    return TerminalReadAction(
        session_id=arguments["session_id"],
    )
