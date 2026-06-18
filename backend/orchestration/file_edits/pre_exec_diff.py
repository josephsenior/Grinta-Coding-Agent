"""Pre-execution diff preview middleware.

Generates a unified diff showing what a file mutation action *will* change
**before** it runs, and attaches it to the tool-invocation context so that
audit logs and the debug endpoint can surface it.
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

    Only activates for ``FileEditAction``.
    """

    # -----------------------------------------------------------------
    # execute stage — runs before the action is dispatched to runtime
    # -----------------------------------------------------------------
    async def execute(self, ctx: ToolInvocationContext) -> None:
        from backend.ledger.action import FileEditAction

        action = ctx.action
        if not isinstance(action, FileEditAction):
            return
        await self._diff_for_edit(ctx, action)

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

    def _simulate_create_file(self, action) -> str:
        return action.file_text or ''

    def _simulate_insert_text(self, old_content: str, action) -> str:
        lines = old_content.splitlines(keepends=True)
        new_text = action.new_str or ''
        line_ending = '\r\n' if '\r\n' in old_content else '\n'
        if old_content and new_text and not new_text.endswith(('\n', '\r')):
            new_text += line_ending
        insert_idx = max(0, min(action.insert_line - 1, len(lines)))
        new_lines = new_text.splitlines(keepends=True) or [new_text]
        return ''.join(lines[:insert_idx] + new_lines + lines[insert_idx:])

    def _normalize_line_endings(self, old_content: str, text: str) -> str:
        newline = '\r\n' if '\r\n' in old_content else '\n'
        normalized = text.replace('\r\n', '\n').replace('\r', '\n')
        if newline == '\r\n':
            normalized = normalized.replace('\n', '\r\n')
        return normalized

    def _simulate_replace_string(self, old_content: str, action) -> str | None:
        old_string = getattr(action, 'old_string', None)
        if not old_string:
            return None
        old_match = self._normalize_line_endings(old_content, old_string)
        new_replacement = self._normalize_line_endings(
            old_content, action.new_str or ''
        )
        replace_all = getattr(action, 'replace_all', False)
        replace_all = replace_all if isinstance(replace_all, bool) else False
        match_count = old_content.count(old_match)
        if match_count == 0 or (match_count > 1 and not replace_all):
            return None
        return old_content.replace(old_match, new_replacement, -1 if replace_all else 1)

    def _simulate_range_edit(self, old_content: str, action) -> str | None:
        start = getattr(action, 'start_line', None)
        end = getattr(action, 'end_line', None)
        if start is None or end is None:
            return None
        lines = old_content.splitlines(keepends=True)
        start_idx = max(0, start - 1)
        end_idx = min(len(lines), end)
        new_lines = (action.new_str or '').splitlines(keepends=True)
        return ''.join(lines[:start_idx] + new_lines + lines[end_idx:])

    def _simulate_edit(self, old_content: str, action) -> str | None:
        """Simulate the edit on old content based on action command."""
        if action.command == 'create_file':
            return self._simulate_create_file(action)
        if action.command == 'insert_text' and action.insert_line is not None:
            return self._simulate_insert_text(old_content, action)
        if action.command == 'replace_string':
            return self._simulate_replace_string(old_content, action)
        if action.command == 'edit' and getattr(action, 'edit_mode', None) == 'range':
            return self._simulate_range_edit(old_content, action)
        return None  # view or unknown — nothing to diff

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
