"""Structured observations for discovery and project-structure tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from backend.core.enums import ObservationType
from backend.ledger.observation.observation import Observation


@dataclass
class GrepObservation(Observation):
    """Result of a ``grep`` regex/text search."""

    content: str = ''
    pattern: str = ''
    path: str = '.'
    output_mode: str = 'files_with_matches'
    lines: list[str] = field(default_factory=list)
    match_count: int = 0
    file_count: int = 0
    error: str = ''
    observation: ClassVar[str] = ObservationType.GREP_RESULT

    @property
    def message(self) -> str:
        if self.error:
            return self.error
        if self.match_count:
            return f'{self.match_count} matches in {self.file_count} files'
        return 'No matches found.'


@dataclass
class GlobObservation(Observation):
    """Result of a ``glob`` file listing."""

    content: str = ''
    pattern: str = ''
    path: str = '.'
    files: list[str] = field(default_factory=list)
    file_count: int = 0
    error: str = ''
    observation: ClassVar[str] = ObservationType.GLOB_RESULT

    @property
    def message(self) -> str:
        if self.error:
            return self.error
        if self.file_count:
            return f'{self.file_count} files'
        return 'No matching files found.'


@dataclass
class FindSymbolsObservation(Observation):
    """Result of a ``find_symbols`` workspace symbol search."""

    query: str = ''
    path: str = '.'
    symbol_kind: str = ''
    include_private: bool = False
    candidates: list[dict[str, object]] = field(default_factory=list)
    error: str = ''
    observation: ClassVar[str] = ObservationType.FIND_SYMBOLS_RESULT

    @property
    def message(self) -> str:
        if self.error:
            return self.error
        count = len(self.candidates)
        if count:
            return f'{count} symbol candidates'
        return 'No matching symbols found.'


@dataclass
class AnalyzeProjectStructureObservation(Observation):
    """Result of an ``analyze_project_structure`` command."""

    command: str = 'tree'
    path: str = '.'
    symbol: str = ''
    depth: int = 1
    direction: str = 'both'
    error: str = ''
    observation: ClassVar[str] = ObservationType.ANALYZE_PROJECT_STRUCTURE_RESULT

    @property
    def message(self) -> str:
        if self.error:
            return self.error
        return f'{self.command} analysis completed'
