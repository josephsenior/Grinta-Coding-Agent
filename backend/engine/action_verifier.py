"""Post-action verification to prevent hallucinations and ensure tool execution success.

This module provides reliability mechanisms used by industry-leading AI tools like Devin,
Cursor, and OpenAI Code Interpreter to verify that claimed actions actually succeeded.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from backend.core.logger import app_logger as logger
from backend.ledger.action import CmdRunAction, FileEditAction
from backend.ledger.observation import CmdOutputObservation, ErrorObservation

if TYPE_CHECKING:
    from backend.ledger.action import Action
    from backend.ledger.observation import Observation
    from backend.execution.base import Runtime


class ActionVerifier:
    """Verifies that actions actually succeeded.

    This prevents hallucinations where the agent claims to have done something
    but didn't actually execute the tool.

    Used by industry leaders:
    - Devin: Verifies every file operation
    - Cursor: Validates tool execution results
    - OpenAI: Checks runtime state changes
    """

    def __init__(self, runtime: Runtime):
        """Initialize the action verifier.

        Args:
            runtime: The runtime environment to verify actions in

        """
        self.runtime = runtime
        self.verification_enabled = True

    async def verify_action(
        self, action: Action
    ) -> tuple[bool, str, Observation | None]:
        """Verify an action actually succeeded.

        Args:
            action: The action that was executed

        Returns:
            Tuple of (success: bool, message: str, verification_observation: Observation | None)

        """
        if not self.verification_enabled:
            return True, "Verification disabled", None

        # Route to appropriate verification method
        if isinstance(action, FileEditAction):
            return await self._verify_file_edit_action(action)

        # No verification needed for other action types
        return True, "No verification needed", None

    async def _verify_file_edit_action(
        self, action: FileEditAction
    ) -> tuple[bool, str, Observation | None]:
        """Verify a file was actually created/edited.

        Args:
            action: The FileEditAction to verify

        Returns:
            Tuple of (success, message, observation)

        """
        try:
            path = action.path

            # Verify file exists (cross-platform: works on both bash and PowerShell)
            verify_cmd = CmdRunAction(
                command=f"python3 -c \"import os; print('FILE_EXISTS' if os.path.isfile('{path}') else 'FILE_MISSING')\"",
                thought="Verifying file was created/edited",
            )
            verify_obs = await self._run_runtime_action(verify_cmd)

            if not isinstance(verify_obs, CmdOutputObservation):
                return (
                    False,
                    "❌ Verification failed: unexpected observation type",
                    verify_obs,
                )

            if "FILE_MISSING" in verify_obs.content:
                logger.error(
                    "File verification failed: %s does not exist despite tool call",
                    path,
                )
                return (
                    False,
                    f"❌ CRITICAL: File {path} was NOT created despite edit_file tool call",
                    verify_obs,
                )

            # Verify file has content (cross-platform)
            content_cmd = CmdRunAction(
                command=f"python3 -c \"import os; p='{path}'; lines=sum(1 for _ in open(p, encoding='utf-8')); size=os.path.getsize(p); print(f'{{lines}} lines, {{size}} bytes')\"",
                thought="Verifying file content",
            )
            content_obs = await self._run_runtime_action(content_cmd)

            if not isinstance(content_obs, CmdOutputObservation):
                return (
                    True,
                    f"✅ File {path} exists (content check skipped)",
                    content_obs,
                )

            # Extract line count
            lines = 0
            try:
                first_line = content_obs.content.split("\n")[0]
                lines = int(first_line.strip().split()[0])
            except (ValueError, IndexError):
                pass

            if lines == 0:
                logger.warning("File %s exists but is empty", path)
                return (
                    True,
                    f"⚠️ File {path} created but is empty (0 lines)",
                    content_obs,
                )

            logger.info(
                "✅ File verification successful: %s (%s lines)", path, lines
            )
            return (
                True,
                f"✅ Verified: {path} created successfully ({lines} lines)",
                content_obs,
            )

        except Exception as e:
            logger.error("Verification error for %s: %s", action.path, e)
            error_obs = ErrorObservation(content=f"Verification failed: {str(e)}")
            return False, f"❌ Verification error: {str(e)}", error_obs

    def should_verify(self, action: Action) -> bool:
        """Determine if an action should be verified.

        Args:
            action: The action to check

        Returns:
            True if this action type should be verified

        """
        # File operations should always be verified
        if isinstance(action, FileEditAction):
            return True

        # Future: add more action types to verify
        # - CmdRunAction for critical commands

        return False

    async def _run_runtime_action(self, action: Action) -> Observation:
        """Execute a runtime action without blocking the event loop."""
        return await asyncio.to_thread(self.runtime.run_action, action)
