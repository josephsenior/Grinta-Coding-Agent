"""Ensure Linux host tools Grinta expects (tmux binary; libtmux via pip)."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Sequence

from backend.core.logging.logger import app_logger as logger

_SKIP_ENV = 'GRINTA_SKIP_HOST_TOOL_INSTALL'


@dataclass(frozen=True)
class HostToolInstallResult:
    """Outcome of a Linux host-tool ensure pass."""

    tmux_installed: bool
    libtmux_available: bool
    attempted_install: bool
    message: str


def _skip_install() -> bool:
    return os.getenv(_SKIP_ENV, '').strip().lower() in {'1', 'true', 'yes', 'on'}


def is_linux_host() -> bool:
    return sys.platform.startswith('linux')


def _has_libtmux() -> bool:
    return importlib.util.find_spec('libtmux') is not None


def _detect_linux_package_manager() -> str | None:
    if shutil.which('apt-get'):
        return 'apt'
    if shutil.which('dnf'):
        return 'dnf'
    if shutil.which('yum'):
        return 'yum'
    if shutil.which('apk'):
        return 'apk'
    if shutil.which('pacman'):
        return 'pacman'
    if shutil.which('zypper'):
        return 'zypper'
    return None


def _install_command_variants(pm: str) -> list[list[str]]:
    if pm == 'apt':
        return [
            [
                'sudo',
                '-n',
                'env',
                'DEBIAN_FRONTEND=noninteractive',
                'apt-get',
                'install',
                '-y',
                'tmux',
            ],
            [
                'env',
                'DEBIAN_FRONTEND=noninteractive',
                'apt-get',
                'install',
                '-y',
                'tmux',
            ],
            [
                'sudo',
                'env',
                'DEBIAN_FRONTEND=noninteractive',
                'apt-get',
                'install',
                '-y',
                'tmux',
            ],
        ]
    if pm in {'dnf', 'yum'}:
        return [
            ['sudo', '-n', pm, 'install', '-y', 'tmux'],
            [pm, 'install', '-y', 'tmux'],
            ['sudo', pm, 'install', '-y', 'tmux'],
        ]
    if pm == 'apk':
        return [
            ['sudo', '-n', 'apk', 'add', '--no-cache', 'tmux'],
            ['apk', 'add', '--no-cache', 'tmux'],
            ['sudo', 'apk', 'add', '--no-cache', 'tmux'],
        ]
    if pm == 'pacman':
        return [
            ['sudo', '-n', 'pacman', '-S', '--noconfirm', 'tmux'],
            ['pacman', '-S', '--noconfirm', 'tmux'],
            ['sudo', 'pacman', '-S', '--noconfirm', 'tmux'],
        ]
    if pm == 'zypper':
        return [
            ['sudo', '-n', 'zypper', 'install', '-y', 'tmux'],
            ['zypper', 'install', '-y', 'tmux'],
            ['sudo', 'zypper', 'install', '-y', 'tmux'],
        ]
    return []


def _interactive_install_allowed() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _run_install(cmd: Sequence[str]) -> bool:
    try:
        result = subprocess.run(
            list(cmd),
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0:
            return True
        detail = (result.stderr or result.stdout or '').strip()
        if detail:
            logger.debug('Host tool install failed (%s): %s', ' '.join(cmd), detail)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug('Host tool install error (%s): %s', ' '.join(cmd), exc)
    return False


def ensure_linux_host_tools(*, install_tmux: bool = True) -> HostToolInstallResult:
    """Ensure tmux is on PATH on Linux and libtmux is importable."""
    if not is_linux_host():
        return HostToolInstallResult(
            tmux_installed=shutil.which('tmux') is not None,
            libtmux_available=_has_libtmux(),
            attempted_install=False,
            message='not a Linux host',
        )

    libtmux_ok = _has_libtmux()
    if not libtmux_ok:
        logger.warning(
            'libtmux Python package is missing; reinstall Grinta to restore shell support.'
        )

    if shutil.which('tmux'):
        return HostToolInstallResult(
            tmux_installed=True,
            libtmux_available=libtmux_ok,
            attempted_install=False,
            message='tmux already available',
        )

    if _skip_install() or not install_tmux:
        return HostToolInstallResult(
            tmux_installed=False,
            libtmux_available=libtmux_ok,
            attempted_install=False,
            message='tmux missing (install skipped or disabled)',
        )

    pm = _detect_linux_package_manager()
    if pm is None:
        logger.warning(
            'tmux not found and no supported package manager detected. '
            'Install tmux manually (e.g. sudo apt install tmux).'
        )
        return HostToolInstallResult(
            tmux_installed=False,
            libtmux_available=libtmux_ok,
            attempted_install=False,
            message='tmux missing; unsupported package manager',
        )

    attempted = False
    for cmd in _install_command_variants(pm):
        if cmd[0] == 'sudo' and cmd[1] != '-n' and not _interactive_install_allowed():
            continue
        attempted = True
        logger.info('Installing tmux via: %s', ' '.join(cmd))
        if _run_install(cmd) and shutil.which('tmux'):
            logger.info('tmux installed successfully.')
            return HostToolInstallResult(
                tmux_installed=True,
                libtmux_available=libtmux_ok,
                attempted_install=True,
                message='tmux installed',
            )

    logger.warning(
        'tmux is not installed and automatic installation failed. '
        'Run: sudo apt install tmux (or your distro equivalent).'
    )
    return HostToolInstallResult(
        tmux_installed=False,
        libtmux_available=libtmux_ok,
        attempted_install=attempted,
        message='tmux missing; automatic install failed',
    )


__all__ = [
    'HostToolInstallResult',
    'ensure_linux_host_tools',
    'is_linux_host',
]
