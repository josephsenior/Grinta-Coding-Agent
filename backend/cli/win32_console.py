"""Windows ConPTY console stdin guards.

Ported from OpenCode ``win32.ts``.  On Windows, ``ENABLE_PROCESSED_INPUT`` on the
console stdin handle can cause Ctrl+C and mouse/key events to be interpreted in
ways that leak raw SGR mouse reports into focused TUI widgets.  We keep that
flag cleared for the TUI session and periodically re-enforce it because other
runtimes (Textual, ConPTY) may re-apply console modes asynchronously.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

STD_INPUT_HANDLE = -10
ENABLE_PROCESSED_INPUT = 0x0001

_kernel32: Any | None = None
_unhook: Callable[[], None] | None = None


def _platform_ready() -> bool:
    return sys.platform == 'win32' and sys.stdin is not None and sys.stdin.isatty()


def _load_kernel32() -> Any | None:
    global _kernel32
    if sys.platform != 'win32':
        return None
    if _kernel32 is not None:
        return _kernel32
    try:
        import ctypes

        _kernel32 = ctypes.windll.kernel32
    except Exception:
        _kernel32 = None
    return _kernel32


def _stdin_handle(kernel32: Any) -> Any:
    return kernel32.GetStdHandle(STD_INPUT_HANDLE)


def _read_console_mode(kernel32: Any, handle: Any) -> int | None:
    import ctypes

    mode = ctypes.c_uint32()
    if kernel32.GetConsoleMode(handle, ctypes.byref(mode)) == 0:
        return None
    return int(mode.value)


def _write_console_mode(kernel32: Any, handle: Any, mode: int) -> None:
    try:
        kernel32.SetConsoleMode(handle, mode)
    except Exception:
        pass


def win32_disable_processed_input() -> None:
    """Clear ``ENABLE_PROCESSED_INPUT`` on the console stdin handle."""
    if not _platform_ready():
        return
    kernel32 = _load_kernel32()
    if kernel32 is None:
        return
    handle = _stdin_handle(kernel32)
    mode = _read_console_mode(kernel32, handle)
    if mode is None or (mode & ENABLE_PROCESSED_INPUT) == 0:
        return
    _write_console_mode(kernel32, handle, mode & ~ENABLE_PROCESSED_INPUT)


def win32_flush_input_buffer() -> None:
    """Discard queued console input (mouse events, key presses, etc.)."""
    if not _platform_ready():
        return
    kernel32 = _load_kernel32()
    if kernel32 is None:
        return
    handle = _stdin_handle(kernel32)
    flush = getattr(kernel32, 'FlushConsoleInputBuffer', None)
    if callable(flush):
        try:
            flush(handle)
        except Exception:
            pass


def win32_install_ctrl_c_guard() -> Callable[[], None] | None:
    """Keep ``ENABLE_PROCESSED_INPUT`` disabled for the active TUI session."""
    global _unhook
    if not _platform_ready():
        return None
    kernel32 = _load_kernel32()
    if kernel32 is None:
        return None
    if _unhook is not None:
        return _unhook

    handle = _stdin_handle(kernel32)
    initial = _read_console_mode(kernel32, handle)
    if initial is None:
        return None

    def _enforce() -> None:
        mode = _read_console_mode(kernel32, handle)
        if mode is None or (mode & ENABLE_PROCESSED_INPUT) == 0:
            return
        _write_console_mode(kernel32, handle, mode & ~ENABLE_PROCESSED_INPUT)

    def _enforce_later() -> None:
        _enforce()
        try:
            threading.Timer(0.0, _enforce).start()
        except Exception:
            pass

    _enforce_later()

    stop = threading.Event()

    def _poll() -> None:
        while not stop.wait(0.1):
            _enforce()

    thread = threading.Thread(target=_poll, name='grinta-win32-console-guard', daemon=True)
    thread.start()

    def unhook() -> None:
        global _unhook
        if _unhook is None:
            return
        stop.set()
        thread.join(timeout=0.5)
        _write_console_mode(kernel32, handle, initial)
        _unhook = None

    _unhook = unhook
    return unhook


def win32_uninstall_ctrl_c_guard() -> None:
    """Restore console mode and stop the guard thread."""
    if _unhook is not None:
        _unhook()


@contextmanager
def win32_console_input_guard() -> Iterator[None]:
    """Install OpenCode-style Windows stdin guards for a TUI session."""
    win32_disable_processed_input()
    unhook = win32_install_ctrl_c_guard()
    try:
        yield
    finally:
        if unhook is not None:
            unhook()
        elif _unhook is not None:
            win32_uninstall_ctrl_c_guard()
