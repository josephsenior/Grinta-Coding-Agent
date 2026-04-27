"""Rollback middleware — creates automatic checkpoints before risky actions.

Integrates the existing (but previously orphaned) ``RollbackManager`` into the
tool-invocation pipeline so that ``FileEditAction``, ``FileWriteAction``, and
``CmdRunAction`` automatically get a filesystem checkpoint right before they
execute.

The checkpoint ID is stored in ``ctx.metadata["rollback_checkpoint_id"]`` for
downstream consumers (audit logger, debug endpoint, undo UI).
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

# Action types that warrant a pre-execution checkpoint.
_RISKY_ACTION_TYPES = frozenset(
    {
        'FileEditAction',
        'FileWriteAction',
        'CmdRunAction',
    }
)

# Read-only / inspection commands that never mutate state.  Skipping a
# checkpoint for these keeps the rollback history meaningful (only real
# mutations show up) and avoids wasteful disk snapshots.
# Pattern is matched against the leading token of the command body.
_TRIVIAL_CMD_PATTERN = re.compile(
    r'^\s*(?:'
    # POSIX read-only utilities
    r'ls|pwd|cat|echo|which|whereis|whoami|id|date|uptime|hostname|uname|env|printenv|'
    r'grep|egrep|fgrep|rg|ag|find|locate|head|tail|wc|sort|uniq|cut|column|awk|sed|'
    r'file|stat|du|df|ps|top|htop|free|lsof|netstat|ss|ip|ifconfig|history|alias|type|'
    # Git read-only
    r'git\s+(?:status|log|show|diff|branch(?!\s+-D)|remote(?:\s+-v)?|config\s+--get|'
        r'rev-parse|describe|stash\s+list|tag(?:\s+-l)?|ls-files|ls-tree|blame)|'
    # Python / Node read-only invocations
    r'python(?:3)?\s+--version|node\s+--version|npm\s+(?:list|ls|view|info|outdated)|'
    r'pip\s+(?:list|show|freeze)|'
    # PowerShell read-only verbs
    r'Get-[A-Z][A-Za-z]+|Test-[A-Z][A-Za-z]+|Where-Object|Select-Object|Measure-Object'
    r')\b'
)


def _is_trivial_command(command: str) -> bool:
    """Return True for read-only commands whose pre-execution checkpoint adds no value."""
    if not command:
        return False
    head = command.strip()
    # Strip leading env-var assignments such as ``DEBUG=1 ls``.
    while True:
        m = re.match(r'^[A-Za-z_][A-Za-z0-9_]*=\S*\s+', head)
        if not m:
            break
        head = head[m.end():]
    return bool(_TRIVIAL_CMD_PATTERN.match(head))


class RollbackMiddleware(ToolInvocationMiddleware):
    """Creates a ``RollbackManager`` checkpoint at the execute stage.

    Only fires for action types listed in ``_RISKY_ACTION_TYPES``.

    Parameters
    ----------
    workspace_path : str | None
        Absolute path to the workspace.  If ``None`` the middleware will
        try to infer it from the controller's runtime at call time.
    enabled : bool
        Master switch — set ``False`` to disable checkpointing without
        removing the middleware from the pipeline.
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

    # ------------------------------------------------------------------
    # Lazy initialisation (deferred until first use so the workspace
    # path can be resolved at runtime)
    # ------------------------------------------------------------------
    def _get_manager(self, ctx: ToolInvocationContext) -> RollbackManager | None:
        """Return (and lazily create) the RollbackManager."""
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
            logger.debug('RollbackMiddleware: cannot resolve workspace path — disabled')
            self._enabled = False
            return None

        try:
            from backend.core.rollback.rollback_manager import RollbackManager

            self._manager = RollbackManager(
                workspace_path=workspace,
                max_checkpoints=30,
                auto_cleanup=True,
            )
            logger.info(
                'RollbackMiddleware: RollbackManager initialised at %s', workspace
            )
        except Exception:
            logger.warning(
                'RollbackMiddleware: failed to create RollbackManager', exc_info=True
            )
            self._enabled = False

        return self._manager

    # ------------------------------------------------------------------
    # execute stage — runs BEFORE the action is actually dispatched
    # ------------------------------------------------------------------
    async def execute(self, ctx: ToolInvocationContext) -> None:
        if not self._enabled:
            return

        action_type = type(ctx.action).__name__
        risky = action_type in _RISKY_ACTION_TYPES
        # Also treat any action explicitly marked HIGH security risk as risky
        # so future tool types are covered automatically (C-P0-2).
        if not risky:
            try:
                from backend.core.enums import ActionSecurityRisk

                if getattr(ctx.action, 'security_risk', None) == ActionSecurityRisk.HIGH:
                    risky = True
            except Exception:
                pass
        if not risky:
            return

        # Skip trivial read-only CmdRunActions to keep checkpoint history clean.
        if action_type == 'CmdRunAction':
            cmd_attr = getattr(ctx.action, 'command', '') or ''
            cmd = cmd_attr if isinstance(cmd_attr, str) else ''
            if cmd and _is_trivial_command(cmd):
                logger.debug('Skipping checkpoint for trivial command: %s', cmd[:80])
                return

        manager = self._get_manager(ctx)
        if manager is None:
            return

        try:
            description = f'auto: before {action_type}'
            metadata = {
                'action_type': action_type,
                'session_id': getattr(ctx.state, 'sid', 'unknown'),
            }
            # Prefer lightweight file-based snapshots (skip git commit noise)
            checkpoint_id = manager.create_checkpoint(
                description=description,
                checkpoint_type='before_risky',
                metadata=metadata,
                use_git=False,
            )
            ctx.metadata['rollback_checkpoint_id'] = checkpoint_id
            ctx.metadata['rollback_available'] = True
            logger.debug('Checkpoint %s created before %s', checkpoint_id, action_type)
        except Exception:
            logger.debug(
                'Checkpoint creation failed — continuing without rollback',
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # observe stage — retroactively update audit entry with snapshot info
    # ------------------------------------------------------------------
    async def observe(self, ctx: ToolInvocationContext, observation=None) -> None:
        checkpoint_id = ctx.metadata.get('rollback_checkpoint_id')
        audit_id = ctx.metadata.get('audit_id')
        if not checkpoint_id or not audit_id:
            return

        try:
            validator = getattr(ctx.controller, 'safety_validator', None)
            audit_logger = (
                getattr(validator, 'telemetry_logger', None) if validator else None
            )
            if audit_logger is None:
                return
            session_id = getattr(ctx.controller, 'id', 'unknown')
            await audit_logger.update_entry_snapshot(
                session_id=session_id,
                audit_id=audit_id,
                filesystem_snapshot_id=checkpoint_id,
                rollback_available=True,
            )
            logger.debug(
                'Audit entry %s updated with checkpoint %s', audit_id, checkpoint_id
            )
        except Exception:
            logger.debug('Failed to update audit entry with snapshot', exc_info=True)

    # ------------------------------------------------------------------
    # Public helpers for programmatic rollback
    # ------------------------------------------------------------------
    def rollback_to(self, checkpoint_id: str) -> bool:
        """Rollback to a previously created checkpoint (delegates to manager)."""
        if self._manager is None:
            return False
        return self._manager.rollback_to(checkpoint_id)

    def list_checkpoints(self) -> list[dict]:
        """Return available checkpoints."""
        if self._manager is None:
            return []
        return self._manager.list_checkpoints()
