"""Token-oriented shell command classification for validation and stuck detection.

Avoids naive substring checks like ``"test" in cmd`` matching unrelated tokens.
"""

from __future__ import annotations

import os
import shlex
from typing import TYPE_CHECKING

from backend.core.os_capabilities import OS_CAPS

if TYPE_CHECKING:
    from backend.ledger.action.commands import CmdRunAction
    from backend.ledger.observation.commands import CmdOutputObservation

from backend.ledger.event import Event


def argv_tokens(command: str) -> list[str]:
    """Best-effort argv splitting for POSIX and Windows-like strings."""
    raw = (command or '').strip()
    if not raw:
        return []
    try:
        return shlex.split(raw, posix=not OS_CAPS.is_windows)
    except ValueError:
        return raw.split()


def _basename_lower(token: str) -> str:
    t = token.strip().strip('"').strip("'")
    return os.path.basename(t).lower()


def _is_python_test_module_invocation(lower_all: list[str]) -> bool:
    if 'unittest' in lower_all and '-m' in lower_all and 'python' in lower_all[0]:
        return True
    if '-m' in lower_all and 'pytest' in lower_all:
        return True
    return '-m' in lower_all and 'unittest' in lower_all


def _is_package_manager_test_command(lower_all: list[str]) -> bool:
    return (
        len(lower_all) >= 2
        and lower_all[0] in ('npm', 'pnpm', 'yarn', 'bun')
        and lower_all[1] == 'test'
    )


def _is_native_test_command(lower_all: list[str]) -> bool:
    return (
        len(lower_all) >= 2
        and lower_all[0] in ('cargo', 'go')
        and lower_all[1] == 'test'
    )


def _is_test_executable(tokens: list[str], lower_all: list[str]) -> bool:
    first_base = _basename_lower(tokens[0])
    if first_base in ('jest', 'mocha', 'vitest', 'pytest', 'py.test'):
        return True
    return 'pytest' in lower_all or 'py.test' in lower_all


def _is_build_tool_test_command(joined: str, first_base: str) -> bool:
    return 'test' in joined and first_base in ('dotnet', 'gradle', 'mvn', 'maven')


def _is_filesystem_inspection_command(lower: list[str]) -> bool:
    inspect_tokens = (
        'cat',
        'ls',
        'pwd',
        'find',
        'head',
        'tail',
        'more',
        'less',
        'wc',
        'stat',
        'file',
        'tree',
    )
    return lower[0] in inspect_tokens or lower[0] in (
        'dir',
        'type',
        'get-content',
        'get-childitem',
    )


def _is_fetch_code_command(lower: list[str]) -> bool:
    return len(lower) >= 2 and lower[0] == 'git' and lower[1] in (
        'clone',
        'pull',
        'fetch',
    )


def _is_install_dependency_command(joined: str) -> bool:
    return any(
        joined.startswith(prefix)
        for prefix in (
            'pip install',
            'npm install',
            'pnpm install',
            'yarn install',
            'cargo build',
        )
    )


def _is_create_file_command(lower: list[str], command: str) -> bool:
    return any(token in ' '.join(lower) for token in ('mkdir', 'touch')) or (
        len(lower) >= 2 and lower[0] == 'echo' and '>' in command
    )


def _is_delete_file_command(lower: list[str]) -> bool:
    return lower[0] in ('rm', 'rmdir', 'del', 'remove-item')


def _is_execute_code_command(lower: list[str], joined: str) -> bool:
    return lower[0] in ('python', 'node', 'cargo', 'ruby', 'php') and 'test' not in joined


def is_test_run_command(command: str) -> bool:
    """Return True if ``command`` is intended as a test invocation."""
    tokens = argv_tokens(command)
    if not tokens:
        return False
    lower_all = [t.lower() for t in tokens]
    joined = ' '.join(lower_all)
    first_base = _basename_lower(tokens[0])
    if _is_python_test_module_invocation(lower_all):
        return True
    if _is_package_manager_test_command(lower_all):
        return True
    if _is_native_test_command(lower_all):
        return True
    if _is_test_executable(tokens, lower_all):
        return True
    if len(tokens) >= 2 and lower_all[0] == 'make' and lower_all[1] in ('test', 'check'):
        return True
    return _is_build_tool_test_command(joined, first_base)


def is_git_diff_command(command: str) -> bool:
    """Return True if this is a git diff (or show) style inspection command."""
    tokens = argv_tokens(command)
    lower = [t.lower() for t in tokens]
    if 'git' not in lower:
        return False
    i = lower.index('git')
    if i + 1 >= len(lower):
        return False
    verb = lower[i + 1]
    return verb in ('diff', 'show', 'log')


def _classify_non_test_shell_intent(
    lower: list[str], joined: str, command: str
) -> str:
    checks = (
        ('inspect_filesystem', _is_filesystem_inspection_command(lower)),
        ('fetch_code', _is_fetch_code_command(lower)),
        ('install_dependency', _is_install_dependency_command(joined)),
        ('create_file', _is_create_file_command(lower, command)),
        ('delete_file', _is_delete_file_command(lower)),
        ('execute_code', _is_execute_code_command(lower, joined)),
    )
    for label, matches in checks:
        if matches:
            return label
    return 'other_command'


def _event_action_id(run: 'CmdRunAction') -> int | None:
    rid = getattr(run, 'id', None)
    if rid is None:
        return None
    aid = int(rid)
    if aid == Event.INVALID_ID:
        return None
    return aid


def _find_cmd_output_by_cause(
    history: list,
    start: int,
    end: int,
    aid: int,
) -> 'CmdOutputObservation | None':
    from backend.ledger.observation.commands import CmdOutputObservation

    return next(
        (
            event
            for event in history[start:end]
            if isinstance(event, CmdOutputObservation) and event.cause == aid
        ),
        None,
    )


def _find_cmd_output_by_command(
    history: list,
    start: int,
    end: int,
    command: str,
) -> 'CmdOutputObservation | None':
    from backend.ledger.observation.commands import CmdOutputObservation

    return next(
        (
            event
            for event in history[start:end]
            if isinstance(event, CmdOutputObservation)
            and getattr(event, 'command', None) == command
        ),
        None,
    )


def classify_shell_intent(command: str) -> str:
    """Coarse intent bucket for stuck / loop scoring (token-oriented, not log parsing)."""
    tokens = argv_tokens(command)
    lower = [t.lower() for t in tokens]
    joined = ' '.join(lower)
    if not tokens:
        return 'other_command'

    if is_test_run_command(command):
        return 'run_test'
    if is_git_diff_command(command):
        return 'inspect_git'
    return _classify_non_test_shell_intent(lower, joined, command)


def find_cmd_output_for_run(
    run: 'CmdRunAction',
    history: list,
    run_index: int,
    *,
    max_lookahead: int = 40,
) -> 'CmdOutputObservation | None':
    """Pair a ``CmdRunAction`` to its ``CmdOutputObservation`` using ``cause`` first.

    Falls back to matching ``observation.command`` only when the run has no event id
    (e.g. deserialized or synthetic history).
    """
    aid = _event_action_id(run)
    start = run_index + 1
    end = min(len(history), run_index + 1 + max_lookahead)

    if aid is not None:
        return _find_cmd_output_by_cause(history, start, end, aid)

    fallback_end = min(run_index + 8, len(history))
    return _find_cmd_output_by_command(history, start, fallback_end, run.command)
