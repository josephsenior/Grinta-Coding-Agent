"""Plan-approval confirmation UI for high-risk actions."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text

from backend.core.enums import AgentState, ActionSecurityRisk
from backend.ledger.action import (
    Action,
    CmdRunAction,
    FileEditAction,
    FileWriteAction,
    ChangeAgentStateAction,
)


def _risk_label(action: Action) -> tuple[str, str]:
    """Return (risk_text, style) for a given action."""
    risk = getattr(action, "security_risk", ActionSecurityRisk.UNKNOWN)
    try:
        if not isinstance(risk, ActionSecurityRisk):
            risk = ActionSecurityRisk(int(risk))
    except (ValueError, TypeError):
        risk = ActionSecurityRisk.UNKNOWN

    if risk == ActionSecurityRisk.HIGH:
        return ("HIGH", "bold red")
    if risk == ActionSecurityRisk.MEDIUM:
        return ("MEDIUM", "yellow")
    if risk == ActionSecurityRisk.LOW:
        return ("LOW", "green")
    return ("ASK", "bright_yellow")


def _action_label(action: Action) -> str:
    if isinstance(action, CmdRunAction):
        cmd = action.command
        if len(cmd) > 80:
            cmd = cmd[:77] + "…"
        return f"bash: {cmd}"
    if isinstance(action, FileEditAction):
        return f"edit: {action.path}"
    if isinstance(action, FileWriteAction):
        return f"write: {action.path}"
    return type(action).__name__


def _file_label(action: Action) -> str:
    if isinstance(action, (FileEditAction, FileWriteAction)):
        return action.path or "—"
    if isinstance(action, CmdRunAction):
        return "—"
    return "—"


def render_confirmation(
    console: Console,
    pending_action: Action,
) -> bool:
    """Render a confirmation table and return True if the user approves."""
    risk_text, risk_style = _risk_label(pending_action)

    table = Table(
        title="[bold]Action Approval Required[/bold]",
        border_style="bright_yellow",
        show_lines=True,
    )
    table.add_column("File", style="cyan", min_width=20)
    table.add_column("Action", style="white", min_width=30)
    table.add_column("Risk", justify="center", min_width=8)

    table.add_row(
        _file_label(pending_action),
        _action_label(pending_action),
        Text(risk_text, style=risk_style),
    )

    console.print()
    console.print(table)

    # Show the thought / rationale if present
    thought = getattr(pending_action, "thought", "")
    if thought:
        console.print(
            Panel(thought, title="Agent Rationale", border_style="dim", padding=(0, 2)),
        )

    console.print()
    return Confirm.ask("[bold yellow]Approve this action?[/bold yellow]", console=console)


def build_confirmation_action(approved: bool) -> ChangeAgentStateAction:
    """Build the event to send back to the engine."""
    state = AgentState.USER_CONFIRMED if approved else AgentState.USER_REJECTED
    return ChangeAgentStateAction(agent_state=state)
