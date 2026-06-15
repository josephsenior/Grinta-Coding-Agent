"""Soft transcript notice for recoverable errors and tool feedback."""

from __future__ import annotations

from textual.widgets import Static

from backend.cli.event_rendering.text_utils import sanitize_visible_transcript_text


class TranscriptNotice(Static):
    """Unified soft notice row — dim text on a subtle background, no border."""

    def __init__(self, text: str, *, id: str | None = None) -> None:
        content = sanitize_visible_transcript_text(text)
        super().__init__(content or '', id=id)
