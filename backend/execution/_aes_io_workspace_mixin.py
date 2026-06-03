"""_AesIoWorkspaceMixin: extracted from action_execution_server_io.

Split of the original RuntimeExecutorIOAndTerminalMixin to keep the
parent module under the per-file LOC budget. Pure code motion —
method bodies are byte-identical to the pre-split version.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.execution.action_execution_server_helpers import (
    annotate_environment_errors as _annotate_environment_errors_impl,
)
from backend.execution.action_execution_server_helpers import (
    detect_powershell_in_bash_mismatch as _detect_powershell_in_bash_mismatch_impl,
)
from backend.execution.action_execution_server_helpers import (
    detect_scaffold_setup_failure as _detect_scaffold_setup_failure_impl,
)
from backend.execution.action_execution_server_helpers import (
    evaluate_interactive_terminal_command as _evaluate_interactive_terminal_command_impl,
)
from backend.execution.action_execution_server_helpers import (
    is_sandboxed_local as _is_sandboxed_local_impl,
)
from backend.execution.action_execution_server_helpers import (
    is_workspace_restricted_profile as _is_workspace_restricted_profile_impl,
)
from backend.execution.action_execution_server_helpers import (
    predict_interactive_cwd_change as _predict_interactive_cwd_change_impl,
)
from backend.execution.action_execution_server_helpers import (
    resolve_effective_cwd as _resolve_effective_cwd_impl,
)
from backend.execution.action_execution_server_helpers import (
    resolve_workspace_file_path as _resolve_workspace_file_path_impl,
)
from backend.execution.action_execution_server_helpers import (
    validate_interactive_session_scope as _validate_interactive_session_scope_impl,
)
from backend.execution.action_execution_server_helpers import (
    validate_workspace_scoped_cwd as _validate_workspace_scoped_cwd_impl,
)
from backend.execution.action_execution_server_helpers import (
    workspace_root as _workspace_root_impl,
)
from backend.ledger.observation import (
    CmdOutputObservation,
    ErrorObservation,
)

if TYPE_CHECKING:
    pass


class _AesIoWorkspaceMixin:
    """Mixin extracted from RuntimeExecutorIOAndTerminalMixin."""

    def _workspace_root(self) -> Path:
        return _workspace_root_impl(self)

    def _is_workspace_restricted_profile(self) -> bool:
        return _is_workspace_restricted_profile_impl(self)

    def _is_sandboxed_local(self) -> bool:
        return _is_sandboxed_local_impl(self)

    def _validate_interactive_session_scope(
        self, session_id: str, session: Any
    ) -> ErrorObservation | None:
        return _validate_interactive_session_scope_impl(self, session_id, session)

    def _predict_interactive_cwd_change(
        self, command: str, current_cwd: Path
    ) -> tuple[Path | None, str | None]:
        return _predict_interactive_cwd_change_impl(self, command, current_cwd)

    def _evaluate_interactive_terminal_command(
        self, command: str, current_cwd: Path
    ) -> tuple[Path | None, ErrorObservation | None]:
        return _evaluate_interactive_terminal_command_impl(self, command, current_cwd)

    def _resolve_effective_cwd(
        self, requested_cwd: str | None, base_cwd: str | None = None
    ) -> Path:
        return _resolve_effective_cwd_impl(self, requested_cwd, base_cwd)

    def _validate_workspace_scoped_cwd(
        self,
        command: str,
        requested_cwd: str | None,
        base_cwd: str | None = None,
    ) -> ErrorObservation | None:
        return _validate_workspace_scoped_cwd_impl(
            self, command, requested_cwd, base_cwd
        )

    def _resolve_workspace_file_path(self, path: str, working_dir: str) -> str:
        return _resolve_workspace_file_path_impl(self, path, working_dir)

    def _annotate_environment_errors(self, observation: CmdOutputObservation) -> None:
        _annotate_environment_errors_impl(self, observation)

    @staticmethod
    def _detect_powershell_in_bash_mismatch(command: str, content: str) -> str | None:
        return _detect_powershell_in_bash_mismatch_impl(command, content)

    @staticmethod
    def _detect_scaffold_setup_failure(command: str, content: str) -> str | None:
        return _detect_scaffold_setup_failure_impl(command, content)
