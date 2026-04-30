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
    CLR_BRAND,
    CLR_CARD_BORDER,
    CLR_DECISION_BORDER,
    CLR_META,
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


def _shorten_middle(text: str, max_len: int = 88) -> str:
    """Keep long commands readable by preserving the start and the tail."""
    if not text or len(text) <= max_len:
        return text
    head_len = max(20, max_len // 2 - 2)
    tail_len = max(20, max_len - head_len - 1)
    return f'{text[:head_len]}…{text[-tail_len:]}'


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
        return f'shell: {_shorten_middle(action.command)}'
    if isinstance(action, FileEditAction):
        return f'edit: {_shorten_path(action.path or "—")}'
    if isinstance(action, FileWriteAction):
        return f'write: {_shorten_path(action.path or "—")}'
    return type(action).__name__


def _file_label(action: Action) -> str:
    if isinstance(action, (FileEditAction, FileWriteAction)):
        return _shorten_path(action.path or '—')
    if isinstance(action, CmdRunAction):
        return '—'
    return '—'


def _shorten_path(path: str, max_len: int = 48) -> str:
    """Keep path readable in the table; favour the leaf folder + filename."""
    if not path or len(path) <= max_len:
        return path
    tail = path[-(max_len - 1) :]
    return '…' + tail


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
    table.add_column('Target', style='dim', no_wrap=True, overflow='fold')
    table.add_column('What will run', style='default', overflow='fold')
    table.add_column('Risk', justify='center', no_wrap=True)

    table.add_row(
        _file_label(pending_action),
        _action_label(pending_action),
        Text(risk_text, style=risk_style),
    )

    # Risk badge in the title gives an at-a-glance signal even when the row
    # is scrolled out of focus on small terminals.
    title = Text()
    title.append('Approve this action  ', style='bold')
    title.append(f' {risk_text} ', style=f'reverse {risk_style}')

    console.print()
    console.print(
        Panel(
            table,
            title=title,
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
    # signature for the remainder of the session. Render keys as bold accents
    # so the user can scan their options without re-reading the sentence.
    hint = Text('  ')
    hint.append('[y]', style=f'bold {CLR_BRAND}')
    hint.append('es ', style=CLR_META)
    hint.append('[n]', style=f'bold {CLR_BRAND}')
    hint.append('o ', style=CLR_META)
    hint.append('[a]', style=f'bold {CLR_BRAND}')
    hint.append('lways allow', style=CLR_META)
    console.print(hint)
    answer = Prompt.ask(
        '  Approve?',
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
