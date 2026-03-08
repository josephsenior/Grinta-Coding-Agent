"""Action type for language-server queries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from backend.core.enums import ActionConfirmationStatus, ActionSecurityRisk, ActionType
from backend.events.action.action import Action


@dataclass
class LspQueryAction(Action):
    """Query the language server for code-navigation information.

    Supported commands:
    - ``find_definition`` – jump to the definition of the symbol at (line, column)
    - ``find_references`` – find all usages of the symbol at (line, column)
    - ``hover``           – get hover/documentation for the symbol at (line, column)
    - ``list_symbols``    – list top-level symbols defined in *file*
    """

    file: str = ""
    command: str = (
        "find_definition"  # find_definition | find_references | hover | list_symbols
    )
    line: int = 1  # 1-based
    column: int = 1  # 1-based
    symbol: str = ""  # Optional filter for list_symbols

    action: ClassVar[str] = ActionType.LSP_QUERY
    runnable: ClassVar[bool] = True
    confirmation_state: ActionConfirmationStatus = ActionConfirmationStatus.CONFIRMED
    security_risk: ActionSecurityRisk = ActionSecurityRisk.LOW

    @property
    def message(self) -> str:
        return f"LSP {self.command} on {self.file}:{self.line}:{self.column}"

    def __str__(self) -> str:
        return f"**LspQueryAction** command={self.command} file={self.file} line={self.line} col={self.column}"

