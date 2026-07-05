"""Agent-directed hints when shell commands stall or detach to background."""

from __future__ import annotations

import re

_STALL_TAG = '[INTERACTIVE_STALL]'

_SUDO_PASSWORD_RE = re.compile(
    r'\[sudo\]\s*password\s+for\s+\S',
    re.IGNORECASE,
)
_DPKG_APT_LOCK_RE = re.compile(
    r'(?:Could not get lock|Unable to lock|dpkg was interrupted|'
    r'is another process using it|/var/lib/dpkg/lock|/var/lib/apt/lists/lock)',
    re.IGNORECASE,
)
_APT_CONFIRM_RE = re.compile(
    r'Do you want to continue\?\s*\[Y/n\]',
    re.IGNORECASE,
)
_GENERIC_PASSWORD_RE = re.compile(
    r'(?:password|passwd)\s*:\s*$',
    re.IGNORECASE | re.MULTILINE,
)


def _tail_lines(text: str, n: int = 8) -> str:
    lines = (text or '').strip().splitlines()
    return '\n'.join(lines[-n:]) if lines else ''


def detect_shell_stall_reason(content: str, command: str = '') -> str | None:
    """Return a short agent-directed explanation for a stalled/detached command."""
    body = content or ''
    tail = _tail_lines(body, 8)
    cmd = (command or '').strip()

    if _SUDO_PASSWORD_RE.search(tail) or _SUDO_PASSWORD_RE.search(body):
        return (
            'Terminal output shows a sudo password prompt. Grinta cannot supply '
            'your password. Ask the user to run this elevated step, use sudo -n '
            'to fail fast without prompting, or avoid sudo.'
        )
    if _DPKG_APT_LOCK_RE.search(tail) or _DPKG_APT_LOCK_RE.search(body):
        return (
            'Package manager lock detected (dpkg/apt). Another install may be '
            'running, or a stale lock remains. Poll with terminal_read or check '
            'processes; do not start parallel apt/dpkg until the lock clears.'
        )
    if _APT_CONFIRM_RE.search(tail):
        return (
            'apt is waiting for interactive confirmation [Y/n]. Re-run with -y '
            'or answer via terminal_manager if appropriate.'
        )
    if _GENERIC_PASSWORD_RE.search(tail):
        return (
            'Terminal shows a password prompt. Grinta cannot supply credentials. '
            'Ask the user for help or use a non-interactive alternative.'
        )
    if cmd.lower().startswith('sudo ') and not tail.strip():
        return (
            'sudo produced no output before idle detach — likely waiting for a '
            'password or policy prompt. Grinta cannot type your password.'
        )
    return None


def observation_is_idle_detached(obs: object) -> bool:
    metadata = getattr(obs, 'metadata', None)
    if metadata is not None:
        if getattr(metadata, 'timeout_kind', None) == 'idle_detach':
            return True
        if getattr(metadata, 'exit_code', None) == -2:
            return True
    return getattr(obs, 'exit_code', None) == -2


def append_stall_hint_to_observation(obs: object) -> bool:
    """Append ``[INTERACTIVE_STALL] …`` to idle-detached command observations."""
    from backend.ledger.observation.commands import CmdOutputObservation

    if not isinstance(obs, CmdOutputObservation):
        return False
    if not observation_is_idle_detached(obs):
        return False
    content = str(getattr(obs, 'content', '') or '')
    if _STALL_TAG in content:
        return False
    command = str(getattr(obs, 'command', '') or '')
    hint = detect_shell_stall_reason(content, command)
    if not hint:
        return False
    obs.content = content.rstrip() + f'\n\n{_STALL_TAG} {hint}'
    return True


__all__ = [
    'append_stall_hint_to_observation',
    'detect_shell_stall_reason',
    'observation_is_idle_detached',
]
