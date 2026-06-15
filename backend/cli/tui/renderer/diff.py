"""File-diff extraction helpers for :class:`RendererEventProcessorMixin`.

These helpers decide what text to render in the ``Edited`` card when a
file-edit/file-write observation arrives. The four entry points correspond
to the four kinds of diff payloads that may be available, falling back to a
``git diff`` shell-out when no inline diff is provided.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.cli.tui.helpers import (
    _encode_split_diff_contents,
    _extract_tagged_block,
)
from backend.core.workspace_resolution import resolve_cli_workspace_directory

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
    )


_EXPLICIT_CLEAR_MARKERS = (
    'clearing the task list',
    'plan updated with 0 tasks',
    'cleared task list',
    'cleared the task list',
)


def _text_contains_clear_marker(text: str) -> bool:
    return any(marker in text for marker in _EXPLICIT_CLEAR_MARKERS)


def _should_replace_task_list_from_event(
    orch: 'RendererEventProcessorMixin',
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
    if _text_contains_clear_marker(content):
        return True
    if _text_contains_clear_marker(thought):
        return True
    return not orch._task_list


def _extract_file_observation_diff(
    orch: 'RendererEventProcessorMixin',
    event: Any,
) -> str | None:
    """Extract unified diff text from any file edit/write observation."""
    return _extract_file_edit_diff(orch, event)


def _extract_file_edit_group_rows(
    orch: 'RendererEventProcessorMixin',
    event: Any,
) -> str | None:
    """Extract two-pane diff rows from before/after edit groups."""
    del orch  # state is read directly from ``event``
    old_content = getattr(event, 'old_content', None)
    new_content = getattr(event, 'new_content', None)
    if old_content is None or new_content is None:
        return None
    return _encode_split_diff_contents(
        old_content,
        new_content,
        path=str(getattr(event, 'path', '') or ''),
    )


def _extract_embedded_diff_from_content(content: str) -> str | None:
    if not isinstance(content, str) or not content:
        return None
    marker = '[EDIT_DIFF]'
    marker_index = content.find(marker)
    if marker_index != -1:
        embedded = content[marker_index + len(marker) :].strip()
        if embedded:
            return embedded
    preview = _extract_tagged_block(content, '<DIFF_PREVIEW>', '</DIFF_PREVIEW>')
    if preview:
        return preview
    return None


def _try_compute_diff_from_old_new(event: Any) -> str | None:
    from backend.execution.utils.diff import get_diff

    old_content = getattr(event, 'old_content', None)
    new_content = getattr(event, 'new_content', None)
    if old_content is None or new_content is None:
        return None
    diff = get_diff(old_content, new_content, path=event.path)
    return diff if diff else None


def _extract_file_edit_diff(
    orch: 'RendererEventProcessorMixin',
    event: Any,
) -> str | None:
    """Extract unified diff from a FileEditObservation for TUI display."""
    explicit_diff = getattr(event, 'diff', None)
    if isinstance(explicit_diff, str) and explicit_diff.strip():
        return explicit_diff

    embedded = _extract_embedded_diff_from_content(getattr(event, 'content', None))
    if embedded:
        return embedded

    try:
        computed = _try_compute_diff_from_old_new(event)
        if computed:
            return computed
        old_content = getattr(event, 'old_content', None)
        new_content = getattr(event, 'new_content', None)
        if old_content is not None and new_content is not None:
            return None
    except Exception:
        pass
    return _extract_git_file_diff(orch, getattr(event, 'path', ''))


def _resolve_git_diff_path(clean_path: str, workspace: Path) -> str | None:
    path_obj = Path(clean_path)
    if not path_obj.is_absolute():
        return clean_path
    try:
        return str(path_obj.resolve().relative_to(workspace.resolve()))
    except (OSError, ValueError):
        return None


def _try_git_diff_subprocess(workspace: Path, clean_path: str) -> str | None:
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
    return None


def _extract_git_file_diff(
    orch: 'RendererEventProcessorMixin',
    path: str,
) -> str | None:
    """Best-effort fallback when observations omit inline diff payloads."""
    clean_path = (path or '').strip()
    if not clean_path or clean_path == '.':
        return None
    try:
        workspace = resolve_cli_workspace_directory(getattr(orch._tui, '_config', None))
        if workspace is None:
            return None

        resolved = _resolve_git_diff_path(clean_path, workspace)
        if resolved is None:
            return None

        return _try_git_diff_subprocess(workspace, resolved)
    except Exception:
        return None
