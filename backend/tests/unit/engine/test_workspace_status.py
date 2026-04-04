from unittest.mock import patch

from backend.engine.tools.workspace_status import (
    _build_diff_action,
    _build_status_action,
)


def test_status_action_uses_bash_on_windows_when_bash_available():
    with (
        patch('backend.engine.tools.prompt.sys.platform', 'win32'),
        patch(
            'backend.engine.tools.prompt.shutil.which',
            return_value=r'C:\Program Files\Git\bin\bash.exe',
        ),
    ):
        action = _build_status_action({})

    assert 'find . -maxdepth' in action.command
    assert 'Get-ChildItem' not in action.command


def test_status_action_uses_powershell_when_windows_has_no_bash():
    with (
        patch('backend.engine.tools.prompt.sys.platform', 'win32'),
        patch('backend.engine.tools.prompt.shutil.which', return_value=None),
    ):
        action = _build_status_action({})

    assert 'Get-ChildItem' in action.command
    assert 'find . -maxdepth' not in action.command


def test_diff_action_uses_powershell_when_windows_has_no_bash():
    with (
        patch('backend.engine.tools.prompt.sys.platform', 'win32'),
        patch('backend.engine.tools.prompt.shutil.which', return_value=None),
    ):
        action = _build_diff_action({})

    assert "Write-Output '=== SESSION CHANGES ==='" in action.command
    assert '2>$null' in action.command
