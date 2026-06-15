"""Activity card widget for the Grinta TUI.

Renders tool calls, shell commands, file operations, and other agent activities
as compact, consistent cards with collapsed/expanded states.

Collapsed cards show:
  [status icon] [action] [target] [compact outcome]

Expanded cards show:
  bordered box with content/diff/output/metadata
"""

from __future__ import annotations

from backend.cli.tui.widgets.activity_card.card import ActivityCard
from backend.cli.tui.widgets.activity_card.constants import (
    DIFF_ADD_PREFIX,
    DIFF_CTX_PREFIX,
    DIFF_REM_PREFIX,
    DIFF_SPLIT_PREFIX,
)
from backend.cli.tui.widgets.activity_card.diff_lines import (
    DiffLine,
    SplitDiffLine,
    encode_diff_line,
    encode_split_diff_line,
)
from backend.cli.tui.widgets.activity_card.message_widgets import (
    AgentMessage,
    LiveResponse,
    ThinkingIndicator,
    TurnCompletion,
    UserMessage,
)
from backend.cli.tui.widgets.activity_card.orient import OrientBurst, OrientLine

__all__ = [
    'DIFF_ADD_PREFIX',
    'DIFF_CTX_PREFIX',
    'DIFF_REM_PREFIX',
    'DIFF_SPLIT_PREFIX',
    'ActivityCard',
    'AgentMessage',
    'DiffLine',
    'LiveResponse',
    'OrientBurst',
    'OrientLine',
    'SplitDiffLine',
    'ThinkingIndicator',
    'TurnCompletion',
    'UserMessage',
    'encode_diff_line',
    'encode_split_diff_line',
]
