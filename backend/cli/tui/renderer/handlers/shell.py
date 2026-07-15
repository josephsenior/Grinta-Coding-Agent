"""Shell / CmdRun event handlers for the TUI renderer.

Mounts :class:`ShellCard` scan-line rows with ⤢ detail screens.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.cli.tui.renderer.helpers.shell import (
    cmd_output_is_background_detached,
    normalize_shell_command_key,
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
    cmd = normalize_shell_command_key(getattr(event, 'command', '') or '')
    if not getattr(event, 'hidden', False):
        orch._create_shell_scan_card(
            cmd,
            command=getattr(event, 'command', '') or '',
            action_id=getattr(event, 'id', None),
        )


def _handle_cmd_output_observation(
    orch: 'RendererEventProcessorMixin', event: CmdOutputObservation
) -> None:
    raw_cmd = getattr(event, 'command', '') or ''
    cmd = normalize_shell_command_key(raw_cmd)
    if cmd.lower().startswith('browser '):
        return
    output = (event.content or '').strip()
    exit_code = getattr(event, 'exit_code', None)
    cwd = resolve_cmd_output_cwd(event)
    output = sanitize_cmd_output(output)
    is_background = cmd_output_is_background_detached(event)
    if output or exit_code is not None or is_background:
        orch._complete_shell_scan_card(
            cmd,
            command=raw_cmd,
            output=output,
            exit_code=exit_code,
            cwd=cwd,
            is_background=is_background,
            action_id=getattr(event, 'cause', None),
        )
