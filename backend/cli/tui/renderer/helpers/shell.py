"""Pure shell/cmd event helpers (no orchestrator dependency)."""

from __future__ import annotations

from backend.cli.display.transcript import strip_tool_result_validation_annotations
from backend.cli.tui.helpers import _sanitize_terminal_display_text
from backend.ledger.observation import CmdOutputObservation


def resolve_cmd_output_cwd(event: CmdOutputObservation) -> str | None:
    if hasattr(event, 'metadata') and event.metadata:
        return getattr(event.metadata, 'working_dir', None)
    return None


def sanitize_cmd_output(output: str) -> str:
    if not output:
        return ''
    return _sanitize_terminal_display_text(
        strip_tool_result_validation_annotations(output)
    ).strip()
