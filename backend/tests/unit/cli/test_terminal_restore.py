"""Unit tests for terminal mode restoration."""

from __future__ import annotations

import io
import signal
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from backend.cli import terminal_restore as tr


@pytest.fixture(autouse=True)
def _reset_terminal_restore_state() -> None:
    tr.uninstall_terminal_restore_hooks()
    tr.set_console_restore_callback(None)
    tr._active_tui_app = None
    tr._hooks_installed = False
    yield
    tr.uninstall_terminal_restore_hooks()
    tr.set_console_restore_callback(None)
    tr._active_tui_app = None
    tr._hooks_installed = False


def test_terminal_restore_sequences_contains_disable_codes() -> None:
    seq = tr.terminal_restore_sequences()
    for token in (
        '1000l',
        '1002l',
        '1003l',
        '1006l',
        '1015l',
        '2004l',
        '1049l',
        '?25h',
    ):
        assert token in seq


def test_restore_terminal_modes_writes_to_stdout(monkeypatch) -> None:
    buffer = io.StringIO()
    monkeypatch.setattr(tr.sys, '__stdout__', buffer)
    tr.restore_terminal_modes()
    assert buffer.getvalue() == tr.terminal_restore_sequences()


def test_restore_terminal_modes_invokes_console_callback(monkeypatch) -> None:
    buffer = io.StringIO()
    monkeypatch.setattr(tr.sys, '__stdout__', buffer)
    called: list[str] = []

    def _restore() -> None:
        called.append('ok')

    tr.set_console_restore_callback(_restore)
    tr.restore_terminal_modes()
    assert called == ['ok']


def test_restore_terminal_modes_is_idempotent_under_reentry(monkeypatch) -> None:
    buffer = io.StringIO()
    monkeypatch.setattr(tr.sys, '__stdout__', buffer)

    def _nested_restore() -> None:
        tr.restore_terminal_modes(flush=False)

    tr.set_console_restore_callback(_nested_restore)
    tr.restore_terminal_modes()
    assert buffer.getvalue().count('1000l') == 1


def test_capture_driver_console_restore_binds_callback() -> None:
    driver = MagicMock()
    driver._restore_console = MagicMock()
    tr.capture_driver_console_restore(driver)
    restore_cb = tr._console_restore_callback
    assert restore_cb is driver._restore_console


def test_restore_textual_driver_calls_stop_and_close() -> None:
    driver = MagicMock()
    driver._restore_console = MagicMock()
    tr.restore_textual_driver(driver)
    driver.stop_application_mode.assert_called_once()
    driver.close.assert_called_once()


def test_install_and_uninstall_signal_hooks_round_trip() -> None:
    prior = signal.getsignal(signal.SIGINT)
    tr.install_terminal_restore_hooks()
    assert signal.getsignal(signal.SIGINT) is not prior
    tr.uninstall_terminal_restore_hooks()
    assert signal.getsignal(signal.SIGINT) is prior


def test_signal_handler_restores_before_chaining(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        tr, 'restore_terminal_modes', lambda **_: calls.append('restore')
    )
    tr._prior_signal_handlers[signal.SIGINT] = lambda _signum, _frame: None
    tr._chain_signal_handler(signal.SIGINT, None)
    assert calls == ['restore']


def test_terminal_restore_guard_restores_on_exit(monkeypatch) -> None:
    buffer = io.StringIO()
    monkeypatch.setattr(tr.sys, '__stdout__', buffer)
    restore_calls: list[int] = []
    monkeypatch.setattr(
        tr,
        'restore_terminal_modes',
        lambda **_: restore_calls.append(1),
    )

    with tr.terminal_restore_guard():
        assert tr._hooks_installed
    assert restore_calls == [1]
    assert not tr._hooks_installed


@pytest.mark.asyncio
async def test_run_tui_uses_terminal_restore_guard(monkeypatch) -> None:
    from backend.cli.tui import main as tui_main

    entered: list[int] = []
    exited: list[int] = []

    class _Guard:
        def __enter__(self):
            entered.append(1)
            return self

        def __exit__(self, *args):
            exited.append(1)

    config = MagicMock()
    llm_config = MagicMock()
    llm_config.model = 'openai/gpt-4o'
    config.get_llm_config.return_value = llm_config
    type(config).project_root = PropertyMock(return_value=None)

    monkeypatch.setattr(tui_main, 'terminal_restore_guard', lambda app: _Guard())
    monkeypatch.setattr(
        tui_main.GrintaTUIApp,
        'run_async',
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        'backend.utils.async_helpers.async_utils.drain_background_tasks',
        AsyncMock(),
    )

    console = MagicMock()
    await tui_main.run_tui(config, console)
    assert entered == [1]
    assert exited == [1]
