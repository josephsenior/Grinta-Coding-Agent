"""Streaming methods for CLIEventRenderer.

Streaming chunks & reasoning (_handle_streaming_*/_absorb_inline_streaming_thinking/_apply_reasoning_text).

Extracted from backend/cli/event_renderer.py to keep the parent module
under the per-file LOC budget. All methods rely on attributes/methods
defined on CLIEventRenderer; this mixin is meant to be combined with
that class via multiple inheritance.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from rich import box
from rich.console import Console, ConsoleOptions, Group, RenderResult
from rich.live import Live
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.style import Style
from rich.text import Text

from backend.cli._event_renderer.constants import (
    THINK_EXTRACT_RE as _THINK_EXTRACT_RE,
)
from backend.cli._event_renderer.constants import (
    THINK_STRIP_RE as _THINK_STRIP_RE,
)
from backend.cli._event_renderer.error_panel import (
    build_error_panel as _build_error_panel,
)
from backend.cli._event_renderer.error_panel import (
    use_recoverable_notice_style as _use_recoverable_notice_style,
)
from backend.cli._event_renderer.panels import (
    PendingActivityCard,
)
from backend.cli._event_renderer.panels import (
    build_delegate_worker_panel as _build_delegate_worker_panel,
)
from backend.cli._event_renderer.panels import (
    build_system_notice_panel as _build_system_notice_panel,
)
from backend.cli._event_renderer.panels import (
    build_task_panel as _build_task_panel,
)
from backend.cli._event_renderer.panels import (
    delegate_worker_panel_signature as _delegate_worker_panel_signature,
)
from backend.cli._event_renderer.panels import (
    normalize_system_title as _normalize_system_title,
)
from backend.cli._event_renderer.panels import (
    task_panel_signature as _task_panel_signature,
)
from backend.cli._event_renderer.sidebar import (
    build_sidebar as _build_sidebar,
)
from backend.cli._event_renderer.sidebar import (
    compute_main_width as _compute_main_width,
)
from backend.cli._event_renderer.text_utils import (
    normalize_reasoning_text as _normalize_reasoning_text,
)
from backend.cli._event_renderer.text_utils import (
    sanitize_visible_transcript_text as _sanitize_visible_transcript_text,
)
from backend.cli._event_renderer.text_utils import (
    show_reasoning_text as _show_reasoning_text,
)
from backend.cli.hud import HUDBar
from backend.cli.layout_tokens import (
    ACTIVITY_BLOCK_BOTTOM_PAD,
    ACTIVITY_CARD_TITLE_SHELL,
    CALLOUT_PANEL_PADDING,
    LIVE_PANEL_ACCENT_STYLE,
    frame_live_body,
    frame_transcript_body,
    gap_below_live_section,
    spacer_live_section,
)
from backend.cli.path_links import file_uri_for_path, linkify_plain
from backend.cli.status_chrome import rich_fake_prompt_group, status_fields_from_hud
from backend.cli.theme import (
    CLR_ERR_BODY,
    CLR_ERR_ICON,
    CLR_STATUS_ERR,
    CLR_STATUS_WARN,
    CLR_USER_BG,
    CLR_USER_BORDER,
    CLR_WARN_BODY,
    CLR_WARN_ICON,
    STYLE_BOLD_DIM,
    STYLE_DIM,
    accessible_mode_enabled,
    get_grinta_pygments_style,
)
from backend.cli.tool_call_display import (
    looks_like_streaming_tool_arguments,
    streaming_args_hint,
    tool_headline,
    try_format_message_as_tool_json,
)
from backend.cli.transcript import (
    format_activity_block,
    format_activity_shell_block,
    format_activity_turn_header,
    format_ground_truth_tool_line,
)
from backend.core.enums import AgentState, EventSource
from backend.ledger import EventStreamSubscriber
from backend.ledger.action import (
    Action,
    NullAction,
    StreamingChunkAction,
)
from backend.ledger.observation import (
    AgentStateChangedObservation,
    NullObservation,
    Observation,
)

if TYPE_CHECKING:
    from backend.cli.event_renderer import CLIEventRenderer


logger = logging.getLogger(__name__)

class _EventRendererStreamingMixin(CLIEventRenderer if TYPE_CHECKING else object):
    """Mixin class — see module docstring."""

    def _handle_streaming_chunk(self, action: StreamingChunkAction) -> None:
        raw = action.accumulated

        # Tool call argument streaming: spinner + headline only. Do not put partial
        # JSON / command hints into the thinking buffer — those were flushed as dim
        # lines and looked like duplicate ``$ cmd`` reasoning (not LLM thinking).
        if action.is_tool_call:
            self._handle_streaming_tool_call(action)
            return

        # Route <redacted_thinking> content to the reasoning display so the user sees
        # the model's chain-of-thought in real time.
        if looks_like_streaming_tool_arguments(raw):
            self._ensure_reasoning()
            self._reasoning.update_action('Tool…')
            self._streaming_accumulated = ''
            self.refresh()
            return

        # First-class thinking field: if the provider streamed reasoning tokens
        # via the dedicated thinking channel, display them immediately.
        self._absorb_streaming_thinking_field(action)
        # Fallback: extract <redacted_thinking> tags embedded in content text
        # (backward compat for models that embed thinking in the main stream).
        self._absorb_inline_streaming_thinking(raw)

        self._streaming_final = action.is_final
        if action.is_final:
            self._hud.state.llm_calls += 1
        # Always force redraw on streaming updates; throttling here made token
        # output feel delayed vs. the model (refresh() only coalesces to ~20fps).
        self.refresh(force=True)
    def _handle_streaming_tool_call(self, action: StreamingChunkAction) -> None:
        tool_name = action.tool_call_name or 'tool'
        _icon, headline = tool_headline(tool_name, use_icons=self._cli_tool_icons)
        self._ensure_reasoning()
        raw = (action.accumulated or '').strip()
        hint = streaming_args_hint(tool_name, raw)
        if hint:
            self._reasoning.update_action(f'{headline}: {hint}')
        else:
            self._reasoning.update_action(f'{headline}…')
        # Clear any text content that arrived before the tool call started
        # (e.g. a preamble "[" or task-list header). Keeping it would leave
        # a stale draft-reply preview panel alongside the
        # Thinking spinner for the entire duration of the tool call stream.
        self._streaming_accumulated = ''
        self.refresh()
    def _absorb_streaming_thinking_field(
        self,
        action: StreamingChunkAction,
    ) -> None:
        if not (action.thinking_accumulated and _show_reasoning_text()):
            return
        cleaned_thinking = _sanitize_visible_transcript_text(
            action.thinking_accumulated
        )
        if cleaned_thinking:
            self._ensure_reasoning()
            self._reasoning.set_streaming_thought(cleaned_thinking)
    def _absorb_inline_streaming_thinking(self, raw: str) -> None:
        think_match = _THINK_EXTRACT_RE.search(raw)
        if not think_match:
            self._streaming_accumulated = _sanitize_visible_transcript_text(raw)  # type: ignore[unreachable]
            return
        thinking_text = _sanitize_visible_transcript_text(think_match.group(1))
        if thinking_text and _show_reasoning_text():
            self._ensure_reasoning()
            self._reasoning.set_streaming_thought(thinking_text)
        # Strip thinking from the streaming preview.
        display_text = _THINK_STRIP_RE.sub('', raw).strip()
        self._streaming_accumulated = _sanitize_visible_transcript_text(display_text)
    _STATE_HUD_UPDATES: dict[Any, tuple[str, str]] = {
        # Populated lazily in :meth:`_state_hud_updates`.
    }
    def _ensure_reasoning(self) -> None:
        if not self._reasoning.active:
            self._reasoning.start()
    def _append_assistant_message(
        self, display_content: str | Any, *, attachments: list[Any] | None = None
    ) -> None:
        """Render a committed assistant message block in the transcript."""
        from rich.text import Text as RichText

        if isinstance(display_content, RichText):
            self._last_assistant_message_text = display_content.plain
            self._append_history(Text(''))
            self._append_history(display_content)
            for attachment in attachments or []:
                self._append_history(attachment)
            return

        display_content = _sanitize_visible_transcript_text(display_content)
        if not display_content:
            return
        self._last_assistant_message_text = display_content

        # Render assistant content directly (no "Assistant" header).
        # Keep a small top spacer for readability.
        self._append_history(Text(''))
        tool_lines = try_format_message_as_tool_json(
            display_content, use_icons=self._cli_tool_icons
        )
        if tool_lines is not None:
            _icon, friendly = tool_lines
            for line in friendly.split('\n'):
                self._append_history(Text(line, style=LIVE_PANEL_ACCENT_STYLE))
        else:
            self._append_assistant_body(display_content)
        for attachment in attachments or []:
            self._append_history(attachment)
    def _append_assistant_body(self, display_content: str) -> None:
        """Render the body of an assistant message that isn't a tool JSON."""
        s = display_content.strip()
        if '<search_results>' in s:
            summary = self._summarize_search_results_block(s)
            self._append_history(Text(summary, style=LIVE_PANEL_ACCENT_STYLE))
            return
        plain_summary = self._summarize_plain_match_lines(s)
        if plain_summary is not None:
            self._append_history(Text(plain_summary, style=LIVE_PANEL_ACCENT_STYLE))
            return
        self._append_history(
            Padding(
                Markdown(display_content, code_theme=get_grinta_pygments_style()),
                (0, 0, 1, 0),
            )
        )
    def _apply_reasoning_text(self, text: str) -> None:
        """Update the reasoning display while keeping tagged tool payloads out of the transcript."""
        action_label, thought = _normalize_reasoning_text(text)
        if action_label is None and thought is None:
            return
        self._ensure_reasoning()
        if action_label:
            self._reasoning.update_action(action_label)
        if thought and _show_reasoning_text():
            self._reasoning.commit_thought(thought)
    def _flush_thinking_block(self) -> None:
        """Print accumulated thoughts as a persistent dim block.

        Disabled - thinking now appears inline in the main response stream only.
        Live panel shows thinking during streaming, no need for separate
        static block at the bottom.
        """
        return
    def _stop_reasoning(self) -> None:
        """Flush any accumulated thoughts to static output, then stop the spinner.

        Always use this instead of calling _reasoning.stop() directly so that
        thoughts are never silently discarded mid-turn or at turn end.
        """
        self._flush_thinking_block()
        self._reasoning.stop()
    def _clear_streaming_preview(self) -> None:
        self._streaming_accumulated = ''
        self._streaming_final = False
        self._stream_wrap_width = None
        self._reasoning._streaming_line = ''
        self.refresh()
    @staticmethod
    def _tail_preview_text(
        content: str,
        *,
        max_width: int | None,
        max_lines: int,
        wrap_width: int | None = None,
    ) -> str:
        """Return a bottom-follow viewport of *content' constrained by wrapped lines."""
        if max_lines <= 0 or not content:
            return content

        if wrap_width is None:
            wrap_width = max(20, (max_width or 120) - 10)
        wrapped: list[str] = []
        for raw in content.splitlines() or ['']:
            if not raw:
                wrapped.append('')
                continue
            wrapped.extend(
                textwrap.wrap(
                    raw,
                    width=wrap_width,
                    replace_whitespace=False,
                    drop_whitespace=False,
                )
                or ['']
            )

        if len(wrapped) <= max_lines:
            return content

        tail = wrapped[-max_lines:]
        return '\n'.join(tail)
