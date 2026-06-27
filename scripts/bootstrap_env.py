#!/usr/bin/env python3
"""Canonical bootstrap wrapper for syncing Grinta dependency profiles."""

from __future__ import annotations

import argparse
import subprocess
import sys

PROFILE_COMMANDS: dict[str, list[str]] = {
    'base': ['uv', 'sync'],
    'browser': ['uv', 'sync', '--group', 'browser'],
    'dev': ['uv', 'sync', '--group', 'dev'],
    'dev-test': ['uv', 'sync', '--group', 'dev', '--group', 'test'],
    'dev-test-browser': [
        'uv',
        'sync',
        '--group',
        'dev',
        '--group',
        'test',
        '--group',
        'browser',
    ],
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Sync the repository environment using a named dependency profile.'
    )
    parser.add_argument(
        'profile',
        nargs='?',
        default='base',
        choices=sorted(PROFILE_COMMANDS),
        help='Dependency profile to sync (default: base).',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print the resolved uv command without executing it.',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    command = PROFILE_COMMANDS[args.profile]
    print(f'[bootstrap] profile={args.profile}')
    print(f'[bootstrap] command={" ".join(command)}')
    if args.dry_run:
        return 0

    try:
        completed = subprocess.run(command, check=False)
    except FileNotFoundError:
        print('[bootstrap] error: `uv` was not found in PATH.', file=sys.stderr)
        return 127
    if completed.returncode != 0:
        return completed.returncode

    host_tools_cmd = [
        'uv',
        'run',
        'python',
        '-c',
        (
            'from backend.utils.linux_host_tools import ensure_linux_host_tools; '
            'from backend.core.wsl import ensure_tmux_tmpdir; '
            'result = ensure_linux_host_tools(); '
            'ensure_tmux_tmpdir(); '
            'print('
            'f"[bootstrap] linux_host_tools tmux={result.tmux_installed} '
            'libtmux={result.libtmux_available} ({result.message})"'
            ')'
        ),
    ]
    try:
        host_completed = subprocess.run(host_tools_cmd, check=False)
        if host_completed.returncode != 0:
            print(
                '[bootstrap] warning: linux host tool setup exited '
                f'with code {host_completed.returncode}',
                file=sys.stderr,
            )
    except FileNotFoundError:
        print('[bootstrap] warning: could not run linux host tool setup.', file=sys.stderr)
    return completed.returncode


if __name__ == '__main__':
    raise SystemExit(main())
