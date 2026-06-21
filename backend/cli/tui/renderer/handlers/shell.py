"""Shell / CmdRun event handlers for the TUI renderer.

Mounts :class:`ShellCard` scan-line rows with ⤢ detail screens.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.cli.tui.renderer.helpers.shell import (
    resolve_cmd_output_cwd,
    sanitize_cmd_output,
)
from backend.ledger.action import CmdRunAction
from backend.ledger.observation import CmdOutputObservation

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
    )


def _handle_cmd_run_action(
    orch: 'RendererEventProcessorMixin', event: CmdRunAction
) -> None:
    cmd = getattr(event, 'command', '') or ''
    if not getattr(event, 'hidden', False):
        orch._create_shell_scan_card(cmd)


def _handle_cmd_output_observation(
    orch: 'RendererEventProcessorMixin', event: CmdOutputObservation
) -> None:
    output = (event.content or '').strip()
    exit_code = getattr(event, 'exit_code', None)
    cmd = getattr(event, 'command', '') or ''
    cwd = resolve_cmd_output_cwd(event)
    output = sanitize_cmd_output(output)
    if output or exit_code is not None:
        orch._complete_shell_scan_card(
            cmd,
            output=output,
            exit_code=exit_code,
            cwd=cwd,
        )
