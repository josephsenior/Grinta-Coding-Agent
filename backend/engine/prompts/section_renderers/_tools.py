"""Renderer for the tool reference partial (system_partial_02_tools.md)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.engine.prompts.section_renderers._env_hints import (
    _explore_hint,
    _path_uncertainty_hint,
)

_QUALITY_BLOCK = (
    '**Quality:** Minimal diff unless asked. Match existing style; handle errors explicitly. '
    'Keep imports at top; avoid circular dependencies.'
)


def _render_tool_reference(
    render_partial: Callable[..., str],
    config: Any = None,
    *,
    is_windows: bool,
    windows_with_bash: bool,
    shell_is_powershell: bool,
) -> str:
    from backend.core.interaction_modes import (
        is_chat_mode,
        is_plan_mode,
        normalize_interaction_mode,
    )

    mode = normalize_interaction_mode(getattr(config, 'mode', 'agent'))
    can_edit = not (is_chat_mode(mode) or is_plan_mode(mode))

    explore = _explore_hint(config)
    confirm_cmd = (
        _path_uncertainty_hint(
            explore,
            is_windows=is_windows,
            windows_with_bash=windows_with_bash,
            shell_is_powershell=shell_is_powershell,
        )
        + ' Prefer editors over shell directory guessing.'
    )
    if not is_windows or windows_with_bash:
        proc_find = 'Never `pkill -f` broadly — `ps`/`grep` then `kill <PID>`.'
    else:
        proc_find = (
            "Find: `Get-Process | Where-Object { $_.ProcessName -like '*name*' }`; "
            'kill: `Stop-Process -Id <PID>`.'
        )

    checkpoints_on = bool(getattr(config, 'enable_checkpoints', True))
    checkpoint_hint = ''
    if checkpoints_on:
        checkpoint_hint = (
            '\n**Checkpoints:** auto snapshots before risky edits; '
            '`save` / `view` / `revert` / `clear` — see System Capabilities.\n'
        )

    if not can_edit:
        editor_ops = (
            '<EDITOR_AND_FILE_OPERATIONS>\n'
            f'Editor `path` values normalize safely. {confirm_cmd}\n'
            '**File API mental model**\n'
            '- Discovery: follow `<DISCOVERY_ROUTING>`.\n'
            '- Context: `read_file(path=...)`; add `start_line`/`end_line` on large files '
            '(see `<DISCOVERY_ROUTING>`).\n'
            f'{checkpoint_hint}'
            f'{_QUALITY_BLOCK}\n'
            '</EDITOR_AND_FILE_OPERATIONS>'
        )
    else:
        editor_ops = (
            '<EDITOR_AND_FILE_OPERATIONS>\n'
            f'Editor `path` values normalize safely. {confirm_cmd}\n'
            'Edit the user path directly; no shadow copies; remove temp files when done.\n\n'
            '**File API mental model**\n'
            '- Discovery: follow `<DISCOVERY_ROUTING>`.\n'
            '- Context: `read_file(path=...)`; add `start_line`/`end_line` on large files '
            '(see `<DISCOVERY_ROUTING>`).\n'
            '- Creation: `create_file` for new files. Fails if the file already exists; use `replace_string` or `multiedit` to modify an existing file.\n'
            '- Editing: `replace_string` (one exact text replacement per call); add by anchor -> anchor + content, delete with `new_string=""`.\n'
            '- Prefer surgical targeted edits for existing files; full-file overwrites only when genuinely necessary.\n'
            '- Batched or cross-file refactors: `multiedit` (multiple replace_string operations across one or more files).\n'
            '- File API rule: one change on one file -> `replace_string`; anything batched -> `multiedit`.\n'
            '- Undo: `undo_last_edit` reverts the last content edit on an existing file. '
            'It cannot undo file creation — delete the file explicitly instead.\n'
            '- Never write source via shell. Use real newlines/quotes, not serialized JSON strings.\n\n'
            '**Examples**\n'
            '- Find candidates: `find_symbols(query="authenticate")`.\n'
            '- Read a line range: `read_file(path="src/auth.py", start_line=40, end_line=80)`.\n'
            '- APPEND to a config file: use `replace_string` with a unique anchor line.\n'
            '- DELETE: `replace_string(old_string="old config block", new_string="")`.\n'
            '- Multiple edits on one file or across files: `multiedit`.\n'
            f'{checkpoint_hint}'
            f'{_QUALITY_BLOCK}\n'
            '</EDITOR_AND_FILE_OPERATIONS>'
        )

    return render_partial(
        'system_partial_02_tools.md',
        confirm_paths=confirm_cmd,
        process_management=proc_find,
        checkpoint_rollback_hint='',
        editor_and_file_operations=editor_ops,
    )
