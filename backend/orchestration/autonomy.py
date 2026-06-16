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
    ActionSecurityRisk,
    BlackboardAction,
    BrowseInteractiveAction,
    BrowserToolAction,
    CmdRunAction,
    DelegateTaskAction,
    FileEditAction,
    FileWriteAction,
    TerminalInputAction,
    TerminalRunAction,
)
from backend.security.command_analyzer import CommandAnalyzer, RiskCategory

if TYPE_CHECKING:
    from backend.core.config.agent_config import AgentConfig

logger = logging.getLogger(__name__)


class AutonomyLevel(str, Enum):
    """Agent autonomy levels.

    All levels share identical execution, prompting, and retry behaviour.
    The only difference is *when* the agent stops to ask the user before
    running an action:

    - ``CONSERVATIVE``: ask for every runnable action.
    - ``BALANCED``: ask only for actions classified as high-risk.
    - ``FULL``: never ask; the safety validator still blocks forbidden ops.
    """

    CONSERVATIVE = 'conservative'
    BALANCED = 'balanced'
    FULL = 'full'


def normalize_autonomy_level(level: object) -> str:
    """Return the stable string value for an autonomy level."""
    raw = getattr(level, 'value', level)
    text = str(raw or AutonomyLevel.BALANCED.value).strip().lower()
    if '.' in text:
        text = text.rsplit('.', 1)[-1].lower()
    return text


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
        # Per-session "always allow" memory: signatures of actions the user
        # has chosen to whitelist for the remainder of the session. Cleared
        # on process exit; never persisted to disk.
        self._always_allow: set[str] = set()

        logger.info(
            'AutonomyController initialized with level=%s, auto_retry=%s',
            self.autonomy_level,
            self.auto_retry,
        )

    @staticmethod
    def action_signature(action: Action) -> str:
        """Stable per-session key used by the always-allow memory.

        For commands we use the exact command string; for file actions we
        use ``<type>:<path>``. Anything else falls back to the type name.
        """
        if isinstance(action, CmdRunAction):
            return f'cmd:{action.command}'
        if isinstance(action, TerminalRunAction):
            return f'terminal-run:{action.cwd or ""}:{action.command}'
        if isinstance(action, TerminalInputAction):
            return f'terminal-input:{action.session_id}:{action.input}'
        if isinstance(action, FileWriteAction | FileEditAction):
            path = getattr(action, 'path', '') or ''
            command = getattr(action, 'command', '') or ''
            return f'{type(action).__name__}:{path}:{command}'
        if isinstance(action, BrowserToolAction):
            return f'browser:{action.command}:{action.params}'
        if isinstance(action, BlackboardAction):
            return f'blackboard:{action.command}:{action.key}'
        if isinstance(action, DelegateTaskAction):
            return (
                f'delegate:{action.run_in_background}:'
                f'{len(action.parallel_tasks)}:{action.task_description}'
            )
        return type(action).__name__

    def remember_always_allow(self, action: Action) -> None:
        """Whitelist this exact action signature for the rest of the session."""
        sig = self.action_signature(action)
        self._always_allow.add(sig)
        logger.info('Always-allow registered for session: %s', sig)

    def is_always_allowed(self, action: Action) -> bool:
        sig = self.action_signature(action)
        if sig in self._always_allow:
            return True
        for allowed in self._always_allow:
            if allowed.endswith('*') and sig.startswith(allowed[:-1]):
                return True
        return False

    def should_request_confirmation(self, action: Action) -> bool:
        """Determine if an action requires user confirmation.

        Args:
            action: The action to evaluate

        Returns:
            True if confirmation is needed, False otherwise

        """
        # Per-session whitelist always wins (except for full mode which
        # already bypasses confirmation entirely).
        if self.is_always_allowed(action):
            return False
        level = normalize_autonomy_level(self.autonomy_level)
        if level == AutonomyLevel.FULL.value:
            # Full autonomy: never ask
            return False
        if level == AutonomyLevel.CONSERVATIVE.value:
            # Conservative: always ask
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
        risk = getattr(action, 'security_risk', ActionSecurityRisk.UNKNOWN)
        if risk == ActionSecurityRisk.HIGH:
            return True

        command = ''
        if isinstance(action, CmdRunAction):
            command = action.command
        elif isinstance(action, TerminalRunAction):
            command = action.command
        elif isinstance(action, TerminalInputAction) and not action.is_control:
            command = action.input.rstrip('\r\n')

        if command:
            analyzer = getattr(self, '_command_analyzer', None)
            if analyzer is None:
                analyzer = CommandAnalyzer({})
                self._command_analyzer = analyzer
            assessment = analyzer.analyze_command(command)
            if assessment.risk_category in (
                RiskCategory.HIGH,
                RiskCategory.CRITICAL,
            ):
                logger.warning(
                    'High-risk command detected (%s): %s',
                    assessment.risk_category.value,
                    command,
                )
                return True

        if isinstance(action, FileEditAction):
            return True

        if isinstance(action, BrowseInteractiveAction | BrowserToolAction):
            return True

        if isinstance(action, DelegateTaskAction):
            return True

        if isinstance(action, BlackboardAction) and action.command.lower() == 'set':
            return True

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
