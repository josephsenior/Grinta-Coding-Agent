"""Autonomy controller for managing autonomous agent behavior.

This module provides the AutonomyController class which determines when the agent
should request user confirmation and when it should automatically retry on errors.

Note: Only handles ImportError retry. LLM errors are already handled by LLM RetryMixin.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING

from backend.ledger.action import (
    Action,
    CmdRunAction,
    FileEditAction,
    FileWriteAction,
)
from backend.security.command_analyzer import CommandAnalyzer, RiskCategory

if TYPE_CHECKING:
    from backend.core.config.agent_config import AgentConfig

logger = logging.getLogger(__name__)


class AutonomyLevel(str, Enum):
    """Agent autonomy levels."""

    SUPERVISED = 'supervised'  # Always ask for confirmation
    BALANCED = 'balanced'  # Ask for high-risk actions only
    FULL = 'full'  # Never ask for confirmation


class AutonomyController:
    """Controller for managing autonomous agent behavior.

    Determines when actions require user confirmation and when errors should
    trigger automatic retries based on the configured autonomy level.
    """

    def __init__(self, config: AgentConfig) -> None:
        """Initialize the autonomy controller.

        Args:
            config: Agent configuration containing autonomy settings

        """
        self.autonomy_level = getattr(
            config, 'autonomy_level', AutonomyLevel.BALANCED.value
        )
        self.auto_retry = getattr(config, 'auto_retry_on_error', False)
        self.max_iterations = getattr(config, 'max_autonomous_iterations', 0)
        self.stuck_detection = getattr(config, 'stuck_detection_enabled', False)
        self.stuck_threshold = getattr(config, 'stuck_threshold_iterations', 0)

        logger.info(
            'AutonomyController initialized with level=%s, auto_retry=%s',
            self.autonomy_level,
            self.auto_retry,
        )

    def should_request_confirmation(self, action: Action) -> bool:
        """Determine if an action requires user confirmation.

        Args:
            action: The action to evaluate

        Returns:
            True if confirmation is needed, False otherwise

        """
        if self.autonomy_level == AutonomyLevel.FULL.value:
            # Full autonomy: never ask
            return False
        if self.autonomy_level == AutonomyLevel.SUPERVISED.value:
            # Supervised: always ask
            return True
        # Balanced: ask only for high-risk actions
        return self._is_high_risk_action(action)

    def _is_high_risk_action(self, action: Action) -> bool:
        """Determine if an action is high-risk.

        Delegates command classification to
        :class:`backend.security.command_analyzer.CommandAnalyzer` so that
        autonomy decisions stay aligned with the security pipeline (which
        already handles PowerShell, fork bombs, base64 obfuscation,
        ``$(printf %s rm)`` style substitution, etc.). File-write/edit
        actions are still treated as not-high-risk here — the safety
        validator and tool-level checks gate sensitive paths.

        Args:
            action: The action to evaluate

        Returns:
            True if the action is high-risk
        """
        if isinstance(action, CmdRunAction):
            analyzer = getattr(self, '_command_analyzer', None)
            if analyzer is None:
                analyzer = CommandAnalyzer({})
                self._command_analyzer = analyzer
            assessment = analyzer.analyze_command(action.command)
            if assessment.risk_category in (
                RiskCategory.HIGH,
                RiskCategory.CRITICAL,
            ):
                logger.warning(
                    'High-risk command detected (%s): %s',
                    assessment.risk_category.value,
                    action.command,
                )
                return True

        # File operations are generally safe in isolated environments
        # but we could add checks for sensitive paths
        if isinstance(action, FileWriteAction | FileEditAction):
            # Could add checks for sensitive files like /etc/passwd
            pass

        return False

    def should_retry_on_error(self, error: Exception, attempts: int) -> bool:
        """Determine if error should trigger automatic retry (ImportError only).

        Note: Only handles ImportError for auto pip install. LLM errors
        (RateLimitError, APIError, etc.) are already retried 6 times with
        exponential backoff by the LLM RetryMixin.

        Args:
            error: The exception that occurred
            attempts: Number of attempts made so far

        Returns:
            True if the error should be retried (only for ImportError)

        """
        if not self.auto_retry:
            return False

        # Only 1 retry for ImportError (for pip install)
        if attempts >= 1:
            logger.info('Max retry attempts reached (%d), not retrying', attempts)
            return False

        # Only retry ImportError (for auto pip install)
        is_import_error = isinstance(error, ImportError | ModuleNotFoundError)

        if is_import_error:
            logger.info(
                'ImportError detected, will auto-install package (attempt %d/1)',
                attempts + 1,
            )

        return is_import_error
