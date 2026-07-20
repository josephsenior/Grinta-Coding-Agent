#!/usr/bin/env python3
"""Verify release tag, package version, lockfile, fallback version, and classifier."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STABLE_VERSION = re.compile(r'^[0-9]+\.[0-9]+\.[0-9]+$')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag', required=True)
    parser.add_argument('--require-stable', action='store_true')
    args = parser.parse_args()

    pyproject = tomllib.loads((REPO_ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    version = pyproject['project']['version']
    expected_tag = f'v{version}'
    errors: list[str] = []
    if args.tag != expected_tag:
        errors.append(f'tag {args.tag!r} does not match package version {version!r}')

    uv_data = tomllib.loads((REPO_ROOT / 'uv.lock').read_text(encoding='utf-8'))
    lock_versions = {
        package.get('version')
        for package in uv_data.get('package', [])
        if package.get('name') == 'grinta'
    }
    if lock_versions != {version}:
        errors.append(f'uv.lock Grinta versions {sorted(lock_versions)} != {version!r}')

    backend_init = (REPO_ROOT / 'backend/__init__.py').read_text(encoding='utf-8')
    match = re.search(r"_DEFAULT_VERSION\s*=\s*['\"]([^'\"]+)['\"]", backend_init)
    fallback = match.group(1) if match else None
    if fallback != version:
        errors.append(f'backend fallback version {fallback!r} != {version!r}')

    classifiers = set(pyproject['project'].get('classifiers', []))
    if args.require_stable:
        if not STABLE_VERSION.fullmatch(version):
            errors.append(f'{version!r} is not a stable X.Y.Z version')
        stable_classifier = 'Development Status :: 5 - Production/Stable'
        if stable_classifier not in classifiers:
            errors.append(f'missing classifier: {stable_classifier}')

    if errors:
        print('Release tag verification failed:', file=sys.stderr)
        for error in errors:
            print(f' - {error}', file=sys.stderr)
        return 1
    print(f'Release tag verified: {args.tag} == package/lock/fallback {version}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
