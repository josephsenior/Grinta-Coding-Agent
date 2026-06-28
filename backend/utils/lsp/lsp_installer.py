"""Auto-installation of canonical LSP servers (global scope).

When ``GRINTA_LSP_AUTO_INSTALL`` is not ``"0"`` (default: on) and the
canonical server for a language is missing, :func:`install_server` runs the
server's ``install`` command via the appropriate package manager.

Install strategy: **global**.  One install per machine serves all projects
(``npm install -g``, ``gem install``, ``rustup component add``,
``go install``, ``dotnet tool install -g``, ``pip install``).  This matches
the default mode of every supported package manager, avoids per-project
re-installs, and works for tools that have no per-workspace equivalent
(rustup components, gem, cargo binaries).  No per-workspace sandboxing.

Per-server locks prevent double-install on concurrent queries.  Successful
installs are remembered for the session so we never re-install.  Failed
installs are also remembered so we don't retry every query.
"""

from __future__ import annotations

import os
import subprocess
import threading

from backend.core.logging.logger import app_logger as logger
from backend.utils.path_normalize import which_normalized

# Package-manager binary for each install_method.
_PREREQ_TOOLS: dict[str, str] = {
    'npm': 'npm',
    'pip': 'pip',
    'pip3': 'pip3',
    'go': 'go',
    'cargo': 'cargo',
    'gem': 'gem',
    'rustup': 'rustup',
    'dotnet': 'dotnet',
    'cpan': 'cpan',
}

_lock = threading.Lock()
_installed: set[str] = set()
_failed: set[str] = set()


def is_auto_install_enabled() -> bool:
    """True when auto-install is not explicitly disabled via env var."""
    return os.getenv('GRINTA_LSP_AUTO_INSTALL') != '0'


def _check_prereq(method: str) -> bool:
    """Return True if the package manager for *method* is on PATH."""
    tool = _PREREQ_TOOLS.get(method)
    if tool is None:
        return False
    return which_normalized(tool) is not None


def install_server(
    spec_name: str,
    install_command: tuple[str, ...] | None,
    install_method: str,
    *,
    timeout: float = 120.0,
) -> bool:
    """Install a single LSP server. Returns True on success.

    Thread-safe — concurrent calls for the same server name block on a
    shared lock and the second caller sees the result of the first.
    """
    if install_command is None:
        logger.info(
            'LSP auto-install: %s has no install command (method=%s)',
            spec_name,
            install_method,
        )
        return False

    if not _check_prereq(install_method):
        logger.info(
            'LSP auto-install: %s requires %s which is not on PATH',
            spec_name,
            install_method,
        )
        return False

    with _lock:
        if spec_name in _installed:
            return True
        if spec_name in _failed:
            return False

        logger.info(
            'LSP auto-install: installing %s via %s...',
            spec_name,
            install_method,
        )
        try:
            result = subprocess.run(
                list(install_command),
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                'LSP auto-install: %s timed out after %ss',
                spec_name,
                timeout,
            )
            _failed.add(spec_name)
            return False
        except OSError as exc:
            logger.warning('LSP auto-install: %s failed: %r', spec_name, exc)
            _failed.add(spec_name)
            return False

        if result.returncode != 0:
            stderr = (
                result.stderr.decode('utf-8', errors='replace')[-500:]
                if result.stderr
                else ''
            )
            logger.warning(
                'LSP auto-install: %s failed (rc=%d): %s',
                spec_name,
                result.returncode,
                stderr,
            )
            _failed.add(spec_name)
            return False

        _installed.add(spec_name)
        logger.info('LSP auto-install: %s installed successfully', spec_name)
        return True


def was_installed(spec_name: str) -> bool:
    """True when *spec_name* was installed during this session."""
    return spec_name in _installed


def reset_install_cache() -> None:
    """Clear install caches (used by tests)."""
    with _lock:
        _installed.clear()
        _failed.clear()
