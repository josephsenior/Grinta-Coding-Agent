# pylint: disable=R0801
"""Get git changes in the current working directory relative to the remote origin if possible.

NOTE: Since this is run as a script, there should be no imports from project files!
"""

from __future__ import annotations

import glob
import json
import logging
import os
import sys
from pathlib import Path

from backend.execution.utils.git_common import get_valid_git_ref, run_git_cmd


def _parse_git_status_line(line: str, changed_files: list[str]) -> list[dict[str, str]]:
    """Parse a single git status line and return changes."""
    if not line.strip() or line.lower().startswith('warning:'):
        return []
    parts = line.split()
    if len(parts) < 2:
        return []
    status = parts[0].strip()
    if status.startswith('R') and len(parts) == 3:
        old_path = parts[1].strip()
        new_path = parts[2].strip()
        return [{'status': 'D', 'path': old_path}, {'status': 'A', 'path': new_path}]
    if status.startswith('C') and len(parts) == 3:
        new_path = parts[2].strip()
        return [{'status': 'A', 'path': new_path}]
    if len(parts) == 2:
        path = parts[1].strip()
    else:
        msg = f'unexpected_value_in_git_diff:{changed_files}'
        raise RuntimeError(msg)
    return [_normalize_status(status, path, changed_files)]


def _normalize_status(
    status: str, path: str, changed_files: list[str]
) -> dict[str, str]:
    """Normalize git status to standard format."""
    if status == '??':
        status = 'A'
    elif status == '*':
        status = 'M'
    if status in {'M', 'A', 'D', 'U'}:
        return {'status': status, 'path': path}
    msg = f'unexpected_status_in_git_diff:{changed_files}'
    raise RuntimeError(msg)


def get_changes_in_repo(repo_dir: str) -> list[dict[str, str]]:
    """Get all changes in a git repository."""
    ref = get_valid_git_ref(repo_dir)
    changed_files: list[str] = []
    try:
        run_git_cmd('git rev-parse --is-inside-work-tree', repo_dir)
    except RuntimeError:
        return []
    if ref:
        changed_files = run_git_cmd(
            f'git --no-pager diff --name-status {ref}', repo_dir
        ).splitlines()
    try:
        untracked_files = run_git_cmd(
            'git ls-files --others --exclude-standard', repo_dir
        ).splitlines()
        untracked_files = [f'A\t{f}' for f in untracked_files if f.strip()]
        changed_files.extend(untracked_files)
    except RuntimeError:
        pass
    changes: list[dict[str, str]] = []
    for line in changed_files:
        changes.extend(_parse_git_status_line(line, changed_files))
    return changes


def get_git_changes(cwd: str) -> list[dict[str, str]]:
    """Get git changes for the current directory and all subdirectories."""
    git_dirs = {
        os.path.dirname(f)[2:]
        for f in glob.glob('./*/.git', root_dir=cwd, recursive=True)
    }
    changes = get_changes_in_repo(cwd)
    changes = [
        c
        for c in changes
        if next((d for d in git_dirs if c['path'].startswith(d)), None) is None
    ]
    for git_dir in git_dirs:
        for change in get_changes_in_repo(str(Path(cwd, git_dir))):
            change['path'] = f'{git_dir}/{change["path"]}'
            changes.append(change)
    changes.sort(key=lambda c: c['path'])
    return changes


def _main() -> None:
    try:
        changes = get_git_changes(os.getcwd())
        try:
            from backend.core.json_stdout import print_json_stdout
        except Exception:
            sys.stdout.write(json.dumps(changes) + '\n')
            sys.stdout.flush()
        else:
            print_json_stdout(changes)
    except Exception as e:
        logging.exception('Failed to compute git changes')
        sys.stdout.write(json.dumps({'error': str(e)}) + '\n')
        sys.stdout.flush()


if __name__ == '__main__':
    _main()
