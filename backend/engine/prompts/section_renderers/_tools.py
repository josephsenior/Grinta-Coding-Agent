"""Renderer for the tool reference partial (system_partial_02_tools.md)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.engine.prompts.section_renderers._env_hints import (
    _explore_hint,
    _path_uncertainty_hint,
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

    if not can_edit:
        editor_ops = (
            '<EDITOR_AND_FILE_OPERATIONS>\n'
            f'Editor `path` values normalize safely. {confirm_cmd}\n'
            '**File API mental model**\n'
            '- Context: `read` for file, range, or symbol bodies.\n'
            '- Discovery: `find_symbols` returns candidates.\n'
            '</EDITOR_AND_FILE_OPERATIONS>'
        )
    else:
        editor_ops = (
            '<EDITOR_AND_FILE_OPERATIONS>\n'
            f'Editor `path` values normalize safely. {confirm_cmd}\n'
            'Edit the user path directly; no shadow copies; remove temp files when done.\n\n'
            '**File API mental model**\n'
            '- Discovery: `find_symbols` returns candidates.\n'
            '- Context: `read` for file, range, or symbol bodies. `read(type="symbols")` returns each target as resolved, ambiguous, or not_found.\n'
            '- Creation: `create(type="file")` for new files; `create(type="symbol")` for new symbols anchored to existing code.\n'
            '- Code: `edit_symbols` for modifying/deleting existing symbols; prefer `path` + `qualified_name` + `symbol_kind` for write targets.\n'
            '- Text/config/docs: `replace_string`; add by anchor -> anchor + content, delete with `new_string=""`.\n'
            '- Refactor atomically across files: `multiedit`.\n'
            '- Undo: `undo_last_edit` reverts the last file-write on an existing file. File must still exist — for creation rollback, delete the file.\n'
            '- Never write source via shell. Use real newlines/quotes, not serialized JSON strings.\n\n'
            '**Examples**\n'
            '- Find candidates: `find_symbols(query="authenticate")`.\n'
            '- Read symbols: `read(type="symbols", symbols=[{"qualified_name": "authenticate_user"}, {"qualified_name": "UserService"}])`.\n'
            '- APPEND to a config file: use `replace_string` with a unique anchor line. Set old_string to the anchor, new_string to the inserted text followed by the same anchor, using real line breaks.\n'
            '- DELETE: `replace_string(old_string="old config block", new_string="")`.\n'
            '- Code/content payloads must represent normal source text. Do not include literal backslash-n sequences unless the target file actually requires them. Transport escaping is handled by the tool API; do not serialize code yourself.\n'
            '- Multiple functions: `edit_symbols`; implementation + tests: `multiedit`.\n'
            '</EDITOR_AND_FILE_OPERATIONS>'
        )

    return render_partial(
        'system_partial_02_tools.md',
        confirm_paths=confirm_cmd,
        process_management=proc_find,
        checkpoint_rollback_hint='',
        editor_and_file_operations=editor_ops,
    )
