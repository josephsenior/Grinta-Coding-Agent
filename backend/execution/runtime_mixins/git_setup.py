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
from typing import TYPE_CHECKING, Any, Literal, cast

from backend.core.logging.logger import app_logger as logger
from backend.core.os_capabilities import OS_CAPS
from backend.ledger import EventSource
from backend.ledger.action import CmdRunAction, FileEditAction, FileReadAction
from backend.ledger.observation import (
    CmdOutputObservation,
    ErrorObservation,
)
from backend.utils.async_helpers.async_utils import call_sync_from_async

if TYPE_CHECKING:
    from backend.core.enums import RuntimeStatus
    from backend.core.providers.provider_models import ProviderTokenType

_ScriptKind = Literal['bash', 'powershell']

_SETUP_SCRIPT_CANDIDATES: dict[bool, tuple[tuple[str, _ScriptKind], ...]] = {
    True: (
        ('.grinta/setup.ps1', 'powershell'),
        ('.grinta/setup.sh', 'bash'),
    ),
    False: (
        ('.grinta/setup.sh', 'bash'),
        ('.grinta/setup.ps1', 'powershell'),
    ),
}

_PRECOMMIT_SCRIPT_CANDIDATES: dict[bool, tuple[tuple[str, _ScriptKind], ...]] = {
    True: (
        ('.grinta/pre-commit.ps1', 'powershell'),
        ('.grinta/pre-commit.sh', 'bash'),
    ),
    False: (('.grinta/pre-commit.sh', 'bash'),),
}


def _bash_pre_commit_hook_content(pre_commit_script: str) -> str:
    return (
        f'#!/bin/bash\n# This hook was installed by APP\n'
        f'# It calls the pre-commit script in the .grinta directory\n\n'
        f'if [ -x "{pre_commit_script}" ]; then\n'
        f'    . "{pre_commit_script}"\n'
        f'    exit $?\n'
        f'else\n'
        f'    echo "Warning: {pre_commit_script} not found or not executable"\n'
        f'    exit 0\n'
        f'fi\n'
    )


def _powershell_pre_commit_hook_content(pre_commit_script: str) -> str:
    return (
        '#!/usr/bin/env pwsh\n'
        '# This hook was installed by APP\n'
        f'$script = "{pre_commit_script}"\n'
        'if (Test-Path $script) {\n'
        '    & $script\n'
        '    exit $LASTEXITCODE\n'
        '}\n'
        f'Write-Host "Warning: {pre_commit_script} not found"\n'
        'exit 0\n'
    )


