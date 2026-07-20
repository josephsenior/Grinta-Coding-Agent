#!/usr/bin/env python3
"""Reject tracked generated state, release media, installers, and oversized blobs."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAX_TRACKED_BYTES = 8 * 1024 * 1024
BANNED_EXACT = {
    'rustup-init.exe',
    'docs/assets/grinta-demo.mp4',
    'docs/assets/grinta-demo-preview.webp',
    'traces/ouroboros/session.zip',
}
BANNED_PREFIXES = ('backend/.grinta/',)


def tracked_files() -> list[str]:
    result = subprocess.run(
        ['git', 'ls-files', '-z'],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return [item.decode('utf-8') for item in result.stdout.split(b'\0') if item]


def main() -> int:
    errors: list[str] = []
    for relative in tracked_files():
        normalized = relative.replace('\\', '/')
        path = REPO_ROOT / relative
        if normalized in BANNED_EXACT or normalized.startswith(BANNED_PREFIXES):
            errors.append(f'forbidden tracked payload: {normalized}')
        if path.is_file() and path.stat().st_size > MAX_TRACKED_BYTES:
            errors.append(
                f'oversized tracked file: {normalized} '
                f'({path.stat().st_size / 1024 / 1024:.1f} MiB)'
            )
    if errors:
        print('Repository hygiene check failed:', file=sys.stderr)
        for error in errors:
            print(f' - {error}', file=sys.stderr)
        return 1
    print('Repository hygiene check passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
