"""Plan-approval confirmation UI for high-risk actions."""

from __future__ import annotations

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text

from backend.core.enums import ActionSecurityRisk, AgentState
from backend.ledger.action import (
    Action,
    ChangeAgentStateAction,
    CmdRunAction,
    FileEditAction,
    FileWriteAction,
)


def _risk_label(action: Action) -> tuple[str, str]:
    """Return (risk_text, style) for a given action."""
    risk = getattr(action, 'security_risk', ActionSecurityRisk.UNKNOWN)
    try:
        if not isinstance(risk, ActionSecurityRisk):
            risk = ActionSecurityRisk(int(risk))
    except (ValueError, TypeError):
        risk = ActionSecurityRisk.UNKNOWN

    if risk == ActionSecurityRisk.HIGH:
        return ('HIGH', 'bold red')
    if risk == ActionSecurityRisk.MEDIUM:
        return ('MEDIUM', 'yellow')
    if risk == ActionSecurityRisk.LOW:
        return ('LOW', 'green')
    return ('ASK', 'yellow')


def _action_label(action: Action) -> str:
    if isinstance(action, CmdRunAction):
        cmd = action.command
        if len(cmd) > 80:
            cmd = cmd[:77] + '…'
        return f'bash: {cmd}'
    if isinstance(action, FileEditAction):
        return f'edit: {action.path}'
    if isinstance(action, FileWriteAction):
        return f'write: {action.path}'
    return type(action).__name__


def _file_label(action: Action) -> str:
    if isinstance(action, (FileEditAction, FileWriteAction)):
        return action.path or '—'
    if isinstance(action, CmdRunAction):
        return '—'
    return '—'


def _confirmation_frame_style(risk_text: str) -> str:
    if risk_text == 'HIGH':
        return 'red'
    if risk_text in {'MEDIUM', 'ASK'}:
        return 'yellow'
    if risk_text == 'LOW':
        return 'green'
    return 'dim'


def render_confirmation(
    console: Console,
    pending_action: Action,
) -> bool:
    """Render a confirmation table and return True if the user approves."""
    risk_text, risk_style = _risk_label(pending_action)
    frame_style = _confirmation_frame_style(risk_text)

    table = Table(
        show_header=True,
        header_style='bold dim',
        border_style='dim',
        show_lines=False,
        box=box.SIMPLE,
        pad_edge=False,
    )
    table.add_column('Target', style='dim', no_wrap=True)
    table.add_column('What will run', style='default')
    table.add_column('Risk', justify='center', no_wrap=True)

    table.add_row(
        _file_label(pending_action),
        _action_label(pending_action),
        Text(risk_text, style=risk_style),
    )

    console.print()
    console.print(
        Panel(
            table,
            title='[bold]Approve this action?[/bold]',
            title_align='left',
            border_style=frame_style,
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )

    # Show the thought / rationale if present
    thought = getattr(pending_action, 'thought', '')
    if thought:
        console.print(
            Panel(
                thought,
                title='[dim]Why the agent wants this[/dim]',
                title_align='left',
                border_style='dim',
                box=box.ROUNDED,
                padding=(0, 2),
            ),
        )

    console.print()
    console.print(
        '[dim]Keys: [bold]y[/bold] approve · [bold]n[/bold] reject · [bold]Enter[/bold] confirms the prompt below[/dim]'
    )
    console.print()
    return Confirm.ask(
        '[bold]Proceed?[/bold] [dim](y/n)[/dim]',
        console=console,
    )


def build_confirmation_action(approved: bool) -> ChangeAgentStateAction:
    """Build the event to send back to the engine."""
    state = AgentState.USER_CONFIRMED if approved else AgentState.USER_REJECTED
    return ChangeAgentStateAction(agent_state=state)
