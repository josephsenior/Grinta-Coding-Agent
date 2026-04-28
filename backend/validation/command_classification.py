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


def is_test_run_command(command: str) -> bool:
    """Return True if ``command`` is intended as a test invocation."""
    tokens = argv_tokens(command)
    if not tokens:
        return False
    lower_all = [t.lower() for t in tokens]
    joined = ' '.join(lower_all)

    # Explicit unittest module
    if 'unittest' in lower_all and '-m' in lower_all and 'python' in lower_all[0]:
        return True
    if '-m' in lower_all and 'pytest' in lower_all:
        return True
    if '-m' in lower_all and 'unittest' in lower_all:
        return True

    # npm / pnpm / yarn test
    if (
        len(tokens) >= 2
        and lower_all[0] in ('npm', 'pnpm', 'yarn', 'bun')
        and lower_all[1] == 'test'
    ):
        return True

    # cargo test, go test
    if len(tokens) >= 2 and lower_all[0] in ('cargo', 'go') and lower_all[1] == 'test':
        return True

    # jest / mocha / vitest as executable
    first_base = _basename_lower(tokens[0])
    if first_base in ('jest', 'mocha', 'vitest', 'pytest', 'py.test'):
        return True
    if 'pytest' in lower_all or 'py.test' in lower_all:
        return True

    # make test
    if (
        len(tokens) >= 2
        and lower_all[0] == 'make'
        and lower_all[1] in ('test', 'check')
    ):
        return True

    # Guard: avoid matching unrelated "test" substrings in paths
    if 'test' in joined and first_base in ('dotnet', 'gradle', 'mvn', 'maven'):
        return True

    return False


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
    if lower[0] in inspect_tokens or lower[0] in (
        'dir',
        'type',
        'get-content',
        'get-childitem',
    ):
        return 'inspect_filesystem'

    if len(lower) >= 2 and lower[0] == 'git' and lower[1] in ('clone', 'pull', 'fetch'):
        return 'fetch_code'

    if any(
        joined.startswith(p)
        for p in (
            'pip install',
            'npm install',
            'pnpm install',
            'yarn install',
            'cargo build',
        )
    ):
        return 'install_dependency'

    if any(p in joined for p in ('mkdir', 'touch')) or (
        len(lower) >= 2 and lower[0] == 'echo' and '>' in command
    ):
        return 'create_file'

    if lower[0] in ('rm', 'rmdir', 'del', 'remove-item'):
        return 'delete_file'

    if lower[0] in ('python', 'node', 'cargo', 'ruby', 'php') and 'test' not in joined:
        return 'execute_code'

    return 'other_command'


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
    from backend.ledger.observation.commands import CmdOutputObservation

    rid = getattr(run, 'id', None)
    aid = int(rid) if rid is not None and int(rid) != Event.INVALID_ID else None
    end = min(len(history), run_index + 1 + max_lookahead)

    for j in range(run_index + 1, end):
        ev = history[j]
        if isinstance(ev, CmdOutputObservation) and aid is not None and ev.cause == aid:
            return ev

    if aid is None:
        for j in range(run_index + 1, min(run_index + 8, len(history))):
            ev = history[j]
            if (
                isinstance(ev, CmdOutputObservation)
                and getattr(ev, 'command', None) == run.command
            ):
                return ev
    return None
