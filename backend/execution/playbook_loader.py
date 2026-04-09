"""Mixin for loading playbooks from repositories and directories.

Extracts playbook-loading logic from ``Runtime`` so it can be tested
and maintained independently.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from zipfile import ZipFile

from backend.core.workspace_resolution import workspace_grinta_root
from backend.ledger.action import CmdRunAction, FileReadAction
from backend.ledger.observation import (
    CmdOutputObservation,
    ErrorObservation,
    FileReadObservation,
)
from backend.playbooks.engine import BasePlaybook, load_playbooks_from_dir
from backend.utils.async_utils import GENERAL_TIMEOUT, call_async_from_sync

if TYPE_CHECKING:
    pass


class PlaybookLoaderMixin:
    """Mixin that adds playbook-loading capabilities to a Runtime."""

    # These attributes/methods are expected on the host class (Runtime).
    # Declared here for type-checker visibility only.
    if TYPE_CHECKING:
        sid: str
        workspace_root: Path
        status_callback: Any
        provider_handler: Any

        def log(self, level: str, message: str) -> None: ...
        def read(self, action: FileReadAction) -> Any: ...
        def list_files(self, path: str, recursive: bool = False) -> list[str]: ...
        def copy_from(self, path: str) -> Path: ...
        def run_action(self, action: Any) -> Any: ...

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _load_playbooks_from_directory(
        self, playbooks_dir: Path, source_description: str
    ) -> list[BasePlaybook]:
        """Load playbooks from a directory.

        Args:
            playbooks_dir: Path to the directory containing playbooks
            source_description: Description of the source for logging purposes

        Returns:
            A list of loaded playbooks
        """
        loaded_playbooks: list[BasePlaybook] = []
        self.log(
            'info',
            f'Attempting to list files in {source_description} playbooks directory: {playbooks_dir}',
        )
        files = cast(Any, self.list_files(str(playbooks_dir)))
        if not files:
            self.log(
                'debug',
                f'No files found in {source_description} playbooks directory: {playbooks_dir}',
            )
            return loaded_playbooks
        self.log(
            'info',
            f'Found {len(files)} files in {source_description} playbooks directory',
        )
        zip_path = cast(Any, self.copy_from(str(playbooks_dir)))
        playbook_folder = tempfile.mkdtemp()
        try:
            if zip_path.is_dir():
                shutil.copytree(zip_path, playbook_folder, dirs_exist_ok=True)
            else:
                with ZipFile(zip_path, 'r') as zip_file:
                    zip_file.extractall(playbook_folder)
                zip_path.unlink()
            repo_agents, knowledge_agents = load_playbooks_from_dir(playbook_folder)
            self.log(
                'info',
                f'Loaded {len(repo_agents)} repo agents and {
                    len(knowledge_agents)
                } knowledge agents from {source_description}',
            )
            loaded_playbooks.extend(repo_agents.values())
            loaded_playbooks.extend(knowledge_agents.values())
        except Exception as e:
            self.log('error', f'Failed to load agents from {source_description}: {e}')
        finally:
            shutil.rmtree(playbook_folder)
        return loaded_playbooks

    def get_playbooks_from_org_or_user(
        self, selected_repository: str
    ) -> list[BasePlaybook]:
        """Load playbooks from the organization or user level repository.

        For example, if the repository is github.com/acme-co/api, this will check if
        github.com/acme-co/.grinta exists. If it does, it will clone it and load
        the playbooks from the ./playbooks/ folder.

        Args:
            selected_repository: The repository path (e.g., "github.com/acme-co/api")

        Returns:
            A list of loaded playbooks from the org/user level repository
        """
        self.log(
            'debug',
            f'Starting org-level playbook loading for repository: {selected_repository}',
        )

        org_name = self._extract_org_name(selected_repository)
        if not org_name:
            return []

        org_config_repo = self._get_org_config_repo_path(selected_repository, org_name)
        self.log('info', f'Checking for org-level playbooks at {org_config_repo}')

        return self._clone_and_load_org_playbooks(org_name, org_config_repo)

    def get_playbooks_from_selected_repo(
        self, selected_repository: str | None
    ) -> list[BasePlaybook]:
        """Load playbooks from the selected repository.

        If selected_repository is None, load playbooks from the current workspace.
        This is the main entry point for loading playbooks.

        This method also checks for user/org level playbooks stored in a repository.
        For example, if the repository is github.com/acme-co/api, it will also check for
        github.com/acme-co/.grinta and load playbooks from there if it exists.
        """
        playbooks_dir = workspace_grinta_root(self.workspace_root) / 'playbooks'
        repo_root = None
        loaded_playbooks: list[BasePlaybook] = []
        if selected_repository:
            org_playbooks = self.get_playbooks_from_org_or_user(selected_repository)
            loaded_playbooks.extend(org_playbooks)
            repo_root = self.workspace_root / selected_repository.split('/')[-1]
            playbooks_dir = repo_root / '.grinta' / 'playbooks'
        self.log(
            'info',
            f'Selected repo: {selected_repository}, loading playbooks from {playbooks_dir} (inside runtime)',
        )
        obs: Any = None
        try:
            obs = cast(
                Any,
                self.read(
                    FileReadAction(path=str(self.workspace_root / '.APP_instructions'))
                ),
            )
        except OSError:
            obs = ErrorObservation('File not found')
        if (
            isinstance(obs, ErrorObservation)
            or (isinstance(obs, FileReadObservation) and not obs.content)
        ) and repo_root is not None:
            self.log(
                'debug',
                f'.APP_instructions not present, trying to load from repository playbooks_dir={playbooks_dir!r}',
            )
            try:
                obs = cast(
                    Any,
                    self.read(
                        FileReadAction(path=str(repo_root / '.APP_instructions'))
                    ),
                )
            except OSError:
                obs = ErrorObservation('File not found')
        if isinstance(obs, FileReadObservation) and obs.content:
            self.log('info', 'APP_instructions playbook loaded.')
            loaded_playbooks.append(
                BasePlaybook.load(
                    path='.APP_instructions',
                    playbook_dir=None,
                    file_content=obs.content,
                ),
            )
        repo_playbooks = self._load_playbooks_from_directory(
            playbooks_dir, 'repository'
        )
        loaded_playbooks.extend(repo_playbooks)
        return loaded_playbooks

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_org_name(self, selected_repository: str) -> str | None:
        """Extract organization name from repository path."""
        repo_parts = selected_repository.split('/')
        if len(repo_parts) < 2:
            self.log(
                'warning',
                f'Repository path has insufficient parts ({len(repo_parts)} < 2), skipping org-level playbooks',
            )
            return None

        org_name = repo_parts[-2]
        self.log('info', f'Extracted org/user name: {org_name}')
        return org_name

    def _get_org_config_repo_path(self, selected_repository: str, org_name: str) -> str:
        """Get org-level config repository path."""
        return f'{org_name}/.grinta'

    def _clone_and_load_org_playbooks(
        self, org_name: str, org_config_repo: str
    ) -> list[BasePlaybook]:
        """Clone org config repo and load playbooks."""
        org_repo_dir = self.workspace_root / f'org_app_{org_name}'
        self.log('debug', f'Creating temporary directory for org repo: {org_repo_dir}')

        try:
            remote_url = call_async_from_sync(
                self.provider_handler.get_authenticated_git_url,
                GENERAL_TIMEOUT,
                org_config_repo,
            )
        except Exception as e:
            from backend.core.provider_types import AuthenticationError

            if isinstance(e, AuthenticationError):
                self.log(
                    'debug',
                    f'org-level playbook directory {org_config_repo} not found: {e!s}',
                )
            return []

        return self._execute_clone_and_load(org_repo_dir, remote_url, org_config_repo)

    def _execute_clone_and_load(
        self, org_repo_dir, remote_url: str, org_config_repo: str
    ) -> list[BasePlaybook]:
        """Execute git clone and load playbooks."""
        clone_cmd = (
            f'GIT_TERMINAL_PROMPT=0 git clone --depth 1 {remote_url} {org_repo_dir}'
        )
        self.log('info', 'Executing clone command for org-level repo')

        action = CmdRunAction(command=clone_cmd)
        obs = cast(Any, self.run_action(action))

        if isinstance(obs, CmdOutputObservation) and obs.exit_code == 0:
            return self._load_and_cleanup_org_playbooks(org_repo_dir, org_config_repo)
        self._log_clone_failure(obs, org_config_repo)
        return []

    def _load_and_cleanup_org_playbooks(
        self, org_repo_dir, org_config_repo: str
    ) -> list[BasePlaybook]:
        """Load playbooks and cleanup cloned repo."""
        self.log(
            'info', f'Successfully cloned org-level playbooks from {org_config_repo}'
        )
        org_playbooks_dir = org_repo_dir / 'playbooks'
        self.log('info', f'Looking for playbooks in directory: {org_playbooks_dir}')

        loaded_playbooks = self._load_playbooks_from_directory(
            org_playbooks_dir, 'org-level'
        )
        self.log(
            'info',
            f'Loaded {len(loaded_playbooks)} playbooks from org-level repository {org_config_repo}',
        )

        # Cleanup
        action = CmdRunAction(command=f'rm -rf {org_repo_dir}')
        cast(Any, self.run_action(action))

        return loaded_playbooks

    def _log_clone_failure(self, obs, org_config_repo: str) -> None:
        """Log clone failure details."""
        clone_error_msg = (
            obs.content if isinstance(obs, CmdOutputObservation) else 'Unknown error'
        )
        exit_code = obs.exit_code if isinstance(obs, CmdOutputObservation) else 'N/A'
        self.log(
            'info',
            f'No org-level playbooks found at {org_config_repo} (exit_code: {exit_code})',
        )
        self.log('debug', f'Clone command output: {clone_error_msg}')
