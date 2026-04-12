"""Portable launcher entry for `grinta`.

This avoids module-name collisions when users launch from repositories that
also contain a top-level `backend/` package.
"""

from __future__ import annotations

import importlib
import importlib.metadata as metadata
import json
import runpy
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


def _editable_project_root() -> Path | None:
    """Resolve editable project root from distribution metadata when available."""
    try:
        dist = metadata.distribution('grinta-ai')
    except metadata.PackageNotFoundError:
        return None

    raw = dist.read_text('direct_url.json')
    if not raw:
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None

    url = str(payload.get('url', '')).strip()
    if not url.lower().startswith('file://'):
        return None

    parsed = urlparse(url)
    path = unquote(parsed.path or '')

    # Normalize Windows file:// URLs like /C:/Users/... to C:/Users/...
    if len(path) >= 3 and path[0] == '/' and path[2] == ':':
        path = path[1:]

    root = Path(path)
    return root if root.exists() else None


def _resolve_entry_file() -> Path | None:
    """Find backend/cli/entry.py without relying on import precedence."""
    root = _editable_project_root()
    if root is not None:
        editable_entry = root / 'backend' / 'cli' / 'entry.py'
        if editable_entry.exists():
            return editable_entry

    try:
        dist = metadata.distribution('grinta-ai')
    except metadata.PackageNotFoundError:
        return None

    wheel_entry = Path(str(dist.locate_file('backend/cli/entry.py')))
    return wheel_entry if wheel_entry.exists() else None


def main() -> None:
    """Launch Grinta CLI in a collision-safe way."""
    entry_file = _resolve_entry_file()
    if entry_file is not None:
        runpy.run_path(str(entry_file), run_name='__main__')
        return

    # Last-resort fallback; may be vulnerable to package-name collisions.
    fallback_main = getattr(importlib.import_module('backend.cli.entry'), 'main')
    fallback_main()


if __name__ == '__main__':
    main()
