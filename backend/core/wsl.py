"""WSL2 detection and layout helpers for the official supported tier.

Official WSL2 layout:
- Grinta repo + venv on Linux home (not ``/mnt/c``)
- Project workspace may live on a Windows mount (``/mnt/c/...``)
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from enum import Enum
from pathlib import Path, PurePosixPath


class WslLayout(str, Enum):
    """How the Grinta install relates to the active workspace."""

    NOT_WSL = 'not_wsl'
    IDEAL = 'ideal'
    SUPPORTED_SPLIT = 'supported_split'
    REPO_ON_DRVFS = 'repo_on_drvfs'
    BOTH_ON_DRVFS = 'both_on_drvfs'


_DRVFS_SLOW_MS = 200.0
_DEFAULT_TMUX_TMPDIR = '/tmp/grinta-tmux'


def is_wsl_runtime() -> bool:
    """Return True when running under Windows Subsystem for Linux."""
    platform = sys.platform
    if not platform.startswith('linux'):
        return False
    if os.getenv('WSL_DISTRO_NAME') or os.getenv('WSL_INTEROP'):
        return True
    try:
        return 'microsoft' in Path('/proc/version').read_text(encoding='utf-8').lower()
    except OSError:
        return False


def wsl_distro_name() -> str | None:
    """Best-effort WSL distribution label (e.g. ``Ubuntu-24.04``)."""
    name = (os.getenv('WSL_DISTRO_NAME') or '').strip()
    return name or None


def is_windows_mount(path: Path | str) -> bool:
    """True for WSL drvfs paths such as ``/mnt/c/Users/...``."""
    expanded = os.path.expanduser(os.path.expandvars(str(path)))
    normalized = expanded.replace('\\', '/')
    try:
        parts = PurePosixPath(normalized).parts
    except (OSError, ValueError):
        return False
    return len(parts) >= 2 and parts[0] == '/' and parts[1] == 'mnt'


def resolve_grinta_repo_root() -> Path | None:
    """Return ``GRINTA_REPO_ROOT`` when set, else None."""
    raw = (os.getenv('GRINTA_REPO_ROOT') or '').strip()
    if not raw:
        return None
    return Path(raw)


def classify_wsl_layout(
    *,
    workspace: Path | str,
    repo_root: Path | str | None = None,
) -> WslLayout:
    """Classify install layout for doctor/TUI preflight."""
    if not is_wsl_runtime():
        return WslLayout.NOT_WSL

    ws = Path(workspace).expanduser()
    repo = Path(repo_root).expanduser() if repo_root is not None else None
    if repo is None:
        env_repo = resolve_grinta_repo_root()
        if env_repo is not None:
            repo = env_repo

    ws_drvfs = is_windows_mount(ws)
    repo_drvfs = is_windows_mount(repo) if repo is not None else False

    if repo_drvfs:
        return WslLayout.BOTH_ON_DRVFS if ws_drvfs else WslLayout.REPO_ON_DRVFS
    if ws_drvfs:
        return WslLayout.SUPPORTED_SPLIT
    return WslLayout.IDEAL


def measure_mount_latency(
    path: Path | str, *, min_ms_to_report: float = 50.0
) -> float | None:
    """Measure a small write/delete on *path*; return latency in ms or None on failure."""
    target = Path(path)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    if not target.is_dir():
        return None

    started = time.perf_counter()
    try:
        with tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            dir=target,
            prefix='.grinta-mount-probe-',
            delete=False,
        ) as handle:
            handle.write('probe')
            probe_path = Path(handle.name)
        probe_path.unlink(missing_ok=True)
    except OSError:
        return None

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if elapsed_ms < min_ms_to_report:
        return elapsed_ms
    return elapsed_ms


def is_drvfs_slow(path: Path | str, *, threshold_ms: float = _DRVFS_SLOW_MS) -> bool:
    """Return True when *path* is on a Windows mount and I/O looks slow."""
    if not is_windows_mount(path):
        return False
    latency = measure_mount_latency(path)
    return latency is not None and latency >= threshold_ms


def recommended_repo_path_hint() -> str:
    return '~/Grinta'


def default_tmux_tmpdir() -> str:
    """Return the default tmux socket directory on WSL."""
    return _DEFAULT_TMUX_TMPDIR


def ensure_tmux_tmpdir() -> str:
    """Create ``TMUX_TMPDIR`` on WSL so tmux is ready before the first shell session."""
    if not is_wsl_runtime():
        return os.environ.get('TMUX_TMPDIR', '').strip()

    tmpdir = os.environ.get('TMUX_TMPDIR', '').strip() or _DEFAULT_TMUX_TMPDIR
    os.environ['TMUX_TMPDIR'] = tmpdir
    os.makedirs(tmpdir, mode=0o700, exist_ok=True)
    if not os.access(tmpdir, os.W_OK):
        raise OSError(f'TMUX_TMPDIR not writable: {tmpdir}')
    return tmpdir


__all__ = [
    'WslLayout',
    'classify_wsl_layout',
    'default_tmux_tmpdir',
    'ensure_tmux_tmpdir',
    'is_drvfs_slow',
    'is_windows_mount',
    'is_wsl_runtime',
    'measure_mount_latency',
    'recommended_repo_path_hint',
    'resolve_grinta_repo_root',
    'wsl_distro_name',
]
