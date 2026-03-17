from typing import Any
from backend.events.action.terminal import (
    TerminalInputAction,
    TerminalReadAction,
    TerminalRunAction,
)

TERMINAL_MANAGER_TOOL_NAME = "terminal_manager"

def create_terminal_manager_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TERMINAL_MANAGER_TOOL_NAME,
            "description": (
                "Manage interactive PTY terminal sessions. Can be used to "
                "open a new session, send input, or read output buffers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["open", "input", "read"],
                        "description": "The action to perform. 'open' to start a command. 'input' to send text/control-c. 'read' to view output."
                    },
                    "session_id": {
                        "type": "string",
                        "description": "The session ID. Required for 'input' and 'read' actions."
                    },
                    "command": {
                        "type": "string",
                        "description": "The command to start the session. Required for 'open' action."
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Optional working directory for the session."
                    },
                    "input": {
                        "type": "string",
                        "description": "The text or control character to send. Required for 'input'."
                    },
                    "is_control": {
                        "type": "boolean",
                        "description": "Set to true if sending a control character sequence like 'C-c'."
                    }
                },
                "required": ["action"]
            }
        }
    }

def handle_terminal_manager_tool(arguments: dict) -> Any:
    """Route terminal manager intents back into the core backend actions."""
    action = arguments.get("action")
    
    if action == "open":
        cmd = arguments.get("command")
        if not cmd:
            raise ValueError("Terminal 'open' action requires 'command'")
        return TerminalRunAction(command=cmd, cwd=arguments.get("cwd"))
        
    elif action == "input":
        session_id = arguments.get("session_id")
        input_val = arguments.get("input")
        if not session_id or not input_val:
            raise ValueError("Terminal 'input' action requires 'session_id' and 'input'")
            
        is_control = arguments.get("is_control", False)
        if isinstance(is_control, str):
            is_control = is_control.lower() == "true"
            
        return TerminalInputAction(
            session_id=session_id, input=input_val, is_control=is_control
        )
        
    elif action == "read":
        session_id = arguments.get("session_id")
        if not session_id:
            raise ValueError("Terminal 'read' action requires 'session_id'")
        return TerminalReadAction(session_id=session_id)
        
    raise ValueError(f"Unknown terminal manager action: {action}")
