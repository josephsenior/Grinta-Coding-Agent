"""Belt-and-suspenders terminal mode restoration for the Grinta TUI.

Textual enables alternate-screen, mouse-tracking, and bracketed-paste modes.
If the process exits without Textual's driver shutdown (crash, wedged loop,
forced termination), those modes can remain active and leak mouse coordinates
into the host shell.  This module writes idempotent disable sequences and
optionally restores Windows ConPTY console flags.

Agent shell commands already run in isolated PTY/subprocess sessions with piped
stdin (not the TUI's stdin); this module addresses the *host* terminal only.
"""

from __future__ import annotations

import atexit
import signal
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

# Idempotent disable sequences — safe to write multiple times.
_TERMINAL_RESTORE_SEQUENCES = (
    '\x1b[?1000l'
    '\x1b[?1002l'
    '\x1b[?1003l'
    '\x1b[?1006l'
    '\x1b[?1015l'
    '\x1b[?2004l'
    '\x1b[?1049l'
    '\x1b[?25h'
)

_restoring = False
_hooks_installed = False
_atexit_registered = False
_prior_signal_handlers: dict[int, Any] = {}
_console_restore_callback: Callable[[], None] | None = None
_active_tui_app: Any | None = None


def terminal_restore_sequences() -> str:
    """Return the raw escape sequence bundle used to reset terminal modes."""
    return _TERMINAL_RESTORE_SEQUENCES


def set_console_restore_callback(callback: Callable[[], None] | None) -> None:
    """Register a Windows ConPTY restore callable from Textual's driver."""
    global _console_restore_callback
    _console_restore_callback = callback


def capture_driver_console_restore(driver: Any | None) -> None:
    """Bind Textual driver ``_restore_console`` when available."""
    if driver is None:
        return
    restore_cb = getattr(driver, '_restore_console', None)
    if callable(restore_cb):
        set_console_restore_callback(restore_cb)


def restore_terminal_modes(*, flush: bool = True) -> None:
    """Write terminal disable sequences; idempotent and must not raise."""
    global _restoring
    if _restoring:
        return
    _restoring = True
    try:
        stdout = sys.__stdout__
        if stdout is not None:
            try:
                stdout.write(_TERMINAL_RESTORE_SEQUENCES)
                if flush:
                    stdout.flush()
            except Exception:
                pass
        callback = _console_restore_callback
        if callback is not None:
            try:
                callback()
            except Exception:
                pass
    finally:
        _restoring = False


def _atexit_restore() -> None:
    if _active_tui_app is not None:
        capture_driver_console_restore(getattr(_active_tui_app, '_driver', None))
    restore_terminal_modes()


def _chain_signal_handler(signum: int, frame: Any | None) -> None:
    restore_terminal_modes()
    prior = _prior_signal_handlers.get(signum)
    if prior is signal.SIG_DFL:
        signal.default_int_handler(signum, frame)
        return
    if prior is signal.SIG_IGN:
        return
    if callable(prior):
        prior(signum, frame)
        return
    if signum == signal.SIGINT:
        raise KeyboardInterrupt


def install_terminal_restore_hooks() -> None:
    """Register atexit and signal handlers for the active TUI session."""
    global _hooks_installed, _atexit_registered
    if _hooks_installed:
        return
    _hooks_installed = True

    if not _atexit_registered:
        atexit.register(_atexit_restore)
        _atexit_registered = True

    for signum in _signal_numbers_to_hook():
        try:
            _prior_signal_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, _chain_signal_handler)
        except (OSError, ValueError, RuntimeError):
            continue


def uninstall_terminal_restore_hooks() -> None:
    """Restore prior signal handlers after a clean TUI shutdown."""
    global _hooks_installed
    if not _hooks_installed:
        return
    _hooks_installed = False

    for signum, prior in list(_prior_signal_handlers.items()):
        try:
            signal.signal(signum, prior)
        except (OSError, ValueError, RuntimeError):
            continue
    _prior_signal_handlers.clear()


def _signal_numbers_to_hook() -> tuple[int, ...]:
    numbers: list[int] = [signal.SIGINT, signal.SIGTERM]
    sigbreak = getattr(signal, 'SIGBREAK', None)
    if isinstance(sigbreak, int):
        numbers.append(sigbreak)
    return tuple(numbers)


def restore_textual_driver(driver: Any | None) -> None:
    """Best-effort Textual driver shutdown when the normal path was skipped."""
    if driver is None:
        return
    capture_driver_console_restore(driver)
    stop = getattr(driver, 'stop_application_mode', None)
    if callable(stop):
        try:
            stop()
        except Exception:
            pass
    close = getattr(driver, 'close', None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


@contextmanager
def terminal_restore_guard(app: Any | None = None) -> Iterator[None]:
    """Install restore hooks for a TUI session and reset modes on exit."""
    global _active_tui_app
    _active_tui_app = app
    install_terminal_restore_hooks()
    try:
        yield
    finally:
        driver = getattr(app, '_driver', None) if app is not None else None
        restore_textual_driver(driver)
        restore_terminal_modes()
        uninstall_terminal_restore_hooks()
        set_console_restore_callback(None)
        _active_tui_app = None
