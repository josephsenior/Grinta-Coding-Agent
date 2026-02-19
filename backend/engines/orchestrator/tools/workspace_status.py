"""workspace_status tool — quick snapshot of project state in one call.

Returns git status, recent changes, file tree summary, and running
processes so the agent can orient without multiple bash round-trips.
"""

from __future__ import annotations

WORKSPACE_STATUS_TOOL_NAME = "workspace_status"


def create_workspace_status_tool() -> dict:
    """Return the OpenAI function-calling schema for workspace_status."""
    return {
        "type": "function",
        "function": {
            "name": WORKSPACE_STATUS_TOOL_NAME,
            "description": (
                "Get a quick snapshot of the current workspace: git status, "
                "recent commits, top-level directory tree, and any running "
                "background processes. Use this to orient yourself at the "
                "start of a task or after context condensation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "include_git": {
                        "description": "Include git status and recent log (default: true).",
                        "type": "boolean",
                    },
                    "include_tree": {
                        "description": "Include directory tree summary (default: true).",
                        "type": "boolean",
                    },
                    "tree_depth": {
                        "description": "Max depth for directory tree listing (default: 2).",
                        "type": "integer",
                    },
                },
                "required": [],
            },
        },
    }


def build_workspace_status_action(arguments: dict):
    """Build a CmdRunAction that gathers workspace state in one command."""
    from backend.events.action.commands import CmdRunAction

    include_git = arguments.get("include_git", True)
    include_tree = arguments.get("include_tree", True)
    tree_depth = arguments.get("tree_depth", 2)
    if not isinstance(tree_depth, int) or tree_depth < 1:
        tree_depth = 2

    parts: list[str] = []

    if include_git:
        parts.append(
            'echo "=== GIT STATUS ===" && '
            "(git status --short 2>/dev/null || echo '(not a git repo)') && "
            'echo "" && echo "=== RECENT COMMITS ===" && '
            "(git log --oneline -5 2>/dev/null || echo '(no git history)')"
        )

    if include_tree:
        parts.append(
            f'echo "" && echo "=== DIRECTORY TREE (depth {tree_depth}) ===" && '
            f"(find . -maxdepth {tree_depth} -not -path '*/\\.*' -not -path '*/node_modules/*' "
            f"-not -path '*/__pycache__/*' -not -path '*/venv/*' "
            f"| head -80 || ls -la)"
        )

    # Always show running bg processes
    parts.append(
        'echo "" && echo "=== BACKGROUND PROCESSES ===" && '
        "(ps aux 2>/dev/null | head -20 || echo '(ps not available)')"
    )

    combined = " && ".join(parts)
    return CmdRunAction(
        command=combined,
        thought="Gathering workspace status snapshot",
    )
