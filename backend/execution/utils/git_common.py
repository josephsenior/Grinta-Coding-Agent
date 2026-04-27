"""Common git utilities for runtime scripts.

NOTE: This module is intended to be used by scripts that are run via subprocess
and should avoid complex project-level imports to maintain reliability.
"""

from __future__ import annotations

import shlex
import subprocess  # nosec B404


EMPTY_TREE_REF = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'
DISALLOWED_GIT_ARG_FRAGMENTS = ('|', '&&', ';', '>', '<', '$(')


def _split_git_cmd(cmd: str) -> list[str]:
    """Split a git command string while rejecting shell-only constructs."""
    args = shlex.split(cmd)
    if not args or args[0] != 'git':
        msg = 'unsafe_git_cmd'
        raise RuntimeError(msg)
    if any(fragment in arg for arg in args for fragment in DISALLOWED_GIT_ARG_FRAGMENTS):
        msg = 'unsafe_git_cmd'
        raise RuntimeError(msg)
    return args


def run_git_cmd(cmd: str, cwd: str) -> str:
    """Run a git command and return its output.

    Args:
        cmd: The command to run.
        cwd: The working directory to run the command in.

    Returns:
        str: The command output.

    Raises:
        RuntimeError: If the command fails to execute.

    """
    # Use shlex.split() to safely parse the command and avoid shell=True
    result = subprocess.run(  # nosec B603
        check=False,
        args=_split_git_cmd(cmd),
        shell=False,
        capture_output=True,
        cwd=cwd,
    )
    byte_content = result.stderr or result.stdout or b''
    if result.returncode != 0:
        msg = f'error_running_cmd:{result.returncode}:{byte_content.decode()}'
        raise RuntimeError(
            msg,
        )
    return byte_content.decode().strip()


def get_valid_git_ref(repo_dir: str) -> str | None:
    """Get a valid git reference for comparison.

    Tries multiple git references in order of preference:
    1. Current branch origin
    2. Default branch references
    3. Empty tree reference

    Args:
        repo_dir: The repository directory.

    Returns:
        str | None: A valid git reference hash, or None if none found.

    """
    refs: list[str] = []
    try:
        current_branch = run_git_cmd(
            'git --no-pager rev-parse --abbrev-ref HEAD', repo_dir
        )
        refs.append(f'origin/{current_branch}')
    except RuntimeError:
        pass
    try:
        default_branch = run_git_cmd(
            'git --no-pager symbolic-ref refs/remotes/origin/HEAD', repo_dir
        ).rsplit('/', maxsplit=1)[-1].strip()
        ref_non_default_branch = run_git_cmd(
            f'git --no-pager merge-base HEAD origin/{default_branch}', repo_dir
        )
        ref_default_branch = f'origin/{default_branch}'
        refs.extend((ref_non_default_branch, ref_default_branch))
    except RuntimeError:
        pass
    ref_new_repo = EMPTY_TREE_REF
    refs.append(ref_new_repo)
    for ref in refs:
        try:
            return run_git_cmd(f'git --no-pager rev-parse --verify {ref}', repo_dir)
        except RuntimeError:
            continue
    return None
