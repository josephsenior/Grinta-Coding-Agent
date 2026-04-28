"""Centralised OS capability detection.

Grinta's design principle is OS-agnosticism: features should work on
Windows, Linux and macOS with equivalent capability whenever the
underlying platform allows. To avoid scattering ``os.name == 'nt'`` and
``sys.platform == 'win32'`` checks across the codebase (which mix the two
detection methods inconsistently and make it hard to understand the full
matrix of supported platforms), all platform-conditional behaviour should
go through :data:`OS_CAPS` exposed from this module.

The capability object is **immutable** and computed once at import time.
For testing, use :func:`override_os_capabilities` (a context manager) to
swap in a synthetic profile.
"""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

ShellKind = Literal['powershell', 'cmd', 'bash', 'zsh', 'sh']
SignalStrategy = Literal['posix', 'windows']


@dataclass(frozen=True)
class OSCapabilities:
    """Immutable snapshot of OS-level capabilities.

    Use the boolean flags (``is_windows`` / ``is_posix`` / ``is_macos``) for
    coarse branching; prefer the higher-level capability fields
    (``supports_pty``, ``signal_strategy``, ``shell_kind``,
    ``default_python_exec``, ``path_sep``) for behaviour decisions so
    individual call sites describe *what* they need rather than *which OS*
    they detect.
    """

    is_windows: bool
    is_posix: bool
    is_linux: bool
    is_macos: bool
    shell_kind: ShellKind
    supports_pty: bool
    signal_strategy: SignalStrategy
    path_sep: str
    default_python_exec: str
    sys_platform: str
    os_name: str

    @property
    def supports_posix_sandbox(self) -> bool:
        """True when a POSIX-style sandbox (firejail, sandbox-exec) can run."""
        return self.is_linux or self.is_macos


def _detect_shell_kind() -> ShellKind:
    if os.name == 'nt':
        # Default to powershell on Windows; the engine.tools.prompt module
        # has a richer "uses_powershell_terminal" override for cases where
        # Git Bash is in use, but for general capability reporting
        # PowerShell is the safer default contract.
        return 'powershell'
    shell = os.environ.get('SHELL', '').rsplit('/', 1)[-1]
    if shell in ('bash', 'zsh', 'sh'):
        return shell  # type: ignore[return-value]
    return 'bash'


def _detect_supports_pty() -> bool:
    if os.name == 'nt':
        # Windows lacks ``os.openpty`` / ``pty.fork``; consumers should
        # fall back to ConPTY-based session helpers or pipe-based shells.
        return False
    try:
        import pty  # noqa: F401, PLC0415

        return True
    except ImportError:  # pragma: no cover - pty ships with CPython on POSIX
        return False


def _detect_default_python() -> str:
    """Return the canonical python executable name for the active shell."""
    if os.name == 'nt':
        return 'python'
    return 'python3'


def detect_os_capabilities() -> OSCapabilities:
    """Compute capabilities from the live process environment.

    Pure function — safe to call repeatedly. Production code should use
    the cached :data:`OS_CAPS` instead.
    """
    is_windows = sys.platform == 'win32' or os.name == 'nt'
    is_macos = sys.platform == 'darwin'
    is_linux = sys.platform.startswith('linux')
    is_posix = os.name == 'posix'

    return OSCapabilities(
        is_windows=is_windows,
        is_posix=is_posix,
        is_linux=is_linux,
        is_macos=is_macos,
        shell_kind=_detect_shell_kind(),
        supports_pty=_detect_supports_pty(),
        signal_strategy='windows' if is_windows else 'posix',
        path_sep=os.sep,
        default_python_exec=_detect_default_python(),
        sys_platform=sys.platform,
        os_name=os.name,
    )


# Module-level cached capability snapshot. Most callers should use this
# directly: ``from backend.core.os_capabilities import OS_CAPS``.
OS_CAPS: OSCapabilities = detect_os_capabilities()


# --- Convenience aliases -----------------------------------------------------
#
# These mirror the most common predicates so call sites read naturally:
#   ``if is_windows():`` rather than ``if OS_CAPS.is_windows:``.
# Both forms are supported; pick whichever feels more readable in context.


def is_windows() -> bool:
    """Convenience wrapper around ``OS_CAPS.is_windows``."""
    return OS_CAPS.is_windows


def is_posix() -> bool:
    """Convenience wrapper around ``OS_CAPS.is_posix``."""
    return OS_CAPS.is_posix


def is_macos() -> bool:
    """Convenience wrapper around ``OS_CAPS.is_macos``."""
    return OS_CAPS.is_macos


def is_linux() -> bool:
    """Convenience wrapper around ``OS_CAPS.is_linux``."""
    return OS_CAPS.is_linux


# --- Test helper -------------------------------------------------------------


@contextlib.contextmanager
def override_os_capabilities(caps: OSCapabilities) -> Iterator[None]:
    """Temporarily swap :data:`OS_CAPS` for tests.

    Mutates the existing :data:`OS_CAPS` instance in place so that modules
    which captured the binding via ``from ... import OS_CAPS`` observe the
    override. Not safe under concurrent execution; tests using this should
    be marked single-threaded.
    """
    fields = (
        'is_windows',
        'is_posix',
        'is_linux',
        'is_macos',
        'shell_kind',
        'supports_pty',
        'signal_strategy',
        'path_sep',
        'default_python_exec',
        'sys_platform',
        'os_name',
    )
    previous = {name: getattr(OS_CAPS, name) for name in fields}
    for name in fields:
        object.__setattr__(OS_CAPS, name, getattr(caps, name))
    try:
        yield
    finally:
        for name, value in previous.items():
            object.__setattr__(OS_CAPS, name, value)
