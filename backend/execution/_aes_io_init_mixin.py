"""_AesIoInitMixin: extracted from action_execution_server_io.

Split of the original RuntimeExecutorIOAndTerminalMixin to keep the
parent module under the per-file LOC budget. Pure code motion —
method bodies are byte-identical to the pre-split version.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.core.logger import app_logger as logger
from backend.execution.action_execution_server_helpers import (
    build_env_check_command as _build_env_check_command_impl,
)
from backend.execution.action_execution_server_helpers import (
    build_shell_git_config_command as _build_shell_git_config_command_impl,
)
from backend.execution.action_execution_server_helpers import (
    extract_failure_signature as _extract_failure_signature_impl,
)
from backend.execution.action_execution_server_helpers import (
    init_shell_commands as _init_shell_commands_impl,
)
from backend.execution.action_execution_server_helpers import (
    should_rewrite_python3_to_python as _should_rewrite_python3_to_python_impl,
)
from backend.execution.action_execution_server_helpers import (
    strip_ansi_obs_text as _strip_ansi_obs_text_impl,
)
from backend.execution.action_execution_server_helpers import (
    uses_powershell_shell_contract as _uses_powershell_shell_contract_impl,
)
from backend.ledger.observation import (
    Observation,
)

if TYPE_CHECKING:
    pass


class _AesIoInitMixin:
    """Mixin extracted from RuntimeExecutorIOAndTerminalMixin."""

    def initialized(self) -> bool:
        """Check if action execution server has completed initialization."""
        return self._initialized

    def _init_shell_commands(self):
        _init_shell_commands_impl(self)

    def _build_shell_git_config_command(self, use_powershell: bool) -> str:
        return _build_shell_git_config_command_impl(self, use_powershell)

    @staticmethod
    def _build_env_check_command(use_powershell: bool) -> str:
        return _build_env_check_command_impl(use_powershell)

    def _uses_powershell_shell_contract(self) -> bool:
        return _uses_powershell_shell_contract_impl(self)

    async def run_action(self, action) -> Observation:
        """Execute any action through action execution server."""
        async with self.lock:
            action_type = action.action
            obs = await getattr(self, action_type)(action)

        if hasattr(obs, 'content') and isinstance(obs.content, str):
            obs.content = self._strip_ansi_obs_text(obs.content)
        if hasattr(obs, 'path') and isinstance(obs.path, str):
            obs.path = self._strip_ansi_obs_text(obs.path)
        if hasattr(obs, 'message') and isinstance(obs.message, str):
            try:
                obs.message = self._strip_ansi_obs_text(obs.message)
            except AttributeError:
                pass
        return obs

    @staticmethod
    def _strip_ansi_obs_text(text: str) -> str:
        return _strip_ansi_obs_text_impl(text)

    def _should_rewrite_python3_to_python(self) -> bool:
        return _should_rewrite_python3_to_python_impl(self)

    @staticmethod
    def _extract_failure_signature(content: str) -> str:
        return _extract_failure_signature_impl(content)

    @staticmethod
    def _append_debug_trace(payload: dict[str, Any]) -> None:
        logger.debug(
            payload.get('message', 'exec_trace'),
            extra={
                'msg_type': 'EXEC_TRACE',
                'hypothesis_id': payload.get('hypothesisId'),
                'location': payload.get('location'),
                'trace_data': payload.get('data'),
            },
        )
