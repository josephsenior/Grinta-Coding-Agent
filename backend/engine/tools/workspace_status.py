"""workspace_status tool — quick snapshot of project state in one call.

Returns git status, recent changes, file tree summary, and running
processes so the agent can orient without multiple bash round-trips.
Platform-aware: uses PowerShell on Windows, bash on Unix.
"""

from __future__ import annotations

import sys

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


def _build_bash_command(
    include_git: bool, include_tree: bool, tree_depth: int
) -> str:
    """Build bash command for Unix (Linux, macOS)."""
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
    parts.append(
        'echo "" && echo "=== BACKGROUND PROCESSES ===" && '
        "(ps aux 2>/dev/null | head -20 || echo '(ps not available)')"
    )
    return " && ".join(parts)


def _build_powershell_command(
    include_git: bool, include_tree: bool, tree_depth: int
) -> str:
    """Build PowerShell command for Windows."""
    depth = max(0, tree_depth - 1)
    parts: list[str] = []

    if include_git:
        parts.append(
            "Write-Output '=== GIT STATUS ==='; "
            "$g=git status --short 2>$null; "
            "if($LASTEXITCODE -ne 0){'(not a git repo)'}else{$g}; "
            "Write-Output ''; Write-Output '=== RECENT COMMITS ==='; "
            "$l=git log --oneline -5 2>$null; "
            "if($LASTEXITCODE -ne 0){'(no git history)'}else{$l}"
        )
    if include_tree:
        parts.append(
            f"Write-Output ''; Write-Output '=== DIRECTORY TREE (depth {tree_depth}) ==='; "
            f"Get-ChildItem -Recurse -Depth {depth} -ErrorAction SilentlyContinue | "
            r"Where-Object { $_.FullName -notmatch 'node_modules|__pycache__|venv|\.git' } | "
            "Select-Object -First 80 | ForEach-Object { $_.FullName }"
        )
    parts.append(
        "Write-Output ''; Write-Output '=== BACKGROUND PROCESSES ==='; "
        "Get-Process -ErrorAction SilentlyContinue | "
        "Select-Object -First 20 | "
        'ForEach-Object { "$($_.Id) $($_.ProcessName)" }'
    )
    return "; ".join(parts)


def build_workspace_status_action(arguments: dict):
    """Build a CmdRunAction that gathers workspace state in one command."""
    from backend.ledger.action.commands import CmdRunAction

    include_git = arguments.get("include_git", True)
    include_tree = arguments.get("include_tree", True)
    tree_depth = arguments.get("tree_depth", 2)
    if not isinstance(tree_depth, int) or tree_depth < 1:
        tree_depth = 2

    if sys.platform == "win32":
        command = _build_powershell_command(include_git, include_tree, tree_depth)
    else:
        command = _build_bash_command(include_git, include_tree, tree_depth)

    return CmdRunAction(
        command=command,
        thought="Gathering workspace status snapshot",
    )
