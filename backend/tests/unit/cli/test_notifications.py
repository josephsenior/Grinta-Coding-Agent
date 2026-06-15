"""Unit tests for desktop notification helpers."""

from __future__ import annotations

import os
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from backend.cli.display import notifications as notify_mod


def test_notifications_disabled_by_env() -> None:
    with patch.dict(os.environ, {'GRINTA_NO_NOTIFY': 'true'}):
        with patch.object(notify_mod, '_do_notify') as mocked:
            notify_mod.notify('t', 'b')
    mocked.assert_not_called()


def test_notify_swallows_errors() -> None:
    with patch.object(notify_mod, '_do_notify', side_effect=RuntimeError('boom')):
        notify_mod.notify('t', 'b')


def test_do_notify_windows_path() -> None:
    with (
        patch('os.name', 'nt'),
        patch.object(notify_mod, '_notify_windows') as win,
    ):
        notify_mod._do_notify('title', 'body', urgency='normal')
    win.assert_called_once_with('title', 'body')


def test_do_notify_macos_path() -> None:
    with (
        patch('os.name', 'posix'),
        patch('shutil.which', side_effect=lambda cmd: '/usr/bin/osascript' if cmd == 'osascript' else None),
        patch.object(notify_mod, '_notify_macos') as mac,
    ):
        notify_mod._do_notify('title', 'body', urgency='normal')
    mac.assert_called_once_with('title', 'body')


def test_do_notify_linux_path() -> None:
    with (
        patch('os.name', 'posix'),
        patch('shutil.which', side_effect=lambda cmd: '/usr/bin/notify-send' if cmd == 'notify-send' else None),
        patch.object(notify_mod, '_notify_linux') as linux,
    ):
        notify_mod._do_notify('title', 'body', urgency='critical')
    linux.assert_called_once_with('title', 'body', urgency='critical')


def test_escape_helpers() -> None:
    assert notify_mod._ps_escape("it's") == "it''s"
    assert notify_mod._applescript_escape('say "hi"') == 'say \\"hi\\"'


def test_notify_agent_idle_and_error() -> None:
    with patch.object(notify_mod, 'notify') as mocked:
        notify_mod.notify_agent_idle(needs_input=True)
        notify_mod.notify_agent_idle(needs_input=False)
        notify_mod.notify_agent_error('boom')
    assert mocked.call_count == 3


def test_notify_windows_runs_powershell_then_msg_fallback() -> None:
    with patch('subprocess.run', side_effect=[RuntimeError('ps'), MagicMock()]) as run:
        notify_mod._notify_windows('t', 'b')
    assert run.call_count == 2


def test_notify_macos_and_linux_invoke_subprocess() -> None:
    with patch('subprocess.run') as run:
        notify_mod._notify_macos('t', 'b')
        notify_mod._notify_linux('t', 'b', urgency='low')
    assert run.call_count == 2
