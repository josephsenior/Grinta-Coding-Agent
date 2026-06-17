"""Structural security analysis for agent actions.

Analyses ``Action`` instances *before* they are dispatched to the runtime,
producing a risk classification that the security-enforcement layer uses
**only to escalate** what the agent already declared. This module never
silently invents a non-LOW risk for an action the agent labelled — its
output is a one-way ratchet: LOW or HIGH.

The previous implementation classified into LOW/MEDIUM/HIGH using brittle
heuristics (path/command pattern lists). That tier was used as a *fallback*
when the agent omitted ``security_risk``. With ``security_risk`` now
required on write/exec tools (see ``backend.engine.tools.common``), the
fallback is no longer needed: this analyzer collapses to a single
"true-unsafe → HIGH, everything else → LOW" decision so the model's
self-assessment is the source of truth and we only override on
unambiguous danger.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.core.enums import ActionSecurityRisk
from backend.ledger.action import Action, CmdRunAction
from backend.ledger.action import FileEditAction
from backend.security.command_analyzer import CommandAnalyzer, RiskCategory

logger = logging.getLogger(__name__)

# Only the top two analyzer tiers count as true-unsafe for escalation.
# MEDIUM/LOW/NONE all collapse to LOW because they were the heuristic
# guess-tiers that this redesign retired.
_TRUE_UNSAFE_CATEGORIES: frozenset[RiskCategory] = frozenset(
    {RiskCategory.CRITICAL, RiskCategory.HIGH}
)

# Paths that are unambiguously dangerous to write to from an agent context.
# A match here escalates the action to HIGH regardless of what the agent
# declared.
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
    """Escalate-only structural analyser for agent actions.

    Returns ``ActionSecurityRisk.HIGH`` when the action matches a
    true-unsafe pattern (sensitive-path write, critical/high command tier),
    and ``ActionSecurityRisk.LOW`` otherwise. The caller in
    :mod:`backend.execution.security_enforcement` combines this with the
    agent-declared risk via ``max(declared, analyzed)``.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._cmd_analyzer = CommandAnalyzer(config or {})

    def security_risk_sync(self, action: Action) -> ActionSecurityRisk:
        """Evaluate the security risk of *action* (synchronous, no I/O).

        Safe to call from any thread, including the event-loop thread.
        The async :meth:`security_risk` delegates here.
        """
        if isinstance(action, FileEditAction):
            return self._assess_sensitive_path_write(action)

        if isinstance(action, CmdRunAction):
            return self._assess_command(action)

        return ActionSecurityRisk.LOW

    async def security_risk(self, action: Action) -> ActionSecurityRisk:
        """Evaluate the security risk of *action*.

        Returns:
            ``HIGH`` only on a true-unsafe match; ``LOW`` otherwise.
        """
        return self.security_risk_sync(action)

    # ------------------------------------------------------------------
    # File-write assessment
    # ------------------------------------------------------------------

    def _assess_sensitive_path_write(self, action: Action) -> ActionSecurityRisk:
        """Escalate writes to sensitive system / credential paths to HIGH."""
        path_lower = (getattr(action, 'path', '') or '').lower().replace('\\', '/')
        for sensitive in _SENSITIVE_WRITE_PATHS:
            if sensitive.lower().replace('\\', '/') in path_lower:
                logger.warning(
                    'Security: write to sensitive path %s -> HIGH',
                    getattr(action, 'path', ''),
                )
                return ActionSecurityRisk.HIGH
        return ActionSecurityRisk.LOW

    # ------------------------------------------------------------------
    # Command assessment (delegates to CommandAnalyzer)
    # ------------------------------------------------------------------

    def _assess_command(self, action: CmdRunAction) -> ActionSecurityRisk:
        """Escalate true-unsafe shell commands (CRITICAL/HIGH tiers) to HIGH."""
        category, reason, _recs = self._cmd_analyzer.analyze(action.command)

        if category in _TRUE_UNSAFE_CATEGORIES:
            logger.info(
                'Security: command escalated to HIGH (analyzer=%s) reason=%r cmd=%s',
                category.value,
                reason,
                action.command[:120],
            )
            return ActionSecurityRisk.HIGH

        return ActionSecurityRisk.LOW


__all__ = ['SecurityAnalyzer']
