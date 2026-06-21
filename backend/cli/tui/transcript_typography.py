"""Shared transcript typography — muted, low-brightness hierarchy.

Use these tokens for labels, body, and metadata across orient lines,
scan-line cards, and message blocks so the feed reads consistently.
"""

from __future__ import annotations

# Primary readable content (targets, messages, paths)
TX_BODY = '#c8d4e8'
# Secondary values (durations, compact summaries)
TX_BODY_DIM = '#9aa8b8'
# Role / verb labels when not state-tinted
TX_LABEL = '#5a7a9a'
# Metadata fragments (counts, hints)
TX_META = '#6f83aa'
# Separators and dim affordances
TX_MUTED = '#54597b'
# Keyboard key + action hints (HUD, detail screens)
TX_KEY_HINT = '#91abec'
TX_ACTION_HINT = '#c8d4e8'


def esc_hint_markup(action: str) -> str:
    """Rich markup for ``esc`` shortcut hints."""
    return f'[{TX_KEY_HINT}]esc[/] [{TX_ACTION_HINT}]{action}[/]'

# Left-pipe accents for non-action message blocks
AGENT_PIPE = '#3d4a66'
USER_PIPE = '#91abec'
THINKING_PIPE = '#42a394'
THINKING_LABEL = '#42a394'
COMPLETION_PIPE = '#3d5a4a'
ERROR_PIPE = '#5a2d2d'

# Domain pipes for orient / artifact rows
ORIENT_PIPE_DEFAULT = '#2d4a6a'
ORIENT_PREFIX_DEFAULT = '#5a7a9a'
# File-edit scan-line label + left pipe (paired with read ↳ / orient blue)
EDIT_CARD_ACCENT = '#91abec'
WORKER_PIPE = '#3d5a4a'
MCP_PIPE = '#3a3d5a'
