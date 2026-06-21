#!/usr/bin/env python3
"""Remove Python bytecode caches (__pycache__, *.pyc) from the repository tree."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def clean_pycache(root: Path) -> tuple[int, int]:
    """Delete ``__pycache__`` directories and ``*.pyc`` files under *root*.

    Returns:
        ``(removed_dirs, removed_files)``
    """
    removed_dirs = 0
    removed_files = 0

    for path in sorted(root.rglob('__pycache__'), key=lambda p: len(p.parts), reverse=True):
        if not path.is_dir():
            continue
        shutil.rmtree(path, ignore_errors=True)
        removed_dirs += 1

    for path in root.rglob('*.pyc'):
        if not path.is_file():
            continue
        try:
            path.unlink()
            removed_files += 1
        except OSError:
            pass

    return removed_dirs, removed_files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'root',
        nargs='?',
        default=str(_repo_root()),
        help='Repository root to clean (default: repo root)',
    )
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f'error: not a directory: {root}', file=sys.stderr)
        return 1

    removed_dirs, removed_files = clean_pycache(root)
    print(
        f'cleaned {removed_dirs} __pycache__ director'
        f'{"ies" if removed_dirs != 1 else "y"} and {removed_files} .pyc file'
        f'{"s" if removed_files != 1 else ""} under {root}'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
