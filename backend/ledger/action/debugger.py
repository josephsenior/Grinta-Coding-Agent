"""Action type for Debug Adapter Protocol debugger sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from backend.core.enums import ActionConfirmationStatus, ActionSecurityRisk
from backend.core.schemas import ActionType
from backend.ledger.action.action import Action


@dataclass
class DebuggerAction(Action):
    """Action to control a stateful DAP debugger session."""

    debug_action: str = ''
    session_id: str | None = None
    adapter: str | None = None
    adapter_id: str | None = None
    adapter_command: list[str] = field(default_factory=list)
    adapter_transport: str | None = None
    adapter_host: str | None = None
    adapter_port: int | None = None
    language: str | None = None
    request: str = 'launch'
    program: str | None = None
    cwd: str | None = None
    args: list[str] = field(default_factory=list)
    launch_config: dict[str, Any] = field(default_factory=dict)
    initialize_options: dict[str, Any] = field(default_factory=dict)
    breakpoints: list[dict[str, Any]] = field(default_factory=list)
    file: str | None = None
    lines: list[int] = field(default_factory=list)
    thread_id: int | None = None
    frame_id: int | None = None
    variables_reference: int | None = None
    expression: str | None = None
    count: int | None = None
    stop_on_entry: bool = False
    just_my_code: bool = False
    python: str | None = None
    timeout: float | None = None
    action: ClassVar[str] = ActionType.DEBUGGER
    runnable: ClassVar[bool] = True
    confirmation_state: ActionConfirmationStatus = ActionConfirmationStatus.CONFIRMED
    security_risk: ActionSecurityRisk = ActionSecurityRisk.UNKNOWN

    @property
    def message(self) -> str:
        """Get a concise debugger action message."""
        target = self.session_id or self.program or self.adapter or self.language or ''
        return f'Debugger {self.debug_action}: {target}'

    def __str__(self) -> str:
        """Return a readable summary."""
        return (
            f'**DebuggerAction ({self.debug_action}, session={self.session_id})**\n'
            f'ADAPTER: {self.adapter or self.adapter_id or self.language or ""}\n'
            f'PROGRAM: {self.program or ""}'
        )


def is_debugger_action(action: object) -> bool:
    """Return True for debugger tool actions.

    ``isinstance(..., DebuggerAction)`` can fail when duplicate module loads produce
    distinct ``DebuggerAction`` classes. Fall back to the string tool id, instance
    fields, and the concrete class name (agent replay / schema paths).
    """

    def _is_dbg_token(v: object) -> bool:
        if v is None:
            return False
        if v in (ActionType.DEBUGGER, 'debugger'):
            return True
        return getattr(v, 'value', None) == 'debugger'

    if isinstance(action, DebuggerAction):
        return True
    if type(action).__name__ == 'DebuggerAction':
        return True
    for key in (getattr(type(action), 'action', None), getattr(action, 'action', None)):
        if _is_dbg_token(key):
            return True
    return False