def _script_run_command(path: str, kind: _ScriptKind) -> str:
    if kind == 'powershell':
        return f'powershell -NoProfile -ExecutionPolicy Bypass -File "{path}"'
    if OS_CAPS.is_windows:
        return f'bash "{path}"'
    return f'chmod +x "{path}" && . "{path}"'


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
        def edit(self, action: FileEditAction) -> Any: ...
        def run(self, action: CmdRunAction) -> Any: ...
        def run_action(self, action: Any) -> Any: ...
        def set_runtime_status(
            self, status: RuntimeStatus, msg: str = '', level: str = 'info'
        ) -> None: ...

    # ------------------------------------------------------------------
    # Git clone / init
    # ------------------------------------------------------------------

    async def clone_or_init_repo(
        self,
        vcs_provider_tokens: ProviderTokenType | None,
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
                    'No repository selected. Initializing a new git repository in the workspace.'
                )
                action = CmdRunAction(
                    command=(
                        f'git init && git config --local --add safe.directory '
                        f'"{self.workspace_root}"'
                    ),
                )
                await call_sync_from_async(self.run_action, action)
            else:
                logger.info(
                    'In workspace mount mode, not initializing a new git repository.'
                )
            return ''
        remote_repo_url = await self.provider_handler.get_authenticated_git_url(
            selected_repository
        )
        if not remote_repo_url:
            msg = 'Missing either Git token or valid repository'
            raise ValueError(msg)
        if self.status_callback:
            from backend.core.enums import RuntimeStatus

            self.status_callback(
                'info', RuntimeStatus.SETTING_UP_WORKSPACE, 'Setting up workspace...'
            )
        dir_name = selected_repository.split('/')[-1].lower()
        random_str = ''.join(
            random.choices(string.ascii_lowercase + string.digits, k=8)  # nosec B311 (branch name suffix, not cryptographic)
        )
        workspace_branch = f'app-workspace-{random_str}'
        clone_command = f'git clone {remote_repo_url} {dir_name}'
        checkout_command = (
            f'git checkout {selected_branch}'
            if selected_branch
            else f'git checkout -b {workspace_branch}'
        )
        clone_action = CmdRunAction(command=clone_command)
        await call_sync_from_async(self.run_action, clone_action)
        cd_checkout_action = CmdRunAction(
            command=f'cd {dir_name} && {checkout_command}'
        )
        action = cd_checkout_action
        self.log('info', f'Cloning repo: {selected_repository}')
        await call_sync_from_async(self.run_action, action)
        return dir_name

    # ------------------------------------------------------------------
    # Setup scripts
    # ------------------------------------------------------------------

    def _find_workspace_script(
        self, candidates: tuple[tuple[str, _ScriptKind], ...]
    ) -> tuple[str, _ScriptKind] | None:
        for path, kind in candidates:
            read_obs = cast(Any, self.read(FileReadAction(path=path)))
            if not isinstance(read_obs, ErrorObservation):
                return path, kind
        return None

    def maybe_run_setup_script(self) -> None:
        """Run a workspace setup script when present under ``.grinta/``.

        Prefers ``setup.ps1`` on Windows and ``setup.sh`` on POSIX, with
        cross-platform fallbacks when only the other script exists.
        """
        resolved = self._find_workspace_script(
            _SETUP_SCRIPT_CANDIDATES[OS_CAPS.is_windows]
        )
        if resolved is None:
            return
        setup_script, kind = resolved
        if self.status_callback:
            from backend.core.enums import RuntimeStatus

            self.status_callback(
                'info', RuntimeStatus.SETTING_UP_WORKSPACE, 'Setting up workspace...'
            )
        action = CmdRunAction(
            command=_script_run_command(setup_script, kind),
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
        hook_dir = self.workspace_root / '.git' / 'hooks'
        try:
            hook_dir.mkdir(parents=True, exist_ok=True)
            return True
        except OSError as exc:
            self.log('error', f'Failed to create git hooks directory: {exc}')
            return False

    def _make_script_executable(self, script_path: str) -> bool:
        """Make a script file executable on POSIX hosts."""
        if OS_CAPS.is_windows:
            return True
        action = CmdRunAction(command=f'chmod +x {script_path}')
        obs = cast(Any, self.run_action(action))
        if isinstance(obs, CmdOutputObservation):
            if obs.exit_code == 0:
                return True
            self.log('error', f'Failed to make {script_path} executable: {obs.content}')
            return False
        return False

    def _preserve_existing_hook(self, pre_commit_hook: str) -> bool:
        """Preserve existing pre-commit hook by moving it to .local file."""
        pre_commit_local = '.git/hooks/pre-commit.local'
        src = self.workspace_root / pre_commit_hook
        dst = self.workspace_root / pre_commit_local
        try:
            shutil.move(str(src), str(dst))
            return self._make_script_executable(pre_commit_local)
        except (OSError, shutil.Error) as exc:
            self.log('error', f'Failed to preserve existing pre-commit hook: {exc}')
            return False

    def _install_pre_commit_hook(
        self,
        pre_commit_script: str,
        pre_commit_hook: str,
        *,
        kind: _ScriptKind,
    ) -> bool:
        """Install the pre-commit hook file."""
        if kind == 'powershell':
            pre_commit_hook_content = _powershell_pre_commit_hook_content(
                pre_commit_script
            )
        else:
            pre_commit_hook_content = _bash_pre_commit_hook_content(pre_commit_script)

        write_obs = cast(
            Any,
            self.edit(
                FileEditAction(
                    path=pre_commit_hook,
                    command='create_file',
                    file_text=pre_commit_hook_content,
                )
            ),
        )
        if isinstance(write_obs, ErrorObservation):
            self.log('error', f'Failed to write pre-commit hook: {write_obs.content}')
            return False

        return self._make_script_executable(pre_commit_hook)

    def maybe_setup_git_hooks(self) -> None:
        """Set up git hooks when a pre-commit script exists under ``.grinta/``.

        Prefers ``pre-commit.ps1`` on Windows and ``pre-commit.sh`` on POSIX.
        """
        resolved = self._find_workspace_script(
            _PRECOMMIT_SCRIPT_CANDIDATES[OS_CAPS.is_windows]
        )
        if resolved is None:
            return
        pre_commit_script, script_kind = resolved
        pre_commit_hook = '.git/hooks/pre-commit'

        if self.status_callback:
            from backend.core.enums import RuntimeStatus

            self.status_callback(
                'info', RuntimeStatus.SETTING_UP_GIT_HOOKS, 'Setting up git hooks...'
            )

        if not self._setup_git_hooks_directory():
            return

        if not self._make_script_executable(pre_commit_script):
            return

        read_obs = cast(Any, self.read(FileReadAction(path=pre_commit_hook)))
        if (
            not isinstance(read_obs, ErrorObservation)
            and 'This hook was installed by APP' not in read_obs.content
        ):
            self.log('info', 'Preserving existing pre-commit hook')
            if not self._preserve_existing_hook(pre_commit_hook):
                return

        if self._install_pre_commit_hook(
            pre_commit_script, pre_commit_hook, kind=script_kind
        ):
            self.log('info', 'Git pre-commit hook installed successfully')

    # ------------------------------------------------------------------
    # Git config
    # ------------------------------------------------------------------

    def _setup_git_config(self) -> None:
        """Configure git author identity via session env vars (no global git config)."""
        vcs_user_name = self.config.vcs_user_name
        vcs_user_email = self.config.vcs_user_email
        try:
            self.add_env_vars(
                {
                    'GIT_AUTHOR_NAME': vcs_user_name,
                    'GIT_COMMITTER_NAME': vcs_user_name,
                    'GIT_AUTHOR_EMAIL': vcs_user_email,
                    'GIT_COMMITTER_EMAIL': vcs_user_email,
                }
            )
            logger.info(
                'Configured git identity via session env vars: name=%s, email=%s',
                vcs_user_name,
                vcs_user_email,
            )
        except Exception as e:
            logger.warning('Failed to configure git identity env vars: %s', e)
