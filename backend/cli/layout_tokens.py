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

# Space below each activity block (tool rows) for scanability.
ACTIVITY_BLOCK_BOTTOM_PAD = (0, 0, 1, 0)


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
