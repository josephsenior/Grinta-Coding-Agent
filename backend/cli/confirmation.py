"""Plan-approval confirmation UI for high-risk actions."""

from __future__ import annotations

from dataclasses import dataclass

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from backend.cli.text_truncation import shorten_middle, shorten_path
from backend.cli.theme import (
    CLR_BRAND,
    CLR_CARD_BORDER,
    CLR_DECISION_BORDER,
    CLR_META,
    CLR_RISK_ASK,
    CLR_RISK_HIGH,
    CLR_RISK_LOW,
    CLR_RISK_MEDIUM,
    STYLE_BOLD,
    STYLE_BOLD_DIM,
    STYLE_DEFAULT,
    STYLE_DIM,
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

    ``suppress_low_risk`` is True when the user chose to auto-approve
    all remaining LOW-risk actions for this session.
    """

    approved: bool
    remember: bool = False
    suppress_low_risk: bool = False


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
        return f'shell: {shorten_middle(action.command)}'
    if isinstance(action, FileEditAction):
        return f'edit: {shorten_path(action.path or "—")}'
    if isinstance(action, FileWriteAction):
        return f'write: {shorten_path(action.path or "—")}'
    return type(action).__name__


def _file_label(action: Action) -> str:
    if isinstance(action, (FileEditAction, FileWriteAction)):
        return shorten_path(action.path or '—')
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
    is_high_risk = risk_text == 'HIGH'

    # HIGH-risk actions get a prominent warning banner before the panel.
    if is_high_risk:
        from rich.panel import Panel as WarningPanel

        console.print()
        console.print(
            WarningPanel(
                'This action can modify your system or environment.\n'
                'Type [bold]yes[/bold] to confirm, or [bold]n[/bold] to reject.',
                title='[bold red]⚠  REQUIRES APPROVAL[/bold red]',
                title_align='left',
                border_style=CLR_RISK_HIGH,
                box=box.HEAVY,
                padding=(1, 2),
            )
        )

    table = Table(
        show_header=True,
        header_style=STYLE_BOLD_DIM,
        border_style=CLR_CARD_BORDER,
        show_lines=False,
        box=box.ROUNDED,
        pad_edge=False,
    )
    table.add_column('Target', style=STYLE_DIM, no_wrap=True, overflow='fold')
    table.add_column('What will run', style=STYLE_DEFAULT, overflow='fold')
    table.add_column('Risk', justify='center', no_wrap=True)

    table.add_row(
        _file_label(pending_action),
        _action_label(pending_action),
        Text(risk_text, style=risk_style),
    )

    # Risk badge in the title gives an at-a-glance signal even when the row
    # is scrolled out of focus on small terminals.
    title = Text()
    title.append('Approve this action  ', style=STYLE_BOLD)
    title.append(f' {risk_text} ', style=f'reverse {risk_style}')

    console.print()
    console.print(
        Panel(
            table,
            title=title,
            title_align='left',
            border_style=frame_style,
            box=box.HEAVY if is_high_risk else box.ROUNDED,
            padding=(1, 2),
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
                padding=(1, 2),
            ),
        )

    if is_high_risk:
        # HIGH risk requires typing "yes" in full — no single-key approval.
        hint = Text('  ')
        hint.append('[yes]', style=f'bold {CLR_RISK_HIGH}')
        hint.append(' approve  ', style=CLR_META)
        hint.append('[n]', style=f'bold {CLR_BRAND}')
        hint.append('o  ', style=CLR_META)
        hint.append('[a]', style=f'bold {CLR_BRAND}')
        hint.append('lways allow', style=CLR_META)
        console.print(hint)
        answer = Prompt.ask(
            '  Approve?',
            console=console,
            default='n',
            show_choices=False,
            show_default=False,
        )
        answer = (answer or 'n').strip().lower()
        if answer in ('a', 'always'):
            return ConfirmationDecision(approved=True, remember=True)
        return ConfirmationDecision(approved=answer == 'yes', remember=False)

    is_low_risk = risk_text == 'LOW'
    hint = Text('  ')
    hint.append('[y]', style=f'bold {CLR_BRAND}')
    hint.append('es ', style=CLR_META)
    hint.append('[n]', style=f'bold {CLR_BRAND}')
    hint.append('o ', style=CLR_META)
    hint.append('[a]', style=f'bold {CLR_BRAND}')
    hint.append('lways allow', style=CLR_META)
    if is_low_risk:
        hint.append('   ', style=CLR_META)
        hint.append('[d]', style=f'bold {CLR_RISK_LOW}')
        hint.append("don't ask again this session", style=CLR_META)
    console.print(hint)

    choices = ['y', 'n', 'a']
    if is_low_risk:
        choices.append('d')

    answer = Prompt.ask(
        '  Approve?',
        console=console,
        choices=choices,
        default='n',
        show_choices=False,
        show_default=False,
    )
    answer = (answer or 'n').strip().lower()
    if answer == 'a':
        return ConfirmationDecision(approved=True, remember=True)
    if answer == 'd':
        return ConfirmationDecision(approved=True, remember=False, suppress_low_risk=True)
    return ConfirmationDecision(approved=answer == 'y', remember=False)


def build_confirmation_action(approved: bool) -> ChangeAgentStateAction:
    """Build the event to send back to the engine."""
    state = AgentState.USER_CONFIRMED if approved else AgentState.USER_REJECTED
    return ChangeAgentStateAction(agent_state=state)
