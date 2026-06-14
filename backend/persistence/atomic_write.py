"""Shared atomic-replace helpers for local filesystem writes."""

from __future__ import annotations

import os
import stat
import time
from pathlib import Path


def _make_writable(path: str) -> None:
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


def replace_file_with_retry(tmp_path: str | Path, full_path: str | Path) -> None:
    """Atomically replace *full_path* with *tmp_path*, tolerating transient locks."""
    tmp = os.fspath(tmp_path)
    dest = os.fspath(full_path)
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            if os.path.exists(dest):
                _make_writable(dest)
            os.replace(tmp, dest)
            return
        except FileNotFoundError:
            raise
        except PermissionError as exc:
            last_error = exc
            if os.path.exists(dest):
                _make_writable(dest)
            time.sleep(0.05 * (attempt + 1))
        except OSError as exc:
            last_error = exc
            if os.path.exists(dest):
                _make_writable(dest)
            time.sleep(0.05 * (attempt + 1))
    if last_error is not None:
        raise last_error
