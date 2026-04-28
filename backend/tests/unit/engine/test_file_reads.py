from __future__ import annotations

import shlex
from collections import deque
from typing import cast
from unittest.mock import patch

from backend.engine.file_reads import (
    _build_full_file_read_command,
    _build_partial_file_read_command,
    try_batch_file_reads,
)
from backend.ledger.action import Action
from backend.ledger.action.commands import CmdRunAction
from backend.ledger.action.files import FileReadAction


def test_try_batch_file_reads_uses_bash_commands_when_bash_contract_is_active():
    pending_actions = deque(
        [
            FileReadAction(path='src/repomentor/index.py'),
            FileReadAction(path='src/repomentor/__main__.py'),
        ]
    )

    with patch(
        'backend.engine.file_reads.uses_powershell_terminal', return_value=False
    ):
        batched = try_batch_file_reads(cast(deque[Action], pending_actions))

    assert isinstance(batched, CmdRunAction)
    assert 'Get-Content' not in batched.command
    assert 'Write-Output' not in batched.command
    assert 'cat src/repomentor/index.py' in batched.command
    assert 'cat src/repomentor/__main__.py' in batched.command
    assert ' && ' in batched.command


def test_try_batch_file_reads_uses_powershell_commands_when_powershell_contract_is_active():
    pending_actions = deque(
        [
            FileReadAction(path='src/repomentor/index.py'),
            FileReadAction(path='src/repomentor/__main__.py'),
        ]
    )

    with patch('backend.engine.file_reads.uses_powershell_terminal', return_value=True):
        batched = try_batch_file_reads(cast(deque[Action], pending_actions))

    assert isinstance(batched, CmdRunAction)
    assert 'Get-Content "src/repomentor/index.py" -Encoding UTF8' in batched.command
    assert 'Get-Content "src/repomentor/__main__.py" -Encoding UTF8' in batched.command
    assert ' ; ' in batched.command


# ---------------------------------------------------------------------------
# Injection-safety regression tests
# ---------------------------------------------------------------------------

_DANGEROUS_PATHS = [
    '/tmp/$(rm -rf /)',
    '/tmp/`id`',
    '/tmp/foo;bar',
    "/tmp/foo'bar",
    '/tmp/foo"bar',
    '/tmp/foo $VAR',
    '/tmp/file with spaces.txt',
]


def _is_safe_unix_command(cmd: str, path: str) -> bool:
    """Verify the path appears only in shlex-quoted form in the command."""
    quoted_path = shlex.quote(path)
    quoted_header = shlex.quote(f'=== FILE: {path} ===')
    # The raw path must only appear inside shlex-quoted tokens
    # (i.e., it must be present as the quoted form or inside the quoted header)
    if quoted_path not in cmd and quoted_header not in cmd:
        return False
    # After removing all single-quoted segments, dangerous metacharacters
    # from the path must not remain unquoted
    import re
    without_quoted = re.sub(r"'(?:[^'\\]|\\.)*'", '', cmd)
    for meta in ['$(', '`']:
        if meta in path and meta in without_quoted:
            return False
    return True


def test_full_file_read_command_escapes_dangerous_unix_paths():
    for path in _DANGEROUS_PATHS:
        cmd = _build_full_file_read_command(path, use_powershell=False)
        assert _is_safe_unix_command(cmd, path), (
            f'Unsafe command for path {path!r}: {cmd!r}'
        )


def test_partial_file_read_command_escapes_dangerous_unix_paths():
    for path in _DANGEROUS_PATHS:
        for start, end in [(0, 10), (5, -1)]:
            cmd = _build_partial_file_read_command(path, start, end, use_powershell=False)
            assert _is_safe_unix_command(cmd, path), (
                f'Unsafe command for path {path!r} ({start},{end}): {cmd!r}'
            )


def test_full_file_read_command_powershell_unaffected_by_shlex():
    """PowerShell path uses its own escaping – shlex must not interfere."""
    path = 'C:\\Users\\test\\file.py'
    cmd = _build_full_file_read_command(path, use_powershell=True)
    assert 'Get-Content' in cmd
    assert 'shlex' not in cmd  # sanity – shlex itself should never appear in output
