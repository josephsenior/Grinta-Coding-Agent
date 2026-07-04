"""Per-step preview/commit state for assistant transcript rendering.

Streaming events update live preview widgets only. Permanent transcript rows
are committed at most once per logical segment (thinking, preamble, final).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AssistantStepDraft:
    """Tracks which assistant-step segments are preview-only vs committed."""

    thinking_committed: bool = False
    content_committed: bool = False
    committed_content: str = ''
    committed_preamble: str = ''
    preview_content: str = ''

    def reset(self) -> None:
        self.thinking_committed = False
        self.content_committed = False
        self.committed_content = ''
        self.committed_preamble = ''
        self.preview_content = ''

    def begin_stream_leg(self) -> None:
        """Start a new preview leg while keeping dedup keys from prior commits."""
        self.thinking_committed = False
        self.content_committed = False
        self.preview_content = ''

    def accept_stream_preview(self, *, is_final: bool, incoming: str = '') -> bool:
        """Return ``False`` when a stream chunk must not update the live preview."""
        if is_final:
            return True
        normalized = (incoming or '').strip()
        if self.content_committed:
            if normalized and self._is_stale_replay(normalized):
                return False
            self.begin_stream_leg()
            return True
        return True

    def _is_stale_replay(self, normalized: str) -> bool:
        for committed in (self.committed_content, self.committed_preamble):
            if not committed:
                continue
            if committed == normalized or committed.startswith(normalized):
                return True
        return False

    def set_preview_content(self, normalized: str) -> None:
        if normalized:
            self.preview_content = normalized

    def should_render_thought(self) -> bool:
        return not self.thinking_committed

    def note_thinking_committed(self) -> None:
        self.thinking_committed = True

    def should_commit_content(
        self, normalized: str, *, transcript_only: bool = False
    ) -> bool:
        if not normalized:
            return False
        if transcript_only:
            return normalized not in (
                self.committed_preamble,
                self.committed_content,
            )
        if not self.content_committed:
            return True
        return normalized != self.committed_content

    def note_content_committed(
        self, normalized: str, *, transcript_only: bool = False
    ) -> None:
        self.content_committed = True
        if transcript_only:
            self.committed_preamble = normalized
        else:
            self.committed_content = normalized
        self.preview_content = ''
