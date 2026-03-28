"""Session Diff tool — shows cumulative changes made during the current session.

Gives the LLM a full view of everything it has changed before calling `finish`,
enabling self-review and catching mistakes across multiple files.
"""

from __future__ import annotations

from backend.ledger.action import CmdRunAction

SESSION_DIFF_TOOL_NAME = "session_diff"


def create_session_diff_tool() -> dict:
    """Return the OpenAI function-calling tool definition for session_diff."""
    return {
        "type": "function",
        "function": {
            "name": SESSION_DIFF_TOOL_NAME,
            "description": (
                "Show a cumulative diff of ALL changes made in this session. "
                "Use this before calling finish() to self-review your work. "
                "Shows staged + unstaged git diff. If not a git repo, shows "
                "the file manifest of touched files instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "stat_only": {
                        "type": "string",
                        "enum": ["true", "false"],
                        "description": (
                            "If 'true', show only a summary (files changed, insertions, deletions). "
                            "If 'false' (default), show the full diff."
                        ),
                        "default": "false",
                    },
                    "path": {
                        "type": "string",
                        "description": "Optional: limit diff to a specific file or directory.",
                        "default": "",
                    },
                },
                "required": [],
            },
        },
    }


def build_session_diff_action(arguments: dict) -> CmdRunAction:
    """Build the action for the session_diff tool call."""
    import shlex

    stat_only = arguments.get("stat_only", "false") == "true"
    path = arguments.get("path", "")
    safe_path = shlex.quote(path) if path else ""

    stat_flag = " --stat" if stat_only else ""

    # Show both staged and unstaged changes against HEAD
    cmd = (
        f"echo '=== SESSION CHANGES ===' && "
        f"git diff HEAD{stat_flag} {safe_path} 2>/dev/null || "
        f"echo '(not a git repository — use workspace_status or file manifest for change tracking)'"
    )
    return CmdRunAction(command=cmd)
