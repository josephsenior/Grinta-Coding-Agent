"""Helpers for invoking git commands within runtime environments."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from backend.core.logger import FORGE_logger as logger
from backend.runtime.utils import git_changes, git_diff

GIT_CHANGES_CMD = "python3 /Forge/code/Forge/runtime/utils/git_changes.py"
GIT_DIFF_CMD = 'python3 /Forge/code/Forge/runtime/utils/git_diff.py "{file_path}"'
GIT_BRANCH_CMD = "git branch --show-current"


@dataclass
class CommandResult:
    """Represents the result of a shell command execution.

    Attributes:
        content (str): The output content of the command.
        exit_code (int): The exit code of the command execution.

    """

    content: str
    exit_code: int


class GitHandler:
    """A handler for executing Git-related operations via shell commands."""

    def __init__(
        self,
        execute_shell_fn: Callable[[str, str | None], CommandResult],
        create_file_fn: Callable[[str, str], int],
    ) -> None:
        """Store shell execution helpers and default git command templates."""
        self.execute = execute_shell_fn
        self.create_file_fn = create_file_fn
        self.cwd: str | None = None
        self.git_changes_cmd = GIT_CHANGES_CMD
        self.git_diff_cmd = GIT_DIFF_CMD
        self.git_branch_cmd = GIT_BRANCH_CMD

    def set_cwd(self, cwd: str) -> None:
        """Sets the current working directory for Git operations.

        Args:
            cwd (str): The directory path.

        """
        self.cwd = cwd

    def _create_python_script_file(self, file: str):
        result = self.execute("mktemp -d", self.cwd)
        script_file = Path(result.content.strip(), Path(file).name)
        with open(file, encoding="utf-8") as f:
            self.create_file_fn(str(script_file), f.read())
            result = self.execute(f'chmod +x "{script_file}"', self.cwd)
        return script_file

    def get_current_branch(self) -> str | None:
        """Retrieves the current branch name of the git repository.

        Returns:
            str | None: The current branch name, or None if not a git repository or error occurs.

        """
        if not self.cwd:
            return None
        result = self.execute(self.git_branch_cmd, self.cwd)
        if result.exit_code == 0:
            return branch if (branch := result.content.strip()) else None
        return None

    def get_git_changes(self) -> list[dict[str, str]] | None:
        """Retrieves the list of changed files in Git repositories.

        Examines each direct subdirectory of the workspace directory looking for git repositories
        and returns the changes for each of these directories.
        Optimized to use a single git command per repository for maximum performance.

        Returns:
            list[dict[str, str]] | None: A list of dictionaries containing file paths and statuses. None if no git repositories found.

        """
        if not self.cwd:
            return None
        result = self.execute(self.git_changes_cmd, self.cwd)
        if result.exit_code == 0:
            try:
                return json.loads(result.content)
            except Exception:
                logger.exception(
                    "GitHandler:get_git_changes:error",
                    extra={"content": result.content},
                )
                return None
        if self.git_changes_cmd != GIT_CHANGES_CMD:
            return None
        logger.info(
            "GitHandler:get_git_changes: adding git_changes script to runtime..."
        )
        script_file = self._create_python_script_file(git_changes.__file__)
        self.git_changes_cmd = f"python3 {script_file}"
        return self.get_git_changes()

    def get_git_diff(self, file_path: str) -> dict[str, str]:
        """Retrieves the original and modified content of a file in the repository.

        Args:
            file_path (str): Path to the file.

        Returns:
            dict[str, str]: A dictionary containing the original and modified content.

        """
        if not self.cwd:
            msg = "no_dir_in_git_diff"
            raise ValueError(msg)
        result = self.execute(self.git_diff_cmd.format(file_path=file_path), self.cwd)
        if result.exit_code == 0:
            return json.loads(result.content, strict=False)
        if self.git_diff_cmd != GIT_DIFF_CMD:
            msg = "error_in_git_diff"
            raise ValueError(msg)
        logger.info("GitHandler:get_git_diff: adding git_diff script to runtime...")
        script_file = self._create_python_script_file(git_diff.__file__)
        self.git_diff_cmd = f'python3 {script_file} "{{file_path}}"'
        return self.get_git_diff(file_path)
