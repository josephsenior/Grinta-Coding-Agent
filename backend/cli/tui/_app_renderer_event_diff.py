"""File-diff extraction helpers for :class:`_AppRendererEventProcessorMixin`.

These helpers decide what text to render in the ``Edited`` card when a
file-edit/file-write observation arrives. The four entry points correspond
to the four kinds of diff payloads that may be available, falling back to a
``git diff`` shell-out when no inline diff is provided.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.cli.tui._app_helpers import (
    _encode_split_diff_contents,
    _extract_tagged_block,
)
from backend.core.workspace_resolution import resolve_cli_workspace_directory

if TYPE_CHECKING:
    from backend.cli.tui._app_renderer_event_processor_mixin import (
        _AppRendererEventProcessorMixin,
    )


def _should_replace_task_list_from_event(
    orch: '_AppRendererEventProcessorMixin',
    event: Any,
) -> bool:
    """Ignore empty task payloads unless they clearly mean to clear the plan."""
    command = str(getattr(event, 'command', '') or '').strip().lower()
    task_list = list(getattr(event, 'task_list', []) or [])
    if task_list:
        return True
    if command == 'view':
        return False
    if command == 'clear':
        return True

    content = str(getattr(event, 'content', '') or '').strip().lower()
    thought = str(getattr(event, 'thought', '') or '').strip().lower()
    explicit_clear_markers = (
        'clearing the task list',
        'plan updated with 0 tasks',
        'cleared task list',
        'cleared the task list',
    )
    if any(marker in content for marker in explicit_clear_markers):
        return True
    if any(marker in thought for marker in explicit_clear_markers):
        return True
    return not orch._task_list


def _extract_file_observation_diff(
    orch: '_AppRendererEventProcessorMixin',
    event: Any,
) -> str | None:
    """Extract unified diff text from any file edit/write observation."""
    return _extract_file_edit_diff(orch, event)


def _extract_file_edit_group_rows(
    orch: '_AppRendererEventProcessorMixin',
    event: Any,
) -> str | None:
    """Extract two-pane diff rows from before/after edit groups."""
    del orch  # state is read directly from ``event``
    old_content = getattr(event, 'old_content', None)
    new_content = getattr(event, 'new_content', None)
    if old_content is None or new_content is None:
        return None
    return _encode_split_diff_contents(old_content, new_content)


def _extract_file_edit_diff(
    orch: '_AppRendererEventProcessorMixin',
    event: Any,
) -> str | None:
    """Extract unified diff from a FileEditObservation for TUI display."""
    explicit_diff = getattr(event, 'diff', None)
    if isinstance(explicit_diff, str) and explicit_diff.strip():
        return explicit_diff

    content = getattr(event, 'content', None)
    if isinstance(content, str) and content:
        marker = '[EDIT_DIFF]'
        marker_index = content.find(marker)
        if marker_index != -1:
            embedded = content[marker_index + len(marker) :].strip()
            if embedded:
                return embedded

        preview = _extract_tagged_block(
            content,
            '<DIFF_PREVIEW>',
            '</DIFF_PREVIEW>',
        )
        if preview:
            return preview

    try:
        from backend.execution.utils.diff import get_diff

        old_content = getattr(event, 'old_content', None)
        new_content = getattr(event, 'new_content', None)
        if old_content is None or new_content is None:
            return _extract_git_file_diff(orch, getattr(event, 'path', ''))

        diff = get_diff(old_content, new_content, path=event.path)
        if diff:
            return diff
        return None
    except Exception:
        pass
    return _extract_git_file_diff(orch, getattr(event, 'path', ''))


def _extract_git_file_diff(
    orch: '_AppRendererEventProcessorMixin',
    path: str,
) -> str | None:
    """Best-effort fallback when observations omit inline diff payloads."""
    clean_path = (path or '').strip()
    if not clean_path or clean_path == '.':
        return None
    try:
        workspace = resolve_cli_workspace_directory(
            getattr(orch._tui, '_config', None)
        )
        if workspace is None:
            return None

        path_obj = Path(clean_path)
        if path_obj.is_absolute():
            try:
                clean_path = str(
                    path_obj.resolve().relative_to(workspace.resolve())
                )
            except (OSError, ValueError):
                return None

        for args in (
            ['git', '-C', str(workspace), '--no-pager', 'diff', '--', clean_path],
            [
                'git',
                '-C',
                str(workspace),
                '--no-pager',
                'diff',
                '--cached',
                '--',
                clean_path,
            ],
        ):
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout
    except Exception:
        return None
    return None
