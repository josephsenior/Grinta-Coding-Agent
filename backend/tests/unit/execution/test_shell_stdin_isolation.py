"""Agent shell sessions must not inherit the interactive TUI stdin."""

from __future__ import annotations

import inspect

import pytest

from backend.core.os_capabilities import OS_CAPS
from backend.execution.utils.shell import simple_bash


def test_simple_bash_subprocess_uses_devnull_stdin() -> None:
    source = inspect.getsource(simple_bash.SimpleBashSession._start_subprocess)
    assert 'stdin=subprocess.DEVNULL' in source
    assert 'stdout=subprocess.PIPE' in source
    assert 'stderr=subprocess.PIPE' in source


@pytest.mark.skipif(not OS_CAPS.is_windows, reason='windows_bash is Windows-only')
def test_windows_bash_subprocess_uses_devnull_stdin_without_input() -> None:
    from backend.execution.utils.shell import windows_bash

    source = inspect.getsource(windows_bash.WindowsPowershellSession._run_command)
    assert 'subprocess.DEVNULL' in source
