"""Destructive command middleware — high-priority checkpoints before destructive shell ops.

Detects patterns such as ``rm -rf``, ``git reset --hard``, ``git push --force``,
``dd if=``, ``drop table``, ``mkfs`` etc. on ``CmdRunAction``s.  When a match is
found, this middleware:

1. Logs a structured warning so the audit trail records the dangerous attempt.
2. Forces a ``RollbackManager`` checkpoint with ``checkpoint_type='before_destructive'``
   even if the regular ``RollbackMiddleware`` chose to skip (e.g. trivial-pattern
   skip).  The destructive checkpoint is exempt from the trivial-skip list and
   from auto-eviction (see ``rollback_manager._evict_oldest_checkpoints``).

The middleware is **agnostic** to OS/model — patterns operate on tokenized
shell text only.  Designed to run AFTER ``RollbackMiddleware`` so the
destructive checkpoint is the most-recent restore point.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from backend.core.logger import app_logger as logger
from backend.orchestration.tool_pipeline import ToolInvocationMiddleware

if TYPE_CHECKING:
    from backend.core.rollback.rollback_manager import RollbackManager
    from backend.orchestration.tool_pipeline import ToolInvocationContext


# Each entry: (label, compiled regex matched against raw command)
# Patterns are intentionally tokenized (\b word boundaries) so substrings like
# ``echo "rm -rf"`` inside a non-leading position still get caught (we choose
# safety over precision here — a false-positive is just an extra checkpoint).
_DESTRUCTIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ('rm-recursive-force', re.compile(r'\brm\s+(?:-[a-zA-Z]*[rRf][a-zA-Z]*\s+|--recursive\s+|--force\s+)+', re.IGNORECASE)),
    ('git-reset-hard', re.compile(r'\bgit\s+reset\s+--hard\b', re.IGNORECASE)),
    ('git-push-force', re.compile(r'\bgit\s+push\s+(?:.*\s+)?(?:--force\b|--force-with-lease\b|-f\b)', re.IGNORECASE)),
    ('git-clean', re.compile(r'\bgit\s+clean\s+-[a-zA-Z]*[fdx][a-zA-Z]*\b', re.IGNORECASE)),
    ('git-checkout-force', re.compile(r'\bgit\s+checkout\s+(?:--\s|--force\b|-f\b)', re.IGNORECASE)),
    ('git-branch-delete-force', re.compile(r'\bgit\s+branch\s+-D\b', re.IGNORECASE)),
    ('sql-drop', re.compile(r'\bdrop\s+(?:table|database|schema|index)\b', re.IGNORECASE)),
    ('sql-truncate', re.compile(r'\btruncate\s+table\b', re.IGNORECASE)),
    ('dd-write', re.compile(r'\bdd\s+(?:.*\s+)?(?:if=|of=)', re.IGNORECASE)),
    ('mkfs', re.compile(r'\bmkfs(?:\.[a-z0-9]+)?\b', re.IGNORECASE)),
    ('fdisk', re.compile(r'\b(?:fdisk|parted|gdisk)\b', re.IGNORECASE)),
    ('shred', re.compile(r'\bshred\s+', re.IGNORECASE)),
    ('format-windows', re.compile(r'\bformat\s+[a-zA-Z]:\s', re.IGNORECASE)),
    ('powershell-remove-recurse', re.compile(r'\bRemove-Item\b[^|;]*-Recurse\b[^|;]*-Force\b', re.IGNORECASE)),
    ('rmdir-recurse', re.compile(r'\b(?:Remove-Item|rmdir)\b[^|;]*\s/s\b', re.IGNORECASE)),
    ('fork-bomb', re.compile(r':\(\)\s*\{\s*:\|.*&\s*\}\s*;\s*:')),
)


def _scan_command(command: str) -> str | None:
    """Return the label of the first matching destructive pattern, else None."""
    if not command:
        return None
    for label, pattern in _DESTRUCTIVE_PATTERNS:
        if pattern.search(command):
            return label
    return None


class DestructiveCommandMiddleware(ToolInvocationMiddleware):
    """Force a high-priority checkpoint before destructive shell commands.

    Parameters
    ----------
    workspace_path : str | None
        Absolute path to the workspace.  If ``None`` the middleware will
        try to infer it from the controller's runtime at call time.
    enabled : bool
        Master switch.
    """

    def __init__(
        self,
        workspace_path: str | None = None,
        *,
        enabled: bool = True,
    ) -> None:
        self._workspace_path = workspace_path
        self._enabled = enabled
        self._manager: RollbackManager | None = None

    def _get_manager(self, ctx: ToolInvocationContext) -> RollbackManager | None:
        if self._manager is not None:
            return self._manager

        workspace = self._workspace_path
        if workspace is None:
            try:
                runtime = ctx.controller.runtime
                workspace = str(
                    getattr(runtime, 'workspace_dir', None)
                    or getattr(runtime, 'workspace_path', None)
                    or ''
                )
            except Exception:
                pass

        if not workspace or not os.path.isdir(workspace):
            self._enabled = False
            return None

        try:
            from backend.core.rollback.rollback_manager import RollbackManager

            self._manager = RollbackManager(
                workspace_path=workspace,
                max_checkpoints=30,
                auto_cleanup=True,
            )
        except Exception:
            logger.warning(
                'DestructiveCommandMiddleware: failed to create RollbackManager',
                exc_info=True,
            )
            self._enabled = False

        return self._manager

    async def execute(self, ctx: ToolInvocationContext) -> None:
        if not self._enabled:
            return

        action = ctx.action
        if type(action).__name__ != 'CmdRunAction':
            return
        command = getattr(action, 'command', '') or ''
        label = _scan_command(command)
        if not label:
            return

        # Capture for downstream observability regardless of checkpoint outcome.
        ctx.metadata['destructive_command'] = label
        snippet = command.strip().splitlines()[0][:160] if command else ''
        logger.warning(
            'DESTRUCTIVE COMMAND DETECTED [%s]: %s',
            label,
            snippet,
        )

        manager = self._get_manager(ctx)
        if manager is None:
            return

        try:
            checkpoint_id = manager.create_checkpoint(
                description=f'before destructive: {label}',
                checkpoint_type='before_destructive',
                metadata={
                    'pattern_label': label,
                    'command_snippet': snippet,
                    'session_id': getattr(ctx.state, 'sid', 'unknown'),
                },
                use_git=False,
            )
            # Override any previous checkpoint id from RollbackMiddleware so the
            # destructive checkpoint is what the audit logger / UI surfaces.
            ctx.metadata['rollback_checkpoint_id'] = checkpoint_id
            ctx.metadata['rollback_available'] = True
            ctx.metadata['destructive_checkpoint_id'] = checkpoint_id
            logger.info(
                'Destructive checkpoint %s created before %s', checkpoint_id, label
            )
        except Exception:
            logger.warning(
                'DestructiveCommandMiddleware: checkpoint creation failed',
                exc_info=True,
            )
