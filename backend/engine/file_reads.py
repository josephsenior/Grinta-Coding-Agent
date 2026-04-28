import shlex
from collections import deque

from backend.engine.tools.prompt import uses_powershell_terminal
from backend.ledger.action import Action
from backend.ledger.action.commands import CmdRunAction
from backend.ledger.action.files import FileReadAction


def _escape_ps_path(path: str) -> str:
    """Escape a file path for safe use in a PowerShell double-quoted string."""
    # Backtick-escape characters special to PowerShell double-quoted strings.
    return path.replace('`', '``').replace('"', '`"').replace('$', '`$')


def _build_full_file_read_command(path: str, use_powershell: bool) -> str:
    """Build command to read entire file for the active shell contract."""
    if use_powershell:
        safe = _escape_ps_path(path)
        return (
            f'Write-Output "=== FILE: {safe} ===" ; Get-Content "{safe}" -Encoding UTF8'
        )
    safe = shlex.quote(path)
    return f'echo {shlex.quote("=== FILE: " + path + " ===")} && cat {safe}'


def _build_partial_file_read_command(
    path: str, start: int, end: int, use_powershell: bool
) -> str:
    """Build command to read file lines [start, end) for the active shell contract."""
    header = f'lines {start + 1}-{end}' if end != -1 else f'lines {start + 1}+'
    if use_powershell:
        safe = _escape_ps_path(path)
        win_header = f'Write-Output "=== FILE: {safe} ({header}) ===" ; '
        if end == -1:
            return (
                win_header
                + f'Get-Content "{safe}" -Encoding UTF8 | Select-Object -Skip {start}'
            )
        count = end - start
        return (
            win_header
            + f'Get-Content "{safe}" -Encoding UTF8 | Select-Object -Skip {start} -First {count}'
        )

    safe = shlex.quote(path)
    unix_header = f'echo {shlex.quote("=== FILE: " + path + " (" + header + ") ===")} && '
    if end == -1:
        return unix_header + f'tail -n +{start + 1} {safe}'
    return unix_header + f'sed -n "{start + 1},{end}p" {safe}'


def _build_file_read_command(fr: FileReadAction, use_powershell: bool) -> str:
    """Build a shell command for one file read using the active shell contract."""
    path = fr.path
    start, end = fr.start, fr.end
    if fr.view_range:
        start = fr.view_range[0] - 1 if len(fr.view_range) > 0 else 0
        end = fr.view_range[1] if len(fr.view_range) > 1 else -1

    if start == 0 and end == -1 and not fr.view_range:
        return _build_full_file_read_command(path, use_powershell)
    return _build_partial_file_read_command(path, start, end, use_powershell)


def _collect_file_read_batch(pending_actions: deque[Action]) -> list[FileReadAction]:
    """Collect leading run of FileReadAction from pending_actions."""
    batch: list[FileReadAction] = []
    for action in pending_actions:
        if isinstance(action, FileReadAction):
            batch.append(action)
        else:
            break
    return batch


def try_batch_file_reads(pending_actions: deque[Action]) -> Action | None:
    """Batch consecutive read-only actions into a single CmdRunAction.

    When the LLM emits multiple file reads or search actions in one
    response, executing them one-per-step is wasteful.  This collapses
    them into a single command that processes all requested operations,
    cutting round-trips.
    """
    batch = _collect_file_read_batch(pending_actions)
    if len(batch) < 2:
        return None

    for _ in batch:
        pending_actions.popleft()

    use_powershell = uses_powershell_terminal()
    parts = [_build_file_read_command(fr, use_powershell) for fr in batch]
    sep = ' ; ' if use_powershell else ' && '
    return CmdRunAction(command=sep.join(parts), thought='Batched parallel file reads')
