#!/usr/bin/env python3
"""Fail when wheel/sdist artifacts contain development state or large release media."""

from __future__ import annotations

import argparse
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MAX_ARTIFACT_BYTES = 12 * 1024 * 1024
MAX_MEMBER_BYTES = 8 * 1024 * 1024
BANNED_SUFFIXES = {'.avi', '.exe', '.mov', '.mp4', '.webm', '.zip'}


@dataclass(frozen=True)
class Member:
    name: str
    size: int


def members(path: Path) -> list[Member]:
    if path.suffix == '.whl':
        with zipfile.ZipFile(path) as archive:
            return [Member(info.filename, info.file_size) for info in archive.infolist()]
    if path.name.endswith('.tar.gz'):
        with tarfile.open(path, 'r:gz') as archive:
            return [Member(info.name, info.size) for info in archive.getmembers() if info.isfile()]
    raise ValueError(f'Unsupported distribution: {path}')


def normalized_parts(name: str) -> tuple[str, ...]:
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError(f'Unsafe archive member path: {name}')
    return path.parts


def violations(path: Path) -> list[str]:
    errors: list[str] = []
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        errors.append(
            f'{path.name}: artifact is {path.stat().st_size / 1024 / 1024:.1f} MiB; '
            f'limit is {MAX_ARTIFACT_BYTES / 1024 / 1024:.0f} MiB'
        )
    for member in members(path):
        try:
            parts = normalized_parts(member.name)
        except ValueError as exc:
            errors.append(f'{path.name}: {exc}')
            continue
        lowered = tuple(part.lower() for part in parts)
        suffix = PurePosixPath(member.name).suffix.lower()
        if '.grinta' in lowered:
            errors.append(f'{path.name}: generated .grinta state included: {member.name}')
        if lowered[-1:] == ('conftest.py',) and 'backend' in lowered:
            errors.append(f'{path.name}: test conftest included: {member.name}')
        joined = '/'.join(lowered)
        if '/backend/scripts/refactor/' in f'/{joined}/':
            errors.append(f'{path.name}: internal refactor utility included: {member.name}')
        if 'backend/tests/' in joined:
            errors.append(f'{path.name}: backend tests included: {member.name}')
        if suffix in BANNED_SUFFIXES:
            errors.append(f'{path.name}: release media/binary included: {member.name}')
        if member.size > MAX_MEMBER_BYTES:
            errors.append(
                f'{path.name}: member {member.name} is '
                f'{member.size / 1024 / 1024:.1f} MiB'
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path, nargs='?', default=Path('dist'))
    args = parser.parse_args()
    root = args.directory
    artifacts = sorted(root.glob('*.whl')) + sorted(root.glob('*.tar.gz'))
    wheels = [path for path in artifacts if path.suffix == '.whl']
    sdists = [path for path in artifacts if path.name.endswith('.tar.gz')]
    errors: list[str] = []
    if len(wheels) != 1:
        errors.append(f'Expected exactly one wheel in {root}, found {len(wheels)}')
    if len(sdists) != 1:
        errors.append(f'Expected exactly one sdist in {root}, found {len(sdists)}')
    for artifact in artifacts:
        print(f'checking {artifact} ({artifact.stat().st_size / 1024 / 1024:.2f} MiB)')
        errors.extend(violations(artifact))
    if errors:
        print('Distribution hygiene check failed:', file=sys.stderr)
        for error in errors:
            print(f' - {error}', file=sys.stderr)
        return 1
    print('Distribution hygiene check passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
