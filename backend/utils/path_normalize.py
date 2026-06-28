r"""Cross-platform path normalization for MSYS/Git Bash on Windows.

When Grinta runs under Git Bash (MSYS2/MINGW) on Windows, paths and PATH
environment variables can leak between MSYS-format (``/c/Users/...``, ``:``
separators) and Windows-native format (``C:\\Users\\...``, ``;`` separators).
The standard library never translates across this boundary — ``shutil.which``
returns whatever the PATH format yields, and ``subprocess.Popen`` expects
Windows-native paths on ``os.name == 'nt'``.

This module provides the conversion utilities that native tool spawn sites
(LSP servers, DAP adapters) use to ensure paths are in the correct format
before being passed to ``subprocess.Popen`` or ``Path.is_file()``.
"""

from __future__ import annotations

import os
import re

_MSYS_DRIVE_RE = re.compile(r'^/([a-zA-Z])/(.*)$')


def is_msys_path(path: str) -> bool:
    """Return True when *path* is an MSYS/Git Bash mount-style path.

    Matches ``/<drive>/...`` (e.g. ``/c/Users/foo``, ``/d/projects``).
    Does NOT match ``/usr/...``, ``/tmp/...``, or POSIX-only paths that
    have no Windows drive equivalent.
    """
    if not path or not path.startswith('/'):
        return False
    return _MSYS_DRIVE_RE.match(path) is not None


def msys_to_windows_path(path: str) -> str:
    r"""Convert a single MSYS mount-style path to a Windows-native path.

    ``/c/Users/foo`` → ``C:\Users\foo``
    ``/d/projects/x`` → ``D:\projects\x``

    Paths that are already Windows-native or have no drive-letter mapping
    (e.g. ``/usr/bin``) are returned unchanged.
    """
    if not path:
        return path
    match = _MSYS_DRIVE_RE.match(path)
    if match is None:
        return path
    drive = match.group(1).upper()
    rest = match.group(2)
    if rest:
        return f'{drive}:\\{rest.replace("/", os.sep)}'
    return f'{drive}:\\'


def to_native_path(path: str | os.PathLike[str]) -> str:
    r"""Normalize *path* to the platform-native format.

    On Windows (``os.name == 'nt'``):
      - MSYS mount paths (``/c/Users/...``) are converted to ``C:\Users\...``
      - Forward slashes in Windows paths are preserved (``subprocess.Popen``
        accepts them; ``Path`` handles them)

    On POSIX: returned as-is (MSYS paths are native there).

    This is the function spawn sites should call before passing a path to
    ``subprocess.Popen``, ``Path.is_file()``, or ``shutil.which`` results.
    """
    text = str(path)
    if os.name != 'nt':
        return text
    return msys_to_windows_path(text)


def normalize_path_env(path_var: str | None) -> str:
    """Normalize a PATH environment variable to the platform-native format.

    On Windows, MSYS/Git Bash uses ``:`` separators and MSYS-style paths.
    Native Windows uses ``;`` separators and Windows-style paths. This
    function splits on whichever separator is present, converts each
    entry to a Windows path, and rejoins with ``;``.

    On POSIX: returned as-is.
    """
    if path_var is None:
        return ''
    if os.name != 'nt':
        return path_var

    raw = path_var.strip()
    if not raw:
        return ''

    if ';' in raw:
        entries = raw.split(';')
    elif ':' in raw:
        entries = raw.split(':')
    else:
        entries = [raw]

    normalized: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
        converted = msys_to_windows_path(entry)
        if converted not in seen:
            seen.add(converted)
            normalized.append(converted)

    return ';'.join(normalized)


def get_native_path_env() -> str:
    """Return ``os.environ['PATH']`` normalized to the platform-native format."""
    return normalize_path_env(os.environ.get('PATH', ''))


def which_normalized(name: str) -> str | None:
    """``shutil.which`` with MSYS-to-Windows path normalization on the result.

    Uses a normalized PATH so that MSYS-format PATH entries are properly
    resolved. The returned path is guaranteed to be in Windows-native format
    on Windows.
    """
    import shutil

    original_path = os.environ.get('PATH', '')
    normalized = normalize_path_env(original_path)
    if normalized != original_path:
        saved = os.environ.get('PATH')
        os.environ['PATH'] = normalized
        try:
            result = shutil.which(name)
        finally:
            if saved is not None:
                os.environ['PATH'] = saved
            else:
                os.environ.pop('PATH', None)
    else:
        result = shutil.which(name)

    if result is None:
        return None
    return to_native_path(result)


__all__ = [
    'get_native_path_env',
    'is_msys_path',
    'msys_to_windows_path',
    'normalize_path_env',
    'to_native_path',
    'which_normalized',
]
