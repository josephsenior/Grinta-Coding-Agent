"""Structural security analysis for agent actions.

Analyses ``Action`` instances *before* they are dispatched to the runtime,
producing a risk classification that downstream safety guards can act on.
"""

from __future__ import annotations

import ast
import logging
from typing import Any

from backend.core.enums import ActionSecurityRisk
from backend.ledger.action import Action, CmdRunAction, FileWriteAction
from backend.security.command_analyzer import CommandAnalyzer, RiskCategory

logger = logging.getLogger(__name__)

# Map CommandAnalyzer risk tiers → ActionSecurityRisk ints
_CMD_RISK_MAP: dict[RiskCategory, ActionSecurityRisk] = {
    RiskCategory.CRITICAL: ActionSecurityRisk.HIGH,  # ActionSecurityRisk has no CRITICAL
    RiskCategory.HIGH: ActionSecurityRisk.HIGH,
    RiskCategory.MEDIUM: ActionSecurityRisk.MEDIUM,
    RiskCategory.LOW: ActionSecurityRisk.LOW,
    RiskCategory.NONE: ActionSecurityRisk.LOW,
}

# Suspicious file-path patterns (write operations)
_SENSITIVE_WRITE_PATHS: list[str] = [
    '/etc/',
    '/usr/',
    '/bin/',
    '/sbin/',
    '/boot/',
    '/proc/',
    '/sys/',
    'C:\\Windows\\',
    'C:\\Program Files',
    '.ssh/',
    '.env',
    '.aws/',
    '.gitconfig',
    '.bashrc',
    '.zshrc',
    '.profile',
]


class SecurityAnalyzer:
    """Analyses actions for security risks using structural analysis.

    For ``CmdRunAction`` it delegates to :class:`CommandAnalyzer` for
    rich pattern matching.  For ``FileWriteAction`` it performs AST
    validation on Python files and checks for writes to sensitive paths.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._cmd_analyzer = CommandAnalyzer(config or {})

    async def security_risk(self, action: Action) -> ActionSecurityRisk:
        """Evaluate the security risk of *action*.

        Returns:
            An :class:`ActionSecurityRisk` value (LOW / MEDIUM / HIGH).
        """
        if isinstance(action, FileWriteAction):
            return self._assess_file_write(action)

        if isinstance(action, CmdRunAction):
            return self._assess_command(action)

        return ActionSecurityRisk.LOW

    # ------------------------------------------------------------------
    # File-write assessment
    # ------------------------------------------------------------------

    def _assess_file_write(self, action: FileWriteAction) -> ActionSecurityRisk:
        """Check file writes for syntax issues and sensitive-path writes."""
        risk = ActionSecurityRisk.LOW

        # 1. Sensitive path check
        path_lower = (action.path or '').lower().replace('\\', '/')
        for sensitive in _SENSITIVE_WRITE_PATHS:
            if sensitive.lower().replace('\\', '/') in path_lower:
                logger.warning('Security: write to sensitive path %s', action.path)
                risk = max(risk, ActionSecurityRisk.MEDIUM)
                break

        # 2. Python syntax validation
        if action.path.endswith('.py'):
            try:
                ast.parse(action.content)
            except SyntaxError:
                logger.warning('Security: syntax error in Python file %s', action.path)
                risk = max(risk, ActionSecurityRisk.HIGH)
            except Exception as exc:
                logger.warning('Security: could not parse %s: %s', action.path, exc)
                risk = max(risk, ActionSecurityRisk.MEDIUM)

        return risk

    # ------------------------------------------------------------------
    # Command assessment (delegates to CommandAnalyzer)
    # ------------------------------------------------------------------

    def _assess_command(self, action: CmdRunAction) -> ActionSecurityRisk:
        """Classify a shell command via :class:`CommandAnalyzer`."""
        category, reason, _recs = self._cmd_analyzer.analyze(action.command)

        mapped = _CMD_RISK_MAP.get(category, ActionSecurityRisk.LOW)

        if mapped >= ActionSecurityRisk.MEDIUM:
            logger.info(
                'Security: command risk=%s reason=%r cmd=%s',
                category.value,
                reason,
                action.command[:120],
            )

        return mapped


__all__ = ['SecurityAnalyzer']
