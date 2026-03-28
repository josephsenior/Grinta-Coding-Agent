"""Mixin for managing environment variables in runtime shells.

Extracts PowerShell / Bash env-var injection from ``Runtime`` so that
``base.py`` stays focused on the core runtime contract.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from backend.core.logger import forge_logger as logger
from backend.ledger.action import CmdRunAction
from backend.ledger.observation import CmdOutputObservation

if TYPE_CHECKING:
    from backend.ledger.observation import Observation


class EnvManagerMixin:
    """Mixin that adds shell environment-variable management to a Runtime."""

    if TYPE_CHECKING:

        def run(self, action: CmdRunAction) -> Observation: ...

    # ------------------------------------------------------------------
    # Shell detection
    # ------------------------------------------------------------------

    def _uses_windows_shell(self) -> bool:
        """Determine if runtime shell commands should use PowerShell syntax."""
        return False

    # ------------------------------------------------------------------
    # PowerShell helpers
    # ------------------------------------------------------------------

    def _build_powershell_env_cmd(self, env_vars: dict[str, str]) -> str:
        """Build PowerShell command to set environment variables."""
        cmd = "".join(
            f"$env:{key} = {json.dumps(value)}; " for key, value in env_vars.items()
        )
        return cmd.strip() if cmd else ""

    def _run_cmd_action(self, action: CmdRunAction) -> Observation:
        """Run command action and return normalized observation type."""
        return self.run(action)

    def _add_env_vars_to_powershell(self, env_vars: dict[str, str]) -> None:
        """Add environment variables to PowerShell session."""
        cmd = self._build_powershell_env_cmd(env_vars)
        if not cmd:
            return
        logger.debug("Adding env vars to PowerShell")
        action = CmdRunAction(command=cmd, blocking=True, hidden=True)
        action.set_hard_timeout(30)
        obs = self._run_cmd_action(action)
        if not isinstance(obs, CmdOutputObservation) or obs.exit_code != 0:
            msg = f"Failed to add env vars [{env_vars.keys()}] to environment: {obs.content}"
            raise RuntimeError(msg)
        logger.debug("Added env vars to PowerShell session: %s", env_vars.keys())

    # ------------------------------------------------------------------
    # Bash helpers
    # ------------------------------------------------------------------

    def _build_bash_env_commands(self, env_vars: dict[str, str]) -> tuple[str, str]:
        """Build bash commands to set environment variables."""
        cmd = ""
        bashrc_cmd = ""
        for key, value in env_vars.items():
            cmd += f"export {key}={json.dumps(value)}; "
            bashrc_cmd += f'touch ~/.bashrc; grep -q "^export {
                key
            }=" ~/.bashrc || echo "export {key}={json.dumps(value)}" >> ~/.bashrc; '
        return cmd.strip() if cmd else "", bashrc_cmd.strip() if bashrc_cmd else ""

    def _add_env_vars_to_bash(self, env_vars: dict[str, str]) -> None:
        """Add environment variables to bash session and .bashrc."""
        cmd, bashrc_cmd = self._build_bash_env_commands(env_vars)
        if not cmd:
            return

        # Add to current session
        logger.debug("Adding env vars to bash")
        action = CmdRunAction(command=cmd, blocking=True, hidden=True)
        action.set_hard_timeout(30)
        obs = self._run_cmd_action(action)
        if not isinstance(obs, CmdOutputObservation) or obs.exit_code != 0:
            msg = f"Failed to add env vars [{env_vars.keys()}] to environment: {obs.content}"
            raise RuntimeError(msg)

        # Add to .bashrc for persistence
        logger.debug("Adding env var to .bashrc: %s", env_vars.keys())
        bashrc_action = CmdRunAction(command=bashrc_cmd, blocking=True, hidden=True)
        bashrc_action.set_hard_timeout(30)
        obs = self._run_cmd_action(bashrc_action)
        if not isinstance(obs, CmdOutputObservation) or obs.exit_code != 0:
            msg = (
                f"Failed to add env vars [{env_vars.keys()}] to .bashrc: {obs.content}"
            )
            raise RuntimeError(msg)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_env_vars(self, env_vars: dict[str, str]) -> None:
        """Add environment variables to runtime.

        Sets variables in the shell environment.

        Args:
            env_vars: Dictionary of environment variables to add
        """
        env_vars = {key.upper(): value for key, value in env_vars.items()}
        os.environ.update(env_vars)

        # Add to shell environment
        try:
            if self._uses_windows_shell():
                self._add_env_vars_to_powershell(env_vars)
            else:
                self._add_env_vars_to_bash(env_vars)
        except RuntimeError as exc:
            logger.warning(
                "Unable to apply shell env vars %s: %s",
                list(env_vars.keys()),
                exc,
            )
