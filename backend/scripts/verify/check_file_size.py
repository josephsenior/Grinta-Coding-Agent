#!/usr/bin/env python3
"""Advisory file-size budget check for refactor tracking.

Warns when Python files under watched backend trees exceed soft limits.
New or changed files above the hard limit fail the check.

Run via:  python backend/scripts/verify/check_file_size.py
          python backend/scripts/verify/check_file_size.py --changed-only
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SOFT_LIMIT = 500
HARD_LIMIT = 800
WATCH_ROOTS = (
    Path('backend/cli'),
    Path('backend/orchestration'),
    Path('backend/engine'),
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _is_watched(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        return False
    return any(rel.startswith(f'{watch.as_posix()}/') for watch in WATCH_ROOTS)


def _changed_files(root: Path) -> list[Path]:
    try:
        result = subprocess.run(
            ['git', 'diff', '--name-only', '--diff-filter=ACMR', 'HEAD'],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    files: list[Path] = []
    for line in result.stdout.splitlines():
        path = root / line.strip()
        if path.suffix == '.py' and _is_watched(path, root):
            files.append(path)
    return files


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding='utf-8').splitlines())


def _check(paths: list[Path], *, changed_only: bool) -> int:
    warnings: list[str] = []
    errors: list[str] = []

    for path in sorted(paths):
        if not path.is_file():
            continue
        rel = path.as_posix()
        if 'tests/' in rel or rel.endswith('__init__.py'):
            continue
        count = _line_count(path)
        if count >= HARD_LIMIT:
            msg = f'{rel}: {count} LOC (hard limit {HARD_LIMIT})'
            if changed_only:
                errors.append(msg)
            else:
                warnings.append(msg)
        elif count >= SOFT_LIMIT:
            warnings.append(f'{rel}: {count} LOC (soft limit {SOFT_LIMIT})')

    for msg in warnings:
        print(f'WARNING: {msg}')
    for msg in errors:
        print(f'ERROR: {msg}')

    if errors:
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--changed-only',
        action='store_true',
        help='Only fail on changed files above the hard limit',
    )
    args = parser.parse_args()

    root = _repo_root()
    if args.changed_only:
        paths = _changed_files(root)
        if not paths:
            return 0
    else:
        discovered: list[Path] = []
        for watch in WATCH_ROOTS:
            watch_path = root / watch
            if watch_path.is_dir():
                discovered.extend(watch_path.rglob('*.py'))
        paths = discovered

    return _check(paths, changed_only=args.changed_only)


if __name__ == '__main__':
    sys.exit(main())
