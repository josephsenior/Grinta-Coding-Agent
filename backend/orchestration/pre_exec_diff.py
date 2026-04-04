"""Pre-execution diff preview middleware.

Generates a unified diff showing what a FileEditAction or FileWriteAction
*will* change **before** it runs, and attaches it to the tool-invocation
context so that audit logs and the debug endpoint can surface it.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from backend.core.logger import app_logger as logger

if TYPE_CHECKING:
    from backend.orchestration.tool_pipeline import ToolInvocationContext

from backend.orchestration.tool_pipeline import ToolInvocationMiddleware


class PreExecDiffMiddleware(ToolInvocationMiddleware):
    """Pipeline middleware that computes a diff *before* the action executes.

    The diff is stored in ``ctx.metadata["pre_exec_diff"]`` so that
    downstream consumers (audit logger, debug endpoint, UI) can inspect
    the planned change without re-computing it.

    In the observe stage, the diff is appended to the observation content
    so the LLM can verify what actually changed.

    Only activates for ``FileEditAction`` and ``FileWriteAction``.
    """

    # -----------------------------------------------------------------
    # execute stage — runs before the action is dispatched to runtime
    # -----------------------------------------------------------------
    async def execute(self, ctx: ToolInvocationContext) -> None:
        action = ctx.action

        try:
            from backend.ledger.action import FileEditAction, FileWriteAction
        except ImportError:
            return

        if isinstance(action, FileEditAction):
            await self._diff_for_edit(ctx, action)
        elif isinstance(action, FileWriteAction):
            await self._diff_for_write(ctx, action)

    # -----------------------------------------------------------------
    # observe stage — append diff summary to observation content
    # -----------------------------------------------------------------
    async def observe(self, ctx: ToolInvocationContext, observation=None) -> None:
        diff = ctx.metadata.get('pre_exec_diff')
        if not diff or observation is None:
            return

        # Append a concise diff to the observation so the LLM sees what changed
        content = getattr(observation, 'content', None)
        if content is None or not isinstance(content, str):
            return

        # Limit diff size to avoid bloating context
        diff_preview = (
            diff if len(diff) <= 2000 else diff[:2000] + '\n... (diff truncated)'
        )
        observation.content = (
            content + '\n\n<DIFF_PREVIEW>\n' + diff_preview + '\n</DIFF_PREVIEW>'
        )

    # -----------------------------------------------------------------
    # internals
    # -----------------------------------------------------------------
    async def _diff_for_edit(self, ctx: ToolInvocationContext, action) -> None:
        """Compute the diff that a FileEditAction will produce."""
        try:
            path = self._resolve_path(action.path, ctx)
            if path is None or not os.path.isfile(path):
                return

            old_content = self._read_file(path)
            if old_content is None:
                return

            # Simulate the edit
            new_content = self._simulate_edit(old_content, action)
            if new_content is None or old_content == new_content:
                return

            from backend.execution.utils.diff import get_diff

            diff = get_diff(old_content, new_content, path=action.path)
            if diff:
                ctx.metadata['pre_exec_diff'] = diff
                logger.debug(
                    'Pre-exec diff generated for %s (%d chars)',
                    action.path,
                    len(diff),
                )
        except Exception:
            logger.debug('Pre-exec diff skipped for FileEditAction', exc_info=True)

    def _simulate_edit(self, old_content: str, action) -> str | None:
        """Simulate the edit on old content based on action command."""
        if action.command == 'replace_text' and action.old_str:
            return old_content.replace(action.old_str, action.new_str or '', 1)
        if action.command == 'create_file':
            return action.file_text or ''
        if action.command == 'insert_text' and action.insert_line is not None:
            lines = old_content.splitlines(keepends=True)
            insert_idx = max(0, min(action.insert_line, len(lines)))
            lines.insert(insert_idx, (action.new_str or '') + '\n')
            return ''.join(lines)
        return None  # view or unknown — nothing to diff

    async def _diff_for_write(self, ctx: ToolInvocationContext, action) -> None:
        """Compute the diff that a FileWriteAction will produce."""
        try:
            path = self._resolve_path(action.path, ctx)
            old_content = ''
            if path and os.path.isfile(path):
                old_content = self._read_file(path) or ''

            new_content = action.content if hasattr(action, 'content') else ''
            if old_content == new_content:
                return

            from backend.execution.utils.diff import get_diff

            diff = get_diff(old_content, new_content, path=action.path)
            if diff:
                ctx.metadata['pre_exec_diff'] = diff
                logger.debug(
                    'Pre-exec diff generated for %s (%d chars)',
                    action.path,
                    len(diff),
                )
        except Exception:
            logger.debug('Pre-exec diff skipped for FileWriteAction', exc_info=True)

    @staticmethod
    def _resolve_path(rel_path: str, ctx: ToolInvocationContext) -> str | None:
        """Best-effort resolution of the file path to an absolute path."""
        if os.path.isabs(rel_path):
            return rel_path
        # Try extracting workspace root from the controller's runtime
        try:
            runtime = ctx.controller.runtime
            workspace = getattr(runtime, 'workspace_dir', None) or getattr(
                runtime, 'workspace_path', None
            )
            if workspace:
                return os.path.join(str(workspace), rel_path)
        except Exception:
            pass
        return None

    @staticmethod
    def _read_file(path: str, max_bytes: int = 2 * 1024 * 1024) -> str | None:
        """Read a file, returning None on failure or if too large."""
        try:
            if os.path.getsize(path) > max_bytes:
                return None
            with open(path, encoding='utf-8', errors='replace') as fh:
                return fh.read()
        except Exception:
            return None
