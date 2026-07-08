"""Prompt for conservative autonomy when opening an unfamiliar workspace."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from backend.core.autonomy import AutonomyLevel, normalize_autonomy_level
from backend.core.workspace_trust import (
    is_familiar_workspace,
    record_workspace_visit,
)

logger = logging.getLogger(__name__)

_UNFAMILIAR_BODY = (
    'This workspace has not been opened with Grinta before.\n\n'
    'For unfamiliar repositories, conservative autonomy confirms shell commands, '
    'file edits, MCP calls, and other risky actions before they run.\n\n'
    'Choose conservative now, or keep your current autonomy level.'
)


async def maybe_apply_unfamiliar_workspace_hardening(
    controller: Any,
    workspace: Path | None,
    *,
    agent_name: str,
    host: Any | None = None,
    console: Any | None = None,
) -> str:
    """Offer conservative autonomy on first visit to *workspace*.

    Returns the effective autonomy level after any change.
    """
    from backend.cli.settings import get_persisted_autonomy_level, update_autonomy_level
    from backend.cli.settings.mode_runtime import apply_autonomy_to_controller

    if workspace is None:
        return normalize_autonomy_level(get_persisted_autonomy_level(agent_name))

    resolved = workspace.expanduser().resolve()
    current = normalize_autonomy_level(get_persisted_autonomy_level(agent_name))

    if is_familiar_workspace(resolved):
        return current

    prompted = False
    chosen = current
    if current != AutonomyLevel.CONSERVATIVE.value:
        prompted = True
        choice = await _prompt_for_conservative(host=host, console=console)
        if choice == 'conservative':
            chosen = AutonomyLevel.CONSERVATIVE.value
            update_autonomy_level(chosen, agent_name)
            ac = getattr(controller, 'autonomy_controller', None)
            if ac is not None:
                ac.autonomy_level = chosen
            apply_autonomy_to_controller(controller)
            _notify_autonomy_change(host, console, chosen)

    record_workspace_visit(
        resolved,
        autonomy_level=chosen,
        prompted=prompted,
    )
    return chosen


async def _prompt_for_conservative(
    *,
    host: Any | None,
    console: Any | None,
) -> str:
    if host is not None and hasattr(host, 'push_screen_wait'):
        from backend.cli.tui.dialogs import GrintaConfirmDialog

        result = await host.push_screen_wait(
            GrintaConfirmDialog(
                title='Unfamiliar workspace',
                body=_UNFAMILIAR_BODY,
                options=[
                    ('conservative', 'Use conservative'),
                    ('keep', 'Keep current level'),
                ],
                recommended=0,
            )
        )
        if result == 'conservative':
            return 'conservative'
        return 'keep'

    if console is not None:
        try:
            from rich.prompt import Prompt

            answer = Prompt.ask(
                'Unfamiliar workspace — switch to conservative autonomy?',
                choices=['y', 'n'],
                default='y',
                console=console,
            )
            if answer.lower() == 'y':
                return 'conservative'
        except Exception:
            logger.debug('Rich prompt failed for workspace trust', exc_info=True)
    return 'keep'


def _notify_autonomy_change(host: Any | None, console: Any | None, level: str) -> None:
    from backend.core.autonomy import autonomy_runtime_notice

    notice = autonomy_runtime_notice(level)
    renderer = getattr(host, '_renderer', None) if host is not None else None
    add_message = getattr(renderer, 'add_system_message', None)
    if callable(add_message):
        add_message(notice, title='workspace')
        return
    if console is not None:
        console.print(f'[workspace] {notice}')


__all__ = ['maybe_apply_unfamiliar_workspace_hardening']
