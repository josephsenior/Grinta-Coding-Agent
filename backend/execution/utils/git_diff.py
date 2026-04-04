# pylint: disable=R0801
"""Get git diff in a single git file for the closest git repo in the file system.

NOTE: Since this is run as a script, there should be no imports from project files!
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from backend.execution.utils.git_common import get_valid_git_ref, run_git_cmd

try:
    from backend.core.constants import MAX_FILE_SIZE_FOR_GIT_DIFF
except ImportError:
    MAX_FILE_SIZE_FOR_GIT_DIFF = 1024 * 1024


def get_closest_git_repo(path: Path) -> Path | None:
    """Find the closest git repository directory by walking up the directory tree.

    Args:
        path: The starting path to search from.

    Returns:
        Path | None: The path to the git repository, or None if not found.

    """
    while True:
        path = path.parent
        git_path = Path(path, '.git')
        if git_path.is_dir():
            return path
        if path.parent == path:
            return None


def get_git_diff(relative_file_path: str) -> dict[str, str]:
    """Get git diff for a specific file.

    Args:
        relative_file_path: The relative path to the file to get diff for.

    Returns:
        dict[str, str]: Dictionary with 'modified' and 'original' file contents.

    Raises:
        ValueError: If file is too large or no repository is found.

    """
    path = Path(os.getcwd(), relative_file_path).resolve()
    if os.path.getsize(path) > MAX_FILE_SIZE_FOR_GIT_DIFF:
        msg = 'file_to_large'
        raise ValueError(msg)
    closest_git_repo = get_closest_git_repo(path)
    if not closest_git_repo:
        msg = 'no_repository'
        raise ValueError(msg)
    current_rev = get_valid_git_ref(str(closest_git_repo))
    try:
        original = run_git_cmd(
            f'git show "{current_rev}:{path.relative_to(closest_git_repo)}"',
            str(closest_git_repo),
        )
    except RuntimeError:
        original = ''
    try:
        with open(path, encoding='utf-8') as f:
            modified = '\n'.join(f.read().splitlines())
    except FileNotFoundError:
        modified = ''
    return {'modified': modified, 'original': original}


def _fallback_print(
    obj,
) -> None:  # pragma: no cover - exercised via tests with patched stdout
    try:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False, default=str) + '\n')
    except Exception:  # pragma: no cover
        try:
            sys.stdout.write(repr(obj) + '\n')
        except Exception:
            sys.stdout.write('{"error":"unserializable"}\n')
    sys.stdout.flush()


def _main() -> None:
    diff = get_git_diff(sys.argv[-1])
    try:
        from backend.core.json_stdout import print_json_stdout
    except Exception:  # pragma: no cover - fallback is tested separately
        _fallback_print(diff)
    else:
        print_json_stdout(diff)


if __name__ == '__main__':  # pragma: no cover
    _main()
