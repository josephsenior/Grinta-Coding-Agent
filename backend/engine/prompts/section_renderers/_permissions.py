"""Renderer for the <PERMISSIONS> block from ``config.permissions``."""

from __future__ import annotations

from typing import Any


def _permission_git_summary(perm: Any) -> tuple[str, str]:
    git_parts: list[str] = []
    if getattr(perm, 'git_enabled', False):
        if getattr(perm, 'git_allow_commit', False):
            git_parts.append('COMMIT')
        if getattr(perm, 'git_allow_push', False):
            git_parts.append('PUSH')
        if getattr(perm, 'git_allow_force_push', False):
            git_parts.append('FORCE')
        if getattr(perm, 'git_allow_branch_delete', False):
            git_parts.append('DELETE-BRANCH')
        git_str = ' '.join(git_parts) or 'ENABLED'
    else:
        git_str = 'DISABLED'
    git_protected = ', '.join(getattr(perm, 'git_protected_branches', []))
    return git_str, git_protected


def _permission_shell_network_limits(perm: Any) -> tuple[str, str, str, str]:
    shell_str = 'ENABLED' if getattr(perm, 'shell_enabled', False) else 'DISABLED'
    if getattr(perm, 'shell_enabled', False) and getattr(
        perm, 'shell_allow_sudo', False
    ):
        shell_str += ' + SUDO'
    shell_blocked = ', '.join(getattr(perm, 'shell_blocked_commands', []))

    net_str = 'DISABLED'
    if getattr(perm, 'network_enabled', False):
        net_str = f'{getattr(perm, "network_max_requests_per_minute", "?")}/min'
        domains = getattr(perm, 'network_allowed_domains', [])
        if domains:
            net_str += f' | Only: {", ".join(domains)}'

    max_writes = getattr(perm, 'max_file_writes_per_task', '?')
    max_cmds = getattr(perm, 'max_shell_commands_per_task', '?')
    cost = getattr(perm, 'max_cost_per_task', None)
    limits = f'{max_writes} files, {max_cmds} commands'
    if cost:
        limits += f', ${cost} cost'

    return shell_str, shell_blocked, net_str, limits


def _render_permissions(config: Any, perm: Any) -> str:
    """Render the <PERMISSIONS> block from config.permissions."""
    file_w = 'WRITE' if getattr(perm, 'file_write_enabled', False) else 'READ-ONLY'
    if getattr(perm, 'file_write_enabled', False):
        file_w += f' (max {getattr(perm, "file_operations_max_size_mb", "?")}MB)'
    file_d = 'DELETE' if getattr(perm, 'file_delete_enabled', False) else 'NO DELETE'
    blocked = ', '.join(getattr(perm, 'file_operations_blocked_paths', []))

    git_str, git_protected = _permission_git_summary(perm)
    shell_str, shell_blocked, net_str, limits = _permission_shell_network_limits(perm)

    return (
        '<PERMISSIONS>\n'
        f'**File:** {file_w} | {file_d}\n'
        f'Blocked: {blocked}\n\n'
        f'**Git:** {git_str}\n'
        f'Protected: {git_protected}\n\n'
        f'**Shell:** {shell_str}\n'
        f'Blocked: {shell_blocked}\n\n'
        f'**Network:** {net_str}\n\n'
        f'**Limits:** {limits}/task\n\n'
        'Exceeding permissions → Error. Work within limits or request permission.\n'
        '</PERMISSIONS>'
    )
