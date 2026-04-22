from __future__ import annotations

from collections import deque
from typing import cast
from unittest.mock import patch

from backend.engine.file_reads import try_batch_file_reads
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
    assert 'cat "src/repomentor/index.py"' in batched.command
    assert 'cat "src/repomentor/__main__.py"' in batched.command
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
