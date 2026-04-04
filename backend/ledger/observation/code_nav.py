"""Observation type for language-server query results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from backend.core.enums import ObservationType
from backend.ledger.observation.observation import Observation


@dataclass
class LspQueryObservation(Observation):
    """Result of an LSP code-navigation query.

    Fields
    ------
    content:
        Human-readable structured text describing the results (locations,
        symbol names, hover text, etc.).  The LLM should parse this text to
        extract the information it needs.
    available:
        ``False`` when ``pylsp`` is not installed or could not start, so the
        LLM knows the graceful-degrade path was taken.
    """

    content: str = ''
    available: bool = True
    observation: ClassVar[str] = ObservationType.LSP_QUERY_RESULT
    observation_type: ClassVar[str] = ObservationType.LSP_QUERY_RESULT

    @property
    def message(self) -> str:
        if not self.available:
            return 'LSP unavailable — falling back to grep/search.'
        return 'LSP query completed.'

    def __str__(self) -> str:
        status = 'OK' if self.available else 'UNAVAILABLE'
        return f'**LspQueryObservation [{status}]**\n{self.content}'
