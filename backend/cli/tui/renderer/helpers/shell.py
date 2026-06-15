"""Pure shell/cmd event helpers (no orchestrator dependency)."""

from __future__ import annotations

from backend.cli.display.transcript import strip_tool_result_validation_annotations
from backend.cli.tui.helpers import _strip_terminal_control_literals
from backend.ledger.observation import CmdOutputObservation


def resolve_cmd_output_cwd(event: CmdOutputObservation) -> str | None:
    if hasattr(event, 'metadata') and event.metadata:
        return getattr(event.metadata, 'working_dir', None)
    return None


def sanitize_cmd_output(output: str) -> str:
    if not output:
        return ''
    text = strip_tool_result_validation_annotations(output)
    return _strip_terminal_control_literals(text).strip()
