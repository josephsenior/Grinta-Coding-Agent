"""Pure terminal event helpers (no orchestrator dependency)."""

from __future__ import annotations

from backend.cli.display.transcript import strip_tool_result_validation_annotations
from backend.cli.tui.helpers import _sanitize_terminal_display_text


def sanitize_terminal_observation_content(content: str) -> str:
    if not content:
        return ''
    return _sanitize_terminal_display_text(
        strip_tool_result_validation_annotations(content)
    ).strip()


def terminal_secondary_kind(exit_code: int | None) -> str:
    if exit_code == 0:
        return 'ok'
    if exit_code is not None:
        return 'err'
    return 'neutral'
