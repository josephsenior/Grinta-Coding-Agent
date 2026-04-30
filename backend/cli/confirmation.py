"""Plan-approval confirmation UI for high-risk actions."""

from __future__ import annotations

from dataclasses import dataclass

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from backend.cli.theme import (
    CLR_CARD_BORDER,
    CLR_DECISION_BORDER,
    CLR_RISK_ASK,
    CLR_RISK_HIGH,
    CLR_RISK_LOW,
    CLR_RISK_MEDIUM,
)
from backend.core.enums import ActionSecurityRisk, AgentState
from backend.ledger.action import (
    Action,
    ChangeAgentStateAction,
    CmdRunAction,
    FileEditAction,
    FileWriteAction,
)


@dataclass(frozen=True)
class ConfirmationDecision:
    """Outcome of a single confirmation prompt.

    ``approved`` is the y/n answer. ``remember`` is True when the user
    asked to whitelist this exact action signature for the rest of the
    session (the "always allow" choice).
    """

    approved: bool
    remember: bool = False


def _risk_label(action: Action) -> tuple[str, str]:
    """Return (risk_text, style) for a given action."""
    risk = getattr(action, 'security_risk', ActionSecurityRisk.UNKNOWN)
    try:
        if not isinstance(risk, ActionSecurityRisk):
            risk = ActionSecurityRisk(int(risk))
    except (ValueError, TypeError):
        risk = ActionSecurityRisk.UNKNOWN

    if risk == ActionSecurityRisk.HIGH:
        return ('HIGH', CLR_RISK_HIGH)
    if risk == ActionSecurityRisk.MEDIUM:
        return ('MEDIUM', CLR_RISK_MEDIUM)
    if risk == ActionSecurityRisk.LOW:
        return ('LOW', CLR_RISK_LOW)
    return ('ASK', CLR_RISK_ASK)


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
        return CLR_RISK_HIGH.replace('bold ', '')
    if risk_text in {'MEDIUM', 'ASK'}:
        return CLR_DECISION_BORDER
    if risk_text == 'LOW':
        return CLR_RISK_LOW
    return CLR_CARD_BORDER


def render_confirmation(
    console: Console,
    pending_action: Action,
) -> ConfirmationDecision:
    """Render a confirmation table and return the user's decision.

    Returns a :class:`ConfirmationDecision` describing whether the action
    was approved and whether the user asked to remember the choice for
    the rest of the session.
    """
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
                border_style=CLR_CARD_BORDER,
                box=box.ROUNDED,
                padding=(0, 2),
            ),
        )

    # y = approve once, n = reject, a = always allow this exact action
    # signature for the remainder of the session.
    answer = Prompt.ask(
        '  [bold]Approve?[/bold] [dim]\\[y/n/a=always][/dim]',
        console=console,
        choices=['y', 'n', 'a'],
        default='n',
        show_choices=False,
        show_default=False,
    )
    answer = (answer or 'n').strip().lower()
    if answer == 'a':
        return ConfirmationDecision(approved=True, remember=True)
    return ConfirmationDecision(approved=answer == 'y', remember=False)


def build_confirmation_action(approved: bool) -> ChangeAgentStateAction:
    """Build the event to send back to the engine."""
    state = AgentState.USER_CONFIRMED if approved else AgentState.USER_REJECTED
    return ChangeAgentStateAction(agent_state=state)
