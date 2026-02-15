"""Mixin for git workspace setup, cloning, and hook management.

Extracts git-related lifecycle operations from ``Runtime`` so that
``base.py`` stays focused on the core runtime contract.
"""

from __future__ import annotations

import random
import shutil
import string
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from backend.core.logger import FORGE_logger as logger
from backend.events import EventSource
from backend.events.action import CmdRunAction, FileReadAction, FileWriteAction
from backend.events.observation import (
    CmdOutputObservation,
    ErrorObservation,
)
from backend.utils.async_utils import call_sync_from_async

if TYPE_CHECKING:
    from backend.core.provider_types import PROVIDER_TOKEN_TYPE
    from backend.core.enums import RuntimeStatus


class GitSetupMixin:
    """Mixin that adds git workspace & hook setup capabilities to a Runtime."""

    # Attributes / methods expected on the host class (Runtime).
    if TYPE_CHECKING:
        sid: str
        config: Any
        workspace_root: Path
        event_stream: Any
        status_callback: Callable | None
        provider_handler: Any

        def log(self, level: str, message: str) -> None: ...
        def read(self, action: FileReadAction) -> Any: ...
        def write(self, action: FileWriteAction) -> Any: ...
        def run(self, action: CmdRunAction) -> Any: ...
        def run_action(self, action: Any) -> Any: ...
        def set_runtime_status(
            self, status: RuntimeStatus, msg: str = "", level: str = "info"
        ) -> None: ...

    # ------------------------------------------------------------------
    # Git clone / init
    # ------------------------------------------------------------------

    async def clone_or_init_repo(
        self,
        vcs_provider_tokens: PROVIDER_TOKEN_TYPE | None,
        selected_repository: str | None,
        selected_branch: str | None,
    ) -> str:
        """Clone repository or initialize workspace.

        Args:
            vcs_provider_tokens: Provider authentication tokens
            selected_repository: Repository to clone (None to use workspace)
            selected_branch: Branch to checkout

        Returns:
            Path to repository directory
        """
        if not selected_repository:
            if self.config.init_git_in_empty_workspace:
                logger.debug(
                    "No repository selected. Initializing a new git repository in the workspace."
                )
                action = CmdRunAction(
                    command=f"git init && git config --global --add safe.directory {self.workspace_root}",
                )
                await call_sync_from_async(self.run_action, action)
            else:
                logger.info(
                    "In workspace mount mode, not initializing a new git repository."
                )
            return ""
        remote_repo_url = await self.provider_handler.get_authenticated_git_url(
            selected_repository
        )
        if not remote_repo_url:
            msg = "Missing either Git token or valid repository"
            raise ValueError(msg)
        if self.status_callback:
            from backend.core.enums import RuntimeStatus

            self.status_callback(
                "info", RuntimeStatus.SETTING_UP_WORKSPACE, "Setting up workspace..."
            )
        dir_name = selected_repository.split("/")[-1].lower()
        random_str = "".join(
            random.choices(string.ascii_lowercase + string.digits, k=8)
        )
        FORGE_workspace_branch = f"Forge-workspace-{random_str}"
        clone_command = f"git clone {remote_repo_url} {dir_name}"
        checkout_command = (
            f"git checkout {selected_branch}"
            if selected_branch
            else f"git checkout -b {FORGE_workspace_branch}"
        )
        clone_action = CmdRunAction(command=clone_command)
        await call_sync_from_async(self.run_action, clone_action)
        cd_checkout_action = CmdRunAction(
            command=f"cd {dir_name} && {checkout_command}"
        )
        action = cd_checkout_action
        self.log("info", f"Cloning repo: {selected_repository}")
        await call_sync_from_async(self.run_action, action)
        return dir_name

    # ------------------------------------------------------------------
    # Setup scripts
    # ------------------------------------------------------------------

    def maybe_run_setup_script(self) -> None:
        """Run .Forge/setup.sh if it exists in the workspace or repository."""
        setup_script = ".Forge/setup.sh"
        read_obs = cast(Any, self.read(FileReadAction(path=setup_script)))
        if isinstance(read_obs, ErrorObservation):
            return
        if self.status_callback:
            from backend.core.enums import RuntimeStatus

            self.status_callback(
                "info", RuntimeStatus.SETTING_UP_WORKSPACE, "Setting up workspace..."
            )
        action = CmdRunAction(
            command=f"chmod +x {setup_script} && source {setup_script}",
            blocking=True,
            hidden=True,
        )
        action.set_hard_timeout(600)
        source = EventSource.ENVIRONMENT
        if self.event_stream:
            self.event_stream.add_event(action, source)
        cast(Any, self.run_action(action))

    # ------------------------------------------------------------------
    # Git hooks
    # ------------------------------------------------------------------

    def _setup_git_hooks_directory(self) -> bool:
        """Create git hooks directory if needed."""
        action = CmdRunAction(command="mkdir -p .git/hooks")
        obs = cast(Any, self.run_action(action))
        if isinstance(obs, CmdOutputObservation):
            if obs.exit_code == 0:
                return True
            self.log("error", f"Failed to create git hooks directory: {obs.content}")
            return False
        return False

    def _make_script_executable(self, script_path: str) -> bool:
        """Make a script file executable."""
        action = CmdRunAction(command=f"chmod +x {script_path}")
        obs = cast(Any, self.run_action(action))
        if isinstance(obs, CmdOutputObservation):
            if obs.exit_code == 0:
                return True
            self.log("error", f"Failed to make {script_path} executable: {obs.content}")
            return False
        return False

    def _preserve_existing_hook(self, pre_commit_hook: str) -> bool:
        """Preserve existing pre-commit hook by moving it to .local file."""
        pre_commit_local = ".git/hooks/pre-commit.local"
        action = CmdRunAction(command=f"mv {pre_commit_hook} {pre_commit_local}")
        obs = cast(Any, self.run_action(action))
        if isinstance(obs, CmdOutputObservation):
            if obs.exit_code == 0:
                return bool(
                    GitSetupMixin._make_script_executable(self, pre_commit_local)
                )
            self.log(
                "error", f"Failed to preserve existing pre-commit hook: {obs.content}"
            )
            return False

        try:
            shutil.move(pre_commit_hook, pre_commit_local)
            return bool(GitSetupMixin._make_script_executable(self, pre_commit_local))
        except (OSError, shutil.Error) as exc:
            self.log("error", f"Failed to preserve existing pre-commit hook: {exc}")
            return False

    def _install_pre_commit_hook(
        self, pre_commit_script: str, pre_commit_hook: str
    ) -> bool:
        """Install the pre-commit hook file."""
        pre_commit_hook_content = f'#!/bin/bash\n# This hook was installed by Forge\n# It calls the pre-commit script in the .Forge directory\n\nif [ -x "{pre_commit_script}" ]; then\n    source "{pre_commit_script}"\n    exit $?\nelse\n    echo "Warning: {pre_commit_script} not found or not executable"\n    exit 0\nfi\n'

        write_obs = cast(
            Any,
            self.write(
                FileWriteAction(path=pre_commit_hook, content=pre_commit_hook_content)
            ),
        )
        if isinstance(write_obs, ErrorObservation):
            self.log("error", f"Failed to write pre-commit hook: {write_obs.content}")
            return False

        return bool(GitSetupMixin._make_script_executable(self, pre_commit_hook))

    def maybe_setup_git_hooks(self) -> None:
        """Set up git hooks if .Forge/pre-commit.sh exists in the workspace or repository."""
        pre_commit_script = ".Forge/pre-commit.sh"
        pre_commit_hook = ".git/hooks/pre-commit"

        # Check if pre-commit script exists
        read_obs = cast(Any, self.read(FileReadAction(path=pre_commit_script)))
        if isinstance(read_obs, ErrorObservation):
            return

        if self.status_callback:
            from backend.core.enums import RuntimeStatus

            self.status_callback(
                "info", RuntimeStatus.SETTING_UP_GIT_HOOKS, "Setting up git hooks..."
            )

        # Setup hooks directory
        if not GitSetupMixin._setup_git_hooks_directory(self):
            return

        # Make pre-commit script executable
        if not GitSetupMixin._make_script_executable(self, pre_commit_script):
            return

        # Preserve existing hook if needed
        read_obs = cast(Any, self.read(FileReadAction(path=pre_commit_hook)))
        if (
            not isinstance(read_obs, ErrorObservation)
            and "This hook was installed by Forge" not in read_obs.content
        ):
            self.log("info", "Preserving existing pre-commit hook")
            if not GitSetupMixin._preserve_existing_hook(self, pre_commit_hook):
                return

        # Install new hook
        if GitSetupMixin._install_pre_commit_hook(
            self, pre_commit_script, pre_commit_hook
        ):
            self.log("info", "Git pre-commit hook installed successfully")

    # ------------------------------------------------------------------
    # Git config
    # ------------------------------------------------------------------

    def _setup_git_config(self) -> None:
        """Configure git user settings during initial environment setup."""
        vcs_user_name = self.config.vcs_user_name
        vcs_user_email = self.config.vcs_user_email
        cmd = f'git config --global user.name "{vcs_user_name}" && git config --global user.email "{vcs_user_email}"'
        try:
            action = CmdRunAction(command=cmd)
            obs = cast(Any, self.run(action))
            if isinstance(obs, CmdOutputObservation) and obs.exit_code != 0:
                logger.warning(
                    "Git config command failed: %s, error: %s", cmd, obs.content
                )
            else:
                logger.info(
                    "Successfully configured git: name=%s, email=%s",
                    vcs_user_name,
                    vcs_user_email,
                )
        except Exception as e:
            logger.warning(
                "Failed to execute git config command: %s, error: %s", cmd, e
            )
