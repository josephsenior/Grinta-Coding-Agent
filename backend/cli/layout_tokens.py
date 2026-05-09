"""Shared spacing and framing for CLI transcript and live agent chrome.

Keeps horizontal inset, panel padding, and vertical rhythm consistent across
user bubbles, assistant output, working/draft panels, and the HUD.
"""

from __future__ import annotations

from typing import Any

from rich.padding import Padding
from rich.text import Text

from backend.cli.theme import (
    CLR_CARD_BORDER,
    CLR_CARD_TITLE,
    CLR_DECISION_BORDER,
    CLR_DRAFT_BORDER,
    CLR_THINKING_BORDER,
    CLR_WORKER_BORDER,
)

# Slightly tighter horizontal inset for a more polished, modern feel.
TRANSCRIPT_LEFT_INSET = 3
TRANSCRIPT_RIGHT_INSET = 3

# Inner padding for rounded callout-style panels (vertical, horizontal).
CALLOUT_PANEL_PADDING = (0, 1)

# Inner padding for activity tool cards (tight horizontal rhythm).
ACTIVITY_PANEL_PADDING = (0, 1)

# Vertical space below each activity block — tighter than before for premium density.
ACTIVITY_BLOCK_BOTTOM_PAD = (0, 0, 0, 0)

# Horizontal chrome added by ``format_callout_panel`` and rounded activity
# panels: 2 border characters + ``CALLOUT_PANEL_PADDING`` horizontal cells on
# each side. Exported so wrappers (e.g. the reasoning thought-line wrap) can
# compute interior widths from a single source of truth instead of guessing.
CALLOUT_PANEL_CHROME_WIDTH = 2 + 2 * CALLOUT_PANEL_PADDING[1]
ACTIVITY_PANEL_CHROME_WIDTH = 2 + 2 * ACTIVITY_PANEL_PADDING[1]

# Shared palette for the transcript chrome. Centralizing these keeps live panels,
# activity cards, and decision callouts visually consistent during long sessions.
ACTIVITY_SECTION_TITLE = ''
ACTIVITY_CARD_BORDER_STYLE = CLR_CARD_BORDER
ACTIVITY_CARD_TITLE_STYLE = CLR_CARD_TITLE
LIVE_PANEL_ACCENT_STYLE = CLR_THINKING_BORDER
DRAFT_PANEL_ACCENT_STYLE = CLR_DRAFT_BORDER
DECISION_PANEL_ACCENT_STYLE = CLR_DECISION_BORDER

# User-facing activity card titles (rounded panels under "Tools & commands").
# Keep these short Title Case nouns so the transcript scans consistently.
ACTIVITY_CARD_TITLE_FILES = ''
ACTIVITY_CARD_TITLE_TERMINAL = ''
ACTIVITY_CARD_TITLE_BROWSER = 'Browser'
ACTIVITY_CARD_TITLE_MCP = 'Connected Tool'
ACTIVITY_CARD_TITLE_MEMORY = 'Memory'
ACTIVITY_CARD_TITLE_CODE = 'Code'
ACTIVITY_CARD_TITLE_DELEGATION = 'Workers'
ACTIVITY_CARD_TITLE_CHECKPOINT = 'Checkpoint'
ACTIVITY_CARD_TITLE_SEARCH = 'Search'
ACTIVITY_CARD_TITLE_TOOL = 'Tool'
ACTIVITY_CARD_TITLE_SHELL = 'Shell'

# Worker live-panel chrome
WORKER_PANEL_ACCENT_STYLE = CLR_WORKER_BORDER
WORKER_LABEL_WIDTH = 18  # fixed width for worker labels in the live table
WORKER_TIMER_WIDTH = 8  # width for elapsed timer column


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
