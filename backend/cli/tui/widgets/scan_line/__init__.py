"""Scan-line action cards: 1-line transcript rows with detail-screen expand.

Each card mirrors OrientLine/ThinkingIndicator chrome (background #090d18,
left pipe, padding) with fixed ``height: 1`` and a ``⤢`` button that pushes
a :class:`DetailScreen`.

Subclasses override ``_line_text()`` and ``build_detail_screen()``.
"""

from __future__ import annotations

from backend.cli.tui.widgets.scan_line.card import ScanLineCard
from backend.cli.tui.widgets.scan_line.cards import (
    AgentMessageCard,
    AcceptanceCriteriaCard,
    BrowserCard,
    CompactionCard,
    DebuggerCard,
    DelegateCard,
    EditCard,
    MCPCard,
    PayloadCard,
    ShellCard,
    TerminalCard,
    _compact_path,
    _extract_syntax_error,
    _format_diff_delta,
    _parse_syntax_badge,
    _truncate,
)

__all__ = [
    'ScanLineCard',
    'AcceptanceCriteriaCard',
    'AgentMessageCard',
    'DelegateCard',
    'EditCard',
    'MCPCard',
    'PayloadCard',
    'ShellCard',
    'TerminalCard',
    'BrowserCard',
    'CompactionCard',
    'DebuggerCard',
    '_parse_syntax_badge',
    '_extract_syntax_error',
    '_format_diff_delta',
    '_compact_path',
    '_truncate',
]
