"""_AesIoFileMixin: extracted from action_execution_server_io.

Split of the original RuntimeExecutorIOAndTerminalMixin to keep the
parent module under the per-file LOC budget. Pure code motion —
method bodies are byte-identical to the pre-split version.
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

from binaryornot.check import is_binary

from backend.core.enums import FileReadSource
from backend.core.logger import app_logger as logger
from backend.execution.action_execution_server_helpers import (
    edit_try_directory_view as _edit_try_directory_view_impl,
)
from backend.execution.action_execution_server_helpers import (
    edit_via_file_editor as _edit_via_file_editor_impl,
)
from backend.execution.action_execution_server_helpers import (
    handle_aci_file_read as _handle_aci_file_read_impl,
)
from backend.execution.action_execution_server_helpers import (
    is_auto_lint_enabled as _is_auto_lint_enabled_impl,
)
from backend.execution.action_execution_server_helpers import (
    resolve_path as _resolve_path_impl,
)
from backend.execution.file_operations import (
    ensure_directory_exists,
    handle_file_read_errors,
    read_image_file,
    read_pdf_file,
    read_text_file,
    read_video_file,
    write_file_content,
)
from backend.ledger.action import (
    FileEditAction,
    FileReadAction,
    FileWriteAction,
)
from backend.ledger.observation import (
    ErrorObservation,
    FileReadObservation,
    FileWriteObservation,
    Observation,
)

if TYPE_CHECKING:
    pass


class _AesIoFileMixin:
    """Mixin extracted from RuntimeExecutorIOAndTerminalMixin."""

    def _resolve_path(self, path: str, working_dir: str) -> str:
        return _resolve_path_impl(self, path, working_dir)

    def _handle_aci_file_read(self, action: FileReadAction) -> FileReadObservation:
        return _handle_aci_file_read_impl(self, action)

    async def read(self, action: FileReadAction) -> Observation:
        bash_session, shell_err = await asyncio.to_thread(
            self._get_or_recreate_default_shell_session
        )
        if shell_err is not None:
            return shell_err
        assert bash_session is not None

        if os.path.isfile(action.path) and is_binary(action.path):
            return ErrorObservation('ERROR_BINARY_FILE')

        impl_source = action.impl_source
        if impl_source == FileReadSource.FILE_EDITOR or str(impl_source).lower() in {
            'file_editor',
            'filereadsource.file_editor',
        }:
            return self._handle_aci_file_read(action)

        working_dir = bash_session.cwd
        try:
            filepath = self._resolve_workspace_file_path(action.path, working_dir)
        except PermissionError:
            return ErrorObservation(
                f"You're not allowed to access this path: {action.path}. You can only access paths inside the workspace."
            )

        return self._read_file_by_type(filepath, action, working_dir)

    def _read_file_by_type(
        self, filepath: str, action: FileReadAction, working_dir: str
    ) -> Observation:
        try:
            if filepath.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif')):
                return read_image_file(filepath)
            if filepath.lower().endswith('.pdf'):
                return read_pdf_file(filepath)
            if filepath.lower().endswith(('.mp4', '.webm', '.ogg')):
                return read_video_file(filepath)
            return read_text_file(filepath, action)
        except Exception:
            return handle_file_read_errors(filepath, working_dir)

    async def write(self, action: FileWriteAction) -> Observation:
        bash_session, shell_err = await asyncio.to_thread(
            self._get_or_recreate_default_shell_session
        )
        if shell_err is not None:
            return shell_err
        assert bash_session is not None

        working_dir = bash_session.cwd
        try:
            filepath = self._resolve_workspace_file_path(action.path, working_dir)
        except PermissionError as exc:
            return ErrorObservation(f'Permission error on {action.path}: {exc}')

        try:
            ensure_directory_exists(filepath)
            file_exists = os.path.exists(filepath)
            error_obs = write_file_content(filepath, action, file_exists)
            if error_obs:
                return error_obs
            return FileWriteObservation(
                content=f'Wrote file: {action.path}',
                path=action.path,
            )
        except Exception as exc:
            logger.error('Error writing file %s: %s', action.path, exc, exc_info=True)
            return ErrorObservation(f'Failed to write file {action.path}: {exc}')

    def _edit_try_directory_view(
        self, filepath: str, path_for_obs: str, action: FileEditAction
    ) -> Observation | None:
        return _edit_try_directory_view_impl(self, filepath, path_for_obs, action)

    def _edit_via_file_editor(self, action: FileEditAction) -> Observation:
        return _edit_via_file_editor_impl(self, action)

    def _is_auto_lint_enabled(self) -> bool:
        return _is_auto_lint_enabled_impl(self)

    async def edit(self, action: FileEditAction) -> Observation:
        bash_session, shell_err = await asyncio.to_thread(
            self._get_or_recreate_default_shell_session
        )
        if shell_err is not None:
            return shell_err
        assert bash_session is not None
        working_dir = bash_session.cwd
        if (action.command or '').strip().lower() == 'multi_edit':
            return self._edit_via_file_editor(action)
        try:
            filepath = self._resolve_workspace_file_path(action.path, working_dir)
        except PermissionError:
            return ErrorObservation(
                f"You're not allowed to access this path: {action.path}. You can only access paths inside the workspace."
            )

        dir_view = self._edit_try_directory_view(filepath, action.path, action)
        if dir_view is not None:
            return dir_view

        if not action.command:
            return ErrorObservation(
                'Legacy edit_file actions are no longer supported. Use the dedicated file tools instead.'
            )

        return self._edit_via_file_editor(action)
