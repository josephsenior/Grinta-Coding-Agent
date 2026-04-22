"""Shared spacing and framing for CLI transcript and live agent chrome.

Keeps horizontal inset, panel padding, and vertical rhythm consistent across
user bubbles, assistant output, working/draft panels, and the HUD.
"""

from __future__ import annotations

from typing import Any

from rich.padding import Padding
from rich.text import Text

# Symmetric horizontal inset so transcript and footer align cleanly.
TRANSCRIPT_LEFT_INSET = 5
TRANSCRIPT_RIGHT_INSET = 5

# Inner padding for rounded callout-style panels (vertical, horizontal).
CALLOUT_PANEL_PADDING = (1, 2)

# Inner padding for compact activity/live panels so rows align across sections.
ACTIVITY_PANEL_PADDING = (0, 1)

# Space below each activity block (tool rows) for scanability. Slightly increased
# to provide a small visual gap between adjacent activity cards.
ACTIVITY_BLOCK_BOTTOM_PAD = (0, 0, 2, 0)

# User-facing activity card titles (rounded panels under "Tools & commands").
# Keep these short Title Case nouns so the transcript scans consistently.
ACTIVITY_CARD_TITLE_FILES = 'Files'
ACTIVITY_CARD_TITLE_TERMINAL = 'Terminal'
ACTIVITY_CARD_TITLE_BROWSER = 'Browser'
ACTIVITY_CARD_TITLE_MCP = 'MCP'
ACTIVITY_CARD_TITLE_MEMORY = 'Memory'
ACTIVITY_CARD_TITLE_CODE = 'Code'
ACTIVITY_CARD_TITLE_DELEGATION = 'Delegation'
ACTIVITY_CARD_TITLE_CHECKPOINT = 'Checkpoint'
ACTIVITY_CARD_TITLE_SEARCH = 'Search'
ACTIVITY_CARD_TITLE_TOOL = 'Tool'
ACTIVITY_CARD_TITLE_SHELL = 'Shell'


def frame_transcript_body(renderable: Any) -> Any:
    """Left/right inset for committed transcript blocks."""
    return Padding(
        renderable,
        pad=(0, TRANSCRIPT_RIGHT_INSET, 0, TRANSCRIPT_LEFT_INSET),
        expand=False,
    )


def frame_live_body(renderable: Any) -> Any:
    """Align live panels with the same inset as the transcript."""
    return frame_transcript_body(renderable)


def gap_below_live_section(renderable: Any) -> Any:
    """Vertical rhythm between stacked live sections (task / draft / working)."""
    return Padding(renderable, pad=(0, 0, 1, 0), expand=False)


def spacer_live_section() -> Text:
    """Single blank line between live regions when a full empty row is needed."""
    return Text('')
