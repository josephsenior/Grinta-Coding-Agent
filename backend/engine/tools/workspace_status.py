"""workspace_status tool — project state, diffs, checkpoints, rollback.

Unified workspace management tool combining status snapshots, session diffs,
checkpoint save/view/clear, and workspace rollback. Platform-aware.
"""

from __future__ import annotations

from backend.engine.tools.prompt import uses_powershell_terminal

WORKSPACE_STATUS_TOOL_NAME = 'workspace_status'


def create_workspace_status_tool() -> dict:
    """Return the OpenAI function-calling schema for workspace_status."""
    return {
        'type': 'function',
        'function': {
            'name': WORKSPACE_STATUS_TOOL_NAME,
            'description': (
                'Workspace management: status snapshots, session diffs, checkpoints, and rollback.\n'
                'Commands:\n'
                '  status (default) — git status, recent commits, directory tree, background processes\n'
                '  diff — show cumulative git diff of all session changes (use before finish)\n'
                '  checkpoint_save — save a progress checkpoint with label\n'
                '  checkpoint_view — list all saved checkpoints\n'
                '  checkpoint_clear — clear all checkpoints\n'
                '  revert — rollback workspace to a checkpoint'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'command': {
                        'type': 'string',
                        'enum': [
                            'status',
                            'diff',
                            'checkpoint_save',
                            'checkpoint_view',
                            'checkpoint_clear',
                            'revert',
                        ],
                        'description': 'Operation to perform (default: status).',
                    },
                    'include_git': {
                        'description': 'For status: include git info (default: true).',
                        'type': 'boolean',
                    },
                    'include_tree': {
                        'description': 'For status: include directory tree (default: true).',
                        'type': 'boolean',
                    },
                    'tree_depth': {
                        'description': 'For status: tree depth (default: 2).',
                        'type': 'integer',
                    },
                    'stat_only': {
                        'description': "For diff: if 'true', show summary only.",
                        'type': 'string',
                        'enum': ['true', 'false'],
                    },
                    'path': {
                        'description': 'For diff: limit to a specific file or directory.',
                        'type': 'string',
                    },
                    'label': {
                        'description': 'For checkpoint_save: short description of completed work.',
                        'type': 'string',
                    },
                    'files_modified': {
                        'description': 'For checkpoint_save: comma-separated list of changed files.',
                        'type': 'string',
                    },
                    'checkpoint_id': {
                        'description': 'For revert: specific checkpoint ID to revert to.',
                        'type': 'string',
                    },
                },
                'required': [],
            },
        },
    }


def _build_bash_command(include_git: bool, include_tree: bool, tree_depth: int) -> str:
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
            f'| head -80 || ls -la)'
        )
    parts.append(
        'echo "" && echo "=== BACKGROUND PROCESSES ===" && '
        "(ps aux 2>/dev/null | head -20 || echo '(ps not available)')"
    )
    return ' && '.join(parts)


def _build_powershell_command(
    include_git: bool, include_tree: bool, tree_depth: int
) -> str:
    """Build PowerShell command for Windows."""
    depth = max(0, tree_depth - 1)
    parts: list[str] = []

    if include_git:
        parts.append(
            "Write-Output '=== GIT STATUS ==='; "
            '$g=git status --short 2>$null; '
            "if($LASTEXITCODE -ne 0){'(not a git repo)'}else{$g}; "
            "Write-Output ''; Write-Output '=== RECENT COMMITS ==='; "
            '$l=git log --oneline -5 2>$null; '
            "if($LASTEXITCODE -ne 0){'(no git history)'}else{$l}"
        )
    if include_tree:
        parts.append(
            f"Write-Output ''; Write-Output '=== DIRECTORY TREE (depth {tree_depth}) ==='; "
            f'Get-ChildItem -Recurse -Depth {depth} -ErrorAction SilentlyContinue | '
            r"Where-Object { $_.FullName -notmatch 'node_modules|__pycache__|venv|\.git' } | "
            'Select-Object -First 80 | ForEach-Object { $_.FullName }'
        )
    parts.append(
        "Write-Output ''; Write-Output '=== BACKGROUND PROCESSES ==='; "
        'Get-Process -ErrorAction SilentlyContinue | '
        'Select-Object -First 20 | '
        'ForEach-Object { "$($_.Id) $($_.ProcessName)" }'
    )
    return '; '.join(parts)


def _build_bash_diff_command(stat_flag: str, safe_path: str) -> str:
    return (
        "echo '=== SESSION CHANGES ===' && "
        f'git diff HEAD{stat_flag} {safe_path} 2>/dev/null || '
        "echo '(not a git repository)'"
    )


def _build_powershell_diff_command(stat_flag: str, safe_path: str) -> str:
    return (
        "Write-Output '=== SESSION CHANGES ==='; "
        f'$d=git diff HEAD{stat_flag} {safe_path} 2>$null; '
        "if($LASTEXITCODE -ne 0){'(not a git repository)'}else{$d}"
    )


def build_workspace_status_action(arguments: dict):
    """Route to the appropriate sub-handler based on *command*."""
    command = arguments.get('command', 'status')

    if command == 'diff':
        return _build_diff_action(arguments)
    if command == 'checkpoint_save':
        return _build_checkpoint_action('save', arguments)
    if command == 'checkpoint_view':
        return _build_checkpoint_action('view', arguments)
    if command == 'checkpoint_clear':
        return _build_checkpoint_action('clear', arguments)
    if command == 'revert':
        return _build_revert_action(arguments)

    # Default: status snapshot
    return _build_status_action(arguments)


def _build_status_action(arguments: dict):
    """Build a CmdRunAction that gathers workspace state in one command."""
    from backend.ledger.action.commands import CmdRunAction

    include_git = arguments.get('include_git', True)
    include_tree = arguments.get('include_tree', True)
    tree_depth = arguments.get('tree_depth', 2)
    if not isinstance(tree_depth, int) or tree_depth < 1:
        tree_depth = 2

    if uses_powershell_terminal():
        cmd = _build_powershell_command(include_git, include_tree, tree_depth)
    else:
        cmd = _build_bash_command(include_git, include_tree, tree_depth)

    return CmdRunAction(command=cmd, thought='Gathering workspace status snapshot', display_label='Gathering workspace status')


def _build_diff_action(arguments: dict):
    """Show cumulative git diff of session changes."""
    import shlex

    from backend.ledger.action.commands import CmdRunAction

    stat_only = arguments.get('stat_only', 'false') == 'true'
    path = arguments.get('path', '')
    safe_path = shlex.quote(path) if path else ''
    stat_flag = ' --stat' if stat_only else ''

    if uses_powershell_terminal():
        cmd = _build_powershell_diff_command(stat_flag, safe_path)
    else:
        cmd = _build_bash_diff_command(stat_flag, safe_path)
    return CmdRunAction(command=cmd, display_label='Reviewing session changes')


def _build_checkpoint_action(sub_command: str, arguments: dict):
    """Delegate to the checkpoint module."""
    from backend.engine.tools.checkpoint import build_checkpoint_action

    return build_checkpoint_action({'command': sub_command, **arguments})


def _build_revert_action(arguments: dict):
    """Delegate to the revert_to_checkpoint module."""
    from backend.engine.tools.revert_to_checkpoint import (
        build_revert_to_checkpoint_action,
    )

    return build_revert_to_checkpoint_action(arguments)
