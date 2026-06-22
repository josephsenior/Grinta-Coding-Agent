"""Pure shell/cmd event helpers (no orchestrator dependency)."""

from __future__ import annotations

from backend.cli.display.transcript import strip_tool_result_validation_annotations
from backend.cli.tui.helpers import _strip_terminal_control_literals
from backend.ledger.observation import CmdOutputObservation


def resolve_cmd_output_cwd(event: CmdOutputObservation) -> str | None:
    if hasattr(event, 'metadata') and event.metadata:
        return getattr(event.metadata, 'working_dir', None)
    return None


def cmd_output_is_background_detached(event: CmdOutputObservation) -> bool:
    """True when the runtime detached the command to a background session."""
    metadata = getattr(event, 'metadata', None)
    if metadata is not None:
        if getattr(metadata, 'timeout_kind', None) == 'idle_detach':
            return bool(getattr(metadata, 'command_still_running', True))
        meta_exit = getattr(metadata, 'exit_code', None)
        if meta_exit == -2:
            return getattr(metadata, 'command_still_running', None) is not False
    return getattr(event, 'exit_code', None) == -2


def sanitize_cmd_output(output: str) -> str:
    if not output:
        return ''
    text = strip_tool_result_validation_annotations(output)
    return _strip_terminal_control_literals(text).strip()
