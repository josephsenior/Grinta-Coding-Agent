"""Tests for Windows ConPTY console stdin guards."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.cli import win32_console as wc


@pytest.fixture(autouse=True)
def _reset_guard_state() -> None:
    wc._kernel32 = None
    wc._unhook = None
    yield
    if wc._unhook is not None:
        wc.win32_uninstall_ctrl_c_guard()
    wc._kernel32 = None
    wc._unhook = None


def test_disable_processed_input_noop_off_windows(monkeypatch) -> None:
    monkeypatch.setattr(wc.sys, 'platform', 'linux')
    wc.win32_disable_processed_input()


def test_disable_processed_input_clears_flag(monkeypatch) -> None:
    monkeypatch.setattr(wc.sys, 'platform', 'win32')
    monkeypatch.setattr(wc.sys.stdin, 'isatty', lambda: True)

    kernel32 = MagicMock()
    kernel32.GetStdHandle.return_value = 7
    monkeypatch.setattr(wc, '_load_kernel32', lambda: kernel32)
    monkeypatch.setattr(
        wc,
        '_read_console_mode',
        lambda _kernel32, _handle: wc.ENABLE_PROCESSED_INPUT | 0x100,
    )

    wc.win32_disable_processed_input()

    kernel32.SetConsoleMode.assert_called_once_with(7, 0x100)


def test_flush_input_buffer_calls_api(monkeypatch) -> None:
    monkeypatch.setattr(wc.sys, 'platform', 'win32')
    monkeypatch.setattr(wc.sys.stdin, 'isatty', lambda: True)

    kernel32 = MagicMock()
    kernel32.GetStdHandle.return_value = 9
    kernel32.FlushConsoleInputBuffer = MagicMock()
    monkeypatch.setattr(wc, '_load_kernel32', lambda: kernel32)

    wc.win32_flush_input_buffer()

    kernel32.FlushConsoleInputBuffer.assert_called_once_with(9)


def test_install_guard_restores_initial_mode(monkeypatch) -> None:
    monkeypatch.setattr(wc.sys, 'platform', 'win32')
    monkeypatch.setattr(wc.sys.stdin, 'isatty', lambda: True)

    initial = wc.ENABLE_PROCESSED_INPUT | 0x200
    kernel32 = MagicMock()
    kernel32.GetStdHandle.return_value = 3
    monkeypatch.setattr(wc, '_load_kernel32', lambda: kernel32)
    monkeypatch.setattr(wc, '_read_console_mode', lambda _k, _h: initial)
    monkeypatch.setattr(wc.threading, 'Timer', lambda _delay, fn: fn())

    unhook = wc.win32_install_ctrl_c_guard()
    assert unhook is not None
    assert kernel32.SetConsoleMode.called

    unhook()
    last_mode = kernel32.SetConsoleMode.call_args_list[-1].args[1]
    assert last_mode == initial


def test_console_input_guard_context_manager(monkeypatch) -> None:
    calls: list[str] = []

    def _fake_install() -> object:
        calls.append('install')
        return _unhook

    def _unhook() -> None:
        calls.append('unhook')

    monkeypatch.setattr(wc, 'win32_disable_processed_input', lambda: calls.append('disable'))
    monkeypatch.setattr(wc, 'win32_install_ctrl_c_guard', _fake_install)

    with wc.win32_console_input_guard():
        assert calls == ['disable', 'install']

    assert calls == ['disable', 'install', 'unhook']
