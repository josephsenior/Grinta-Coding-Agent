"""Activity methods for CLIEventRenderer.

Activity cards & search results (summarize_search_results/_print_activity/_flush_pending_*).

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

class _EventRendererActivityMixin(CLIEventRenderer if TYPE_CHECKING else object):
    """Mixin class — see module docstring."""

    @staticmethod
    def _summarize_search_results_block(s: str) -> str:
        payload = _EventRendererActivityMixin._search_results_payload(s)
        lines = _EventRendererActivityMixin._search_result_lines(payload)
        if not lines:
            return 'No matches found.'
        if _EventRendererActivityMixin._search_head_says_no_match(lines):
            return 'No matches found.'
        return _EventRendererActivityMixin._format_match_count(lines)
    @staticmethod
    def _search_results_payload(s: str) -> str:
        m = re.search(
            r'<search_results>\s*(?P<payload>.*?)\s*</search_results>', s, re.S
        )
        return m.group('payload') if m else s
    @staticmethod
    def _search_result_lines(payload: str) -> list[str]:
        return [
            ln
            for ln in payload.splitlines()
            if ln.strip() and not ln.startswith('Error running ripgrep:')
        ]
    @staticmethod
    def _search_head_says_no_match(lines: list[str]) -> bool:
        head_blob = '\n'.join(lines[:5])
        return any(frag in head_blob for frag in _EventRendererActivityMixin._NO_MATCH_FRAGMENTS)
    _PLAIN_RG_LOCATION_LINE = re.compile(r'^[^:]+:\d+:')
    _RG_PATH_LINE_COLON = re.compile(r'^([^:]+):(\d+):(.*)$')
    @staticmethod
    def _linkify_ripgrep_line(line: str, *, accent_style: str) -> Text:
        """Hyperlink the file path in ``path:line:text`` ripgrep output."""
        m = _EventRendererActivityMixin._RG_PATH_LINE_COLON.match(line.strip())
        base = Style.parse(accent_style)
        if not m:
            return linkify_plain(  # type: ignore[unreachable]
                line,
                plain_style=accent_style,
                link_files=True,
                link_urls=False,
            )
        path_s, ln_s, rest = m.group(1), m.group(2), m.group(3)
        uri = file_uri_for_path(path_s)
        t = Text()
        if uri:
            t.append(path_s, style=base.update_link(uri))
        else:
            t.append(path_s, style=base)
        t.append(f':{ln_s}:{rest}', style=base)
        return t
    @staticmethod
    def _format_match_count(lines: list[str]) -> str:
        match_count = sum(
            1 for line in lines if _EventRendererActivityMixin._PLAIN_RG_LOCATION_LINE.match(line)
        ) or len(lines)
        return f'Found {match_count} match{"es" if match_count != 1 else ""}.'
    @staticmethod
    def _summarize_plain_match_lines(s: str) -> str | None:
        plain_lines = [ln for ln in s.splitlines() if ln.strip()]
        if not plain_lines:
            return None
        rg = _EventRendererActivityMixin._PLAIN_RG_LOCATION_LINE
        if not any(rg.match(ln) for ln in plain_lines[:5]):
            return None
        match_count = sum(1 for line in plain_lines if rg.match(line)) or len(
            plain_lines
        )
        return f'Found {match_count} match{"es" if match_count != 1 else ""}.'
    def _emit_activity_turn_header(self) -> None:
        if self._activity_turn_header_emitted:
            return
        self._activity_turn_header_emitted = True
        self._print_or_buffer(Padding(format_activity_turn_header(), pad=(0, 0, 1, 0)))
    def _print_activity(
        self,
        verb: str,
        detail: str | Text,
        stats: str | None = None,
        *,
        shell_rail: bool = False,
        title: str | None = None,
        badge_label: str | None = None,
    ) -> None:
        """Primary activity row plus optional dim stats (tool / file / shell)."""
        self._emit_activity_turn_header()
        if shell_rail:
            inner = format_activity_shell_block(
                verb,
                detail,
                secondary=stats,
                secondary_kind='neutral',
                title=title,
                badge_label=badge_label,
            )
        else:
            inner = format_activity_block(
                verb,
                detail,
                secondary=stats,
                secondary_kind='neutral',
                title=title,
                badge_label=badge_label,
            )
        self._print_or_buffer(Padding(inner, pad=ACTIVITY_BLOCK_BOTTOM_PAD))
    def _buffer_pending_activity(
        self,
        *,
        title: str,
        verb: str,
        detail: str,
        secondary: str | None = None,
        kind: str = 'generic',
        payload: dict[str, Any] | None = None,
        badge_label: str | None = None,
    ) -> None:
        self._flush_pending_activity_card()
        self._pending_activity_card = PendingActivityCard(
            title=title,
            verb=verb,
            detail=detail,
            secondary=secondary,
            kind=kind,
            payload=payload or {},
            badge_label=badge_label,
        )
    def _take_pending_activity_card(
        self, *expected_kinds: str
    ) -> PendingActivityCard | None:
        pending = self._pending_activity_card
        if pending is None:
            return None
        if expected_kinds and pending.kind not in expected_kinds:
            return None
        self._pending_activity_card = None
        return pending
    def _render_pending_activity_card(
        self,
        pending: PendingActivityCard,
        *,
        result_message: str | None = None,
        result_kind: str = 'neutral',
        extra_lines: list[Any] | None = None,
        badge_label: str | None = None,
    ) -> None:
        self._emit_activity_turn_header()
        inner = format_activity_block(
            pending.verb,
            pending.detail,
            secondary=pending.secondary,
            secondary_kind='neutral',
            result_message=result_message,
            result_kind=result_kind,
            extra_lines=extra_lines,
            title=pending.title,
            badge_label=badge_label or pending.badge_label,
        )
        self._print_or_buffer(Padding(inner, pad=ACTIVITY_BLOCK_BOTTOM_PAD))
    def _flush_pending_activity_card(self) -> None:
        pending = self._pending_activity_card
        if pending is None:
            return
        self._pending_activity_card = None
        self._render_pending_activity_card(pending)
    def _flush_pending_tool_cards(self) -> None:
        self._flush_pending_activity_card()
        self._flush_pending_shell_action()
    def _flush_pending_shell_action(self) -> None:
        """Print buffered command card without a result (fallback for orphaned CmdRunActions)."""
        if self._pending_shell_action is None:
            return
        verb, label = self._pending_shell_action
        title = self._pending_shell_title
        is_internal = self._pending_shell_is_internal
        self._pending_shell_action = None
        self._pending_shell_command = None
        self._pending_shell_title = None
        self._pending_shell_is_internal = False
        self._emit_activity_turn_header()  # not a duplicate
        if is_internal:
            inner = format_activity_block(
                verb, label, title=title or ACTIVITY_CARD_TITLE_SHELL
            )
        else:
            inner = format_activity_shell_block(verb, label)
        self._print_or_buffer(Padding(inner, pad=ACTIVITY_BLOCK_BOTTOM_PAD))
    def _print_tool_call(self, label: str) -> None:
        """Emit one legacy ground-truth tool row (``> label``)."""
        self._emit_activity_turn_header()
        self._print_or_buffer(
            Padding(
                format_ground_truth_tool_line(label),
                pad=ACTIVITY_BLOCK_BOTTOM_PAD,
            )
        )
