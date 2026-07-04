"""Action types for workspace discovery and structural search tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from backend.core.enums import ActionConfirmationStatus, ActionSecurityRisk, ActionType
from backend.ledger.action.action import Action


@dataclass
class GrepAction(Action):
    """Regex/text search across project file contents."""

    pattern: str = ''
    path: str = '.'
    file_pattern: str = ''
    output_mode: str = 'files_with_matches'
    context_lines: int = 2
    case_sensitive: bool = False
    head_limit: int | None = None
    offset: int = 0

    action: ClassVar[str] = ActionType.GREP
    runnable: ClassVar[bool] = True
    confirmation_state: ActionConfirmationStatus = ActionConfirmationStatus.CONFIRMED
    security_risk: ActionSecurityRisk = ActionSecurityRisk.LOW

    @property
    def message(self) -> str:
        return f'grep {self.pattern!r} in {self.path}'


@dataclass
class GlobAction(Action):
    """List files matching a glob pattern under a directory."""

    pattern: str = ''
    path: str = '.'
    head_limit: int | None = None
    offset: int = 0

    action: ClassVar[str] = ActionType.GLOB
    runnable: ClassVar[bool] = True
    confirmation_state: ActionConfirmationStatus = ActionConfirmationStatus.CONFIRMED
    security_risk: ActionSecurityRisk = ActionSecurityRisk.LOW

    @property
    def message(self) -> str:
        return f'glob {self.pattern!r} in {self.path}'


@dataclass
class FindSymbolsAction(Action):
    """Resolve symbol candidates across the workspace."""

    query: str = ''
    path: str = ''
    symbol_kind: str = ''
    include_private: bool = False

    action: ClassVar[str] = ActionType.FIND_SYMBOLS
    runnable: ClassVar[bool] = True
    confirmation_state: ActionConfirmationStatus = ActionConfirmationStatus.CONFIRMED
    security_risk: ActionSecurityRisk = ActionSecurityRisk.LOW

    @property
    def message(self) -> str:
        location = self.path or '.'
        return f'find symbols {self.query!r} in {location}'


@dataclass
class AnalyzeProjectStructureAction(Action):
    """Inspect repository structure or relationships for a command mode."""

    command: str = 'tree'
    path: str = '.'
    symbol: str = ''
    depth: int = 1
    direction: str = 'both'

    action: ClassVar[str] = ActionType.ANALYZE_PROJECT_STRUCTURE
    runnable: ClassVar[bool] = True
    confirmation_state: ActionConfirmationStatus = ActionConfirmationStatus.CONFIRMED
    security_risk: ActionSecurityRisk = ActionSecurityRisk.LOW

    @property
    def message(self) -> str:
        return f'analyze project structure {self.command!r} for {self.path}'
