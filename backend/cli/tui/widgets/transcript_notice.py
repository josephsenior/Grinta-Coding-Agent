"""Soft transcript notice for recoverable errors and tool feedback."""

from __future__ import annotations

from textual.widgets import Static

from backend.cli.event_rendering.text_utils import sanitize_visible_transcript_text
from backend.cli.theme import NAVY_BG_NOTICE, NAVY_TEXT_NOTICE


class TranscriptNotice(Static):
    """Unified soft notice row — dim text on a subtle background, no border."""

    DEFAULT_CSS = f"""
    TranscriptNotice {{
        width: 100%;
        height: auto;
        margin: 0 0 2 0;
        padding: 0 1;
        background: {NAVY_BG_NOTICE};
        border: none;
        color: {NAVY_TEXT_NOTICE};
    }}
    """

    def __init__(self, text: str, *, id: str | None = None) -> None:
        content = sanitize_visible_transcript_text(text)
        super().__init__(content or '', id=id)
