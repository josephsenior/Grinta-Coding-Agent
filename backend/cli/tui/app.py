"""Grinta TUI — Textual Application screen and widgets.

Clean minimal layout with proper widget architecture, unified activity cards,
and incremental transcript updates.
"""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import contextlib
import difflib
import logging
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import pyperclip
from rich.console import Group
from rich.markdown import Markdown
from rich.rule import Rule
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.message import Message
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Input,
    Label,
    ListItem,
    ListView,
    Select,
    Static,
    TextArea,
)

_tui_logger = logging.getLogger('grinta.tui')
_tui_logger.setLevel(logging.DEBUG)


def _bounded_int_env(name: str, default: int, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(minimum, int(raw))
    except (TypeError, ValueError):
        _tui_logger.warning('Invalid %s=%r; using default %d', name, raw, default)
        return default


_TUI_PENDING_EVENT_LIMIT = _bounded_int_env(
    'GRINTA_TUI_PENDING_EVENT_LIMIT',
    default=5000,
    minimum=100,
)
_TUI_HISTORY_RENDER_LIMIT = _bounded_int_env(
    'GRINTA_TUI_HISTORY_RENDER_LIMIT',
    default=2000,
    minimum=200,
)
_FILE_DIFF_AUTO_COLLAPSE_LINES = _bounded_int_env(
    'GRINTA_TUI_FILE_DIFF_AUTO_COLLAPSE_LINES',
    default=80,
    minimum=20,
)

from backend.cli._event_renderer.panels import task_panel_signature
from backend.cli._event_renderer.text_utils import (
    sanitize_visible_transcript_text,
)
from backend.cli._event_renderer.unified_renderer import (
    ActivityCard,
    ActivityRenderer,
)
from backend.cli.config_manager import AppConfig
from backend.cli.hud import HUDBar
from backend.cli.reasoning_display import ReasoningDisplay
from backend.cli.theme import (
    NAVY_BORDER,
    NAVY_BRAND,
    NAVY_ERROR,
    NAVY_GREEN_ACCENT,
    NAVY_READY,
    NAVY_RED_ACCENT,
    NAVY_TEXT_DIM,
    NAVY_TEXT_MUTED,
    NAVY_TEXT_PRIMARY,
    NAVY_TEXT_SECONDARY,
    NAVY_TEXT_TERTIARY,
    NAVY_WAITING,
    NAVY_YELLOW_ACCENT,
)
from backend.cli.transcript import strip_tool_result_validation_annotations
from backend.cli.tui.widgets.activity_card import (
    encode_diff_line,
    encode_split_diff_line,
)
from backend.cli.tui.widgets.dialogs import ModalDialog
from backend.core.bootstrap.agent_control_loop import run_agent_until_done
from backend.core.bootstrap.main import (
    create_agent,
    create_registry_and_conversation_stats,
)
from backend.core.bootstrap.setup import (
    create_controller,
    create_memory,
    create_runtime,
    generate_sid,
)
from backend.core.enums import AgentState, EventSource
from backend.core.interaction_modes import (
    AGENT_MODE,
    CHAT_MODE,
    PLAN_MODE,
    VISIBLE_INTERACTION_MODES,
    is_chat_mode,
    normalize_interaction_mode,
)
from backend.core.logger import app_logger as logger
from backend.core.workspace_resolution import resolve_cli_workspace_directory
from backend.ledger import EventStream, EventStreamSubscriber
from backend.ledger.action import (
    AgentThinkAction,
    BrowseInteractiveAction,
    BrowserToolAction,
    ChangeAgentStateAction,
    ClarificationRequestAction,
    CmdRunAction,
    CondensationAction,
    DelegateTaskAction,
    EscalateToHumanAction,
    FileEditAction,
    FileReadAction,
    FileWriteAction,
    LspQueryAction,
    MCPAction,
    MessageAction,
    NullAction,
    PlaybookFinishAction,
    ProposalAction,
    RecallAction,
    StreamingChunkAction,
    TaskTrackingAction,
    TerminalInputAction,
    TerminalReadAction,
    TerminalRunAction,
    UncertaintyAction,
)
from backend.ledger.observation import (
    AgentCondensationObservation,
    AgentStateChangedObservation,
    AgentThinkObservation,
    BrowserScreenshotObservation,
    CmdOutputObservation,
    DelegateTaskObservation,
    ErrorObservation,
    FileDownloadObservation,
    FileEditObservation,
    FileReadObservation,
    FileWriteObservation,
    LspQueryObservation,
    MCPObservation,
    NullObservation,
    RecallFailureObservation,
    RecallObservation,
    ServerReadyObservation,
    StatusObservation,
    SuccessObservation,
    TaskTrackingObservation,
    TerminalObservation,
    UserRejectObservation,
)
from backend.persistence import get_file_store  # noqa: E402


def _rich_text(text: str) -> Text:
    """Convert text with potential ANSI and markup to a Rich Text object."""
    return Text.from_ansi(text)


def _strip_ansi(text: str) -> str:
    """Strip all ANSI escape sequences from text using Rich's parser."""
    return _rich_text(text).plain


_TERMINAL_MOUSE_REPORT_RE = re.compile(r'(?:\x1b)?\[(?:<)?\d{1,7};\d{1,7};\d{1,7}[mM]')
_TERMINAL_ORPHAN_PARAM_TOKEN_RE = re.compile(
    r'(?:^|(?<=[^\w]))(?:\[?\d+(?:;\d+){2,}[OI]?_){2,}'
)


def _strip_terminal_control_literals(text: str) -> str:
    """Remove terminal mouse reports that some consoles leak as input text."""
    if not text:
        return text
    text = _TERMINAL_MOUSE_REPORT_RE.sub('', text)
    return _TERMINAL_ORPHAN_PARAM_TOKEN_RE.sub('', text)


def _sanitize_terminal_display_text(text: str) -> str:
    """Strip terminal control traffic before rendering PTY output in Textual."""
    if not text:
        return text
    return _strip_terminal_control_literals(_strip_ansi(text))


def _render_thinking_with_diff(text: str) -> Text:
    """Render thinking text as plain muted text."""
    return Text(text or '', style='dim lightgray')


def _count_text_lines(text: str) -> int:
    """Count visible lines in a text blob."""
    return text.count('\n') + 1 if text else 0


def _format_diff_summary(added: int, removed: int) -> str | None:
    """Format a compact add/remove summary for file edit cards."""
    parts: list[str] = []
    if added:
        parts.append(f'+{added}')
    if removed:
        parts.append(f'-{removed}')
    return ' · '.join(parts) if parts else None


def _encode_unified_diff_text(diff_text: str, *, max_lines: int = 200) -> str | None:
    """Encode a unified diff into full-width TUI diff rows."""
    if not diff_text:
        return None

    lines = diff_text.splitlines()
    encoded: list[str] = []
    visible_lines = lines[:max_lines]
    for line in visible_lines:
        if line.startswith(('---', '+++', '@@')):
            kind = 'ctx'
        elif line.startswith('+'):
            kind = 'add'
        elif line.startswith('-'):
            kind = 'rem'
        else:
            kind = 'ctx'
        encoded.append(encode_diff_line(line or ' ', kind))

    remaining = len(lines) - len(visible_lines)
    if remaining > 0:
        encoded.append(encode_diff_line(f'... {remaining} more diff lines', 'ctx'))

    return '\n'.join(encoded) if encoded else None


def _split_combined_diff(diff_text: str) -> list[tuple[str, str]]:
    """Split a combined unified diff (multi-file) into per-file (path, diff_text) pairs.

    Standard unified diff separates files with ``--- a/path`` / ``+++ b/b/path``
    headers. This function splits on those boundaries.
    """
    per_file: list[tuple[str, str]] = []
    current_lines: list[str] = []
    current_path: str | None = None

    for line in diff_text.splitlines():
        if line.startswith('--- '):
            if current_path and current_lines:
                per_file.append((current_path, '\n'.join(current_lines)))
            current_lines = [line]
            current_path = None
        elif line.startswith('+++ ') and current_path is None:
            raw = line[4:].strip()
            if raw.startswith('b/'):
                raw = raw[2:]
            if raw and raw != '/dev/null':
                current_path = raw
            current_lines.append(line)
        else:
            current_lines.append(line)

    if current_path and current_lines:
        per_file.append((current_path, '\n'.join(current_lines)))

    return per_file


def _numbered_diff_line(kind: str, line_no: int, line: str, pad: int) -> str:
    prefix = {'add': '+', 'rem': '-'}.get(kind, ' ')
    return f'{prefix}{line_no:>{pad}}|{line}'


def _encode_split_diff_contents(
    old_content: str,
    new_content: str,
    *,
    max_lines: int = 200,
    n_context_lines: int = 3,
) -> str | None:
    """Encode before/after text into aligned two-pane TUI diff rows."""
    old_lines = old_content.split('\n')
    new_lines = new_content.split('\n')
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    encoded: list[str] = []
    for group_idx, group in enumerate(matcher.get_grouped_opcodes(n_context_lines)):
        if group_idx > 0:
            encoded.append(encode_split_diff_line('...', '...', 'ctx', 'ctx'))
        max_line_no = max((op[2] for op in group), default=0)
        max_line_no = max(max_line_no, max((op[4] for op in group), default=0))
        pad = max(1, len(str(max_line_no)))
        for tag, i1, i2, j1, j2 in group:
            for row in _split_diff_opcode_rows(
                tag,
                old_lines,
                new_lines,
                i1,
                i2,
                j1,
                j2,
                pad,
            ):
                if len(encoded) >= max_lines:
                    encoded.append(
                        encode_split_diff_line(
                            '... more diff rows',
                            '... more diff rows',
                            'ctx',
                            'ctx',
                        )
                    )
                    return '\n'.join(encoded)
                encoded.append(
                    encode_split_diff_line(
                        row[0],
                        row[1],
                        row[2],
                        row[3],
                    )
                )
    return '\n'.join(encoded) if encoded else None


def _split_diff_opcode_rows(
    tag: str,
    old_lines: list[str],
    new_lines: list[str],
    i1: int,
    i2: int,
    j1: int,
    j2: int,
    pad: int,
) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    if tag == 'equal':
        for offset, old_index in enumerate(range(i1, i2)):
            new_index = j1 + offset
            rows.append(
                (
                    _numbered_diff_line(
                        'ctx', old_index + 1, old_lines[old_index], pad
                    ),
                    _numbered_diff_line(
                        'ctx', new_index + 1, new_lines[new_index], pad
                    ),
                    'ctx',
                    'ctx',
                )
            )
        return rows
    if tag == 'delete':
        for old_index in range(i1, i2):
            rows.append(
                (
                    _numbered_diff_line(
                        'rem', old_index + 1, old_lines[old_index], pad
                    ),
                    '',
                    'rem',
                    'ctx',
                )
            )
        return rows
    if tag == 'insert':
        for new_index in range(j1, j2):
            rows.append(
                (
                    '',
                    _numbered_diff_line(
                        'add', new_index + 1, new_lines[new_index], pad
                    ),
                    'ctx',
                    'add',
                )
            )
        return rows
    if tag == 'replace':
        old_count = i2 - i1
        new_count = j2 - j1
        for offset in range(max(old_count, new_count)):
            old_index = i1 + offset
            new_index = j1 + offset
            left = (
                _numbered_diff_line('rem', old_index + 1, old_lines[old_index], pad)
                if offset < old_count
                else ''
            )
            right = (
                _numbered_diff_line('add', new_index + 1, new_lines[new_index], pad)
                if offset < new_count
                else ''
            )
            rows.append(
                (
                    left,
                    right,
                    'rem' if left else 'ctx',
                    'add' if right else 'ctx',
                )
            )
    return rows


def _join_secondary_parts(*parts: str | None) -> str | None:
    """Join compact secondary labels while skipping blanks."""
    values = [part for part in parts if part]
    return ' · '.join(values) if values else None


def _extract_tagged_block(content: str, start_tag: str, end_tag: str) -> str | None:
    """Return the first non-empty tagged block from an observation content string."""
    start = content.find(start_tag)
    if start == -1:
        return None
    body_start = start + len(start_tag)
    end = content.find(end_tag, body_start)
    if end == -1:
        return None
    block = content[body_start:end].strip()
    return block or None


def _should_collapse_file_diff(diff_text: str) -> bool:
    return len(diff_text.splitlines()) > _FILE_DIFF_AUTO_COLLAPSE_LINES


# ── Widget classes ────────────────────────────────────────────────────────


class InfoSidebar(VerticalScroll):
    """Sidebar for Mission Control info (Tasks, MCPs, Skills)."""

    def update(self, *args: Any, **kwargs: Any) -> None:
        """No-op update for backward compatibility and test mock compatibility."""
        pass


class Transcript(VerticalScroll):
    """Scrollable conversation transcript container with auto-scroll awareness."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._user_scrolled_away = False

    def compose(self) -> ComposeResult:
        yield Static(id='scroll-badge', classes='-hidden')

    def on_mount(self) -> None:
        self._scroll_badge = self.query_one('#scroll-badge', Static)

    def _was_at_bottom(self, threshold: int = 3) -> bool:
        return self.max_scroll_y - self.scroll_y <= threshold

    def on_scroll(self, _event: Widget.Scroll) -> None:
        if not self._scroll_badge:
            return
        if self._was_at_bottom():
            if self._user_scrolled_away:
                self._user_scrolled_away = False
                self._scroll_badge.add_class('-hidden')
        else:
            if not self._user_scrolled_away:
                self._user_scrolled_away = True
                self._scroll_badge.remove_class('-hidden')

    def append_widget(self, widget: Static | Container) -> None:
        """Mount a widget and auto-scroll unless user scrolled up."""
        widget.styles.offset = (0, -1)
        self.mount(widget)
        try:
            widget.animate('offset', (0, 0), duration=0.2)
        except Exception:
            widget.styles.offset = (0, 0)
        if not self._user_scrolled_away:
            self.scroll_end(animate=False)

    def write(self, renderable: Any) -> None:
        """Compatibility method for RichLog interface."""
        self.append_widget(Static(renderable))

    def force_scroll_end(self) -> None:
        """Scroll to bottom regardless of user scroll state."""
        self._user_scrolled_away = False
        self._scroll_badge.add_class('-hidden')
        self.scroll_end(animate=False)

    def clear(self) -> None:
        """Compatibility method for RichLog interface."""
        self.remove_children()
        self._user_scrolled_away = False
        self.mount(Static('', id='scroll-badge', classes='-hidden'))
        self._scroll_badge = self.query_one('#scroll-badge', Static)


_WELCOME_SUGGESTIONS = [
    'Explain this codebase',
    'Analyze this repository and produce an implementation plan',
    'Plan a safe refactor of this module',
    'Run tests and fix failures',
    'Inspect the project and propose a testing strategy',
]

_WELCOME_FIGLET_FALLBACK = (
    '  ____ ____  ___ _   _ _____  _ ',
    ' / ___|  _ \\|_ _| \\ | |_   _|/ \\',
    '| |  _| |_) || ||  \\| | | | / _ \\',
    '| |_| |  _ < | || |\\  | | |/ ___ \\',
    ' \\____|_| \\_\\___|_| \\_| |_/_/   \\_\\',
)

_WELCOME_FIGLET_CACHE: str | None = None


def _get_welcome_figlet() -> str:
    global _WELCOME_FIGLET_CACHE
    if _WELCOME_FIGLET_CACHE is not None:
        return _WELCOME_FIGLET_CACHE
    try:
        import pyfiglet as _pyfiglet

        _WELCOME_FIGLET_CACHE = _pyfiglet.figlet_format('GRINTA', font='slant').rstrip(
            '\n'
        )
    except Exception:
        _WELCOME_FIGLET_CACHE = '\n'.join(_WELCOME_FIGLET_FALLBACK)
    return _WELCOME_FIGLET_CACHE


class WelcomeWidget(Vertical):
    """Empty-state welcome panel with interactive task suggestions."""

    def __init__(
        self,
        *,
        header: str = 'Describe a task for the current workspace.',
        subheader: str = 'Use up/down + Enter, or click a starter task.',
        suggestions: list[str] | None = None,
        suggestion_details: list[str] | None = None,
        callback_name: str = '_handle_welcome_click',
        show_logo: bool = True,
    ) -> None:
        super().__init__()
        self._header_text = header
        self._subheader_text = subheader
        self._suggestions = (
            list(suggestions) if suggestions is not None else list(_WELCOME_SUGGESTIONS)
        )
        self._suggestion_details = list(
            suggestion_details or [''] * len(self._suggestions)
        )
        if len(self._suggestion_details) < len(self._suggestions):
            self._suggestion_details.extend(
                [''] * (len(self._suggestions) - len(self._suggestion_details))
            )
        self._callback_name = callback_name
        self._show_logo = show_logo

    def compose(self) -> ComposeResult:
        if self._show_logo:
            yield Static('', id='welcome-logo')
            yield Static(
                '[#c8d4e8 bold]Autonomous coding agent runtime[/]',
                id='welcome-slogan',
            )
            yield Static(
                '[#6f83aa italic]Pure grit.[/]',
                id='welcome-tagline',
            )
            yield Static(
                '[#6f83aa]Describe a task to inspect, plan, edit, test, or refactor your project.[/]',
                id='welcome-instruction',
            )
        else:
            yield Static(self._header_text, id='welcome-header')
            yield Static(self._subheader_text, id='welcome-subheader')
        for _text in self._suggestions:
            yield Static('', classes='welcome-item')

    def on_mount(self) -> None:
        if self._show_logo:
            width = self.screen.size.width
            logo_static = self.query_one('#welcome-logo', Static)
            if width >= 80:
                logo_static.update(_get_welcome_figlet())
            else:
                logo_static.update('[#6f83aa bold]GRINTA[/]')
        self._selected = 0
        self._items = list(self.query('.welcome-item'))
        self._cascade_timers: list[Any] = []
        for item in self._items:
            item.display = False
        self._cascade(0)

    def on_unmount(self) -> None:
        for timer in self._cascade_timers:
            try:
                timer.stop()
            except Exception:
                pass
        self._cascade_timers.clear()

    def _cascade(self, idx: int) -> None:
        if idx >= len(self._items):
            self._highlight(0)
            return
        self._items[idx].display = True
        timer = self.set_timer(0.15, lambda i=idx: self._cascade(i + 1))
        self._cascade_timers.append(timer)

    def _highlight(self, idx: int) -> None:
        for i, item in enumerate(self._items):
            item.update(self._render_suggestion(i, selected=i == idx))
        self._selected = idx

    def _render_suggestion(self, index: int, *, selected: bool) -> str:
        icon = '▶' if selected else '▸'
        label_style = '#5eead4 bold' if selected else '#8ea2c8'
        detail = (self._suggestion_details[index] or '').strip()
        text = f'  {icon} [{label_style}]{self._suggestions[index]}[/]'
        if detail:
            text += f'\n    [#6b7280]{detail}[/]'
        return text

    def highlight_prev(self) -> None:
        if self._selected > 0:
            self._highlight(self._selected - 1)

    def highlight_next(self) -> None:
        if self._selected < len(self._suggestions) - 1:
            self._highlight(self._selected + 1)

    def select_current(self) -> str | None:
        if 0 <= self._selected < len(self._suggestions):
            return self._suggestions[self._selected]
        return None

    def on_click(self, event: events.Click) -> None:
        target = event.widget
        if target is None:
            return
        for i, item in enumerate(self._items):
            if target is item:
                self._highlight(i)
                text = self.select_current()
                if text:
                    event.prevent_default()
                    event.stop()
                    screen = getattr(self, 'screen', None)
                    if screen and hasattr(screen, self._callback_name):
                        getattr(screen, self._callback_name)(text)
                break


class CommunicatePromptWidget(WelcomeWidget):
    """Interactive transcript prompt for communicate_with_user."""

    def __init__(
        self,
        title: str,
        prompt: str,
        *,
        context: str = '',
        details: list[str] | None = None,
        options: list[tuple[str, str, str, bool]] | None = None,
    ) -> None:
        details_text = ' '.join(details or [])
        helper = 'Use up/down + Enter, or click an option.'
        parts = [part for part in (context, details_text, helper) if part]
        super().__init__(
            header=f'{title}: {prompt}',
            subheader=' '.join(parts) if parts else helper,
            suggestions=[
                option[0] + (' (recommended)' if option[3] else '')
                for option in (options or [])
            ],
            suggestion_details=[option[2] for option in (options or [])],
            callback_name='_handle_communicate_selection',
            show_logo=False,
        )
        self._values = [option[1] for option in (options or [])]
        self._active = bool(self._values)
        self._submitted: int | None = None

    def on_mount(self) -> None:
        self._selected = 0
        self._items = list(self.query('.welcome-item'))
        self._cascade_timers = []
        for item in self._items:
            item.display = True
        if self._items:
            self._highlight(0)

    @property
    def has_options(self) -> bool:
        return bool(self._values)

    @property
    def current_value(self) -> str | None:
        if not self._values:
            return None
        return self._values[self._selected]

    def set_active(self, active: bool) -> None:
        self._active = active and self.has_options

    def mark_submitted(self, index: int | None = None) -> None:
        if not self._values:
            return
        self._submitted = self._selected if index is None else index
        self._active = False

    def action_submit_option(self) -> None:
        if not self._active or not self._values:
            return
        self.mark_submitted(self._selected)
        screen = getattr(self, 'screen', None)
        if screen and hasattr(screen, '_handle_communicate_selection'):
            screen._handle_communicate_selection(
                self._values[self._selected], card=self
            )

    def on_click(self, event: events.Click) -> None:
        target = event.widget
        if target is None:
            return
        for i, item in enumerate(self._items):
            if target is item:
                self._highlight(i)
                self.action_submit_option()
                event.prevent_default()
                event.stop()
                return


class InputBar(Horizontal):
    """Bottom input row with border and prompt."""


class PromptTextArea(TextArea):
    """Input area that routes arrow navigation to welcome suggestions when idle."""

    def _on_paste(self, event: events.Paste) -> None:
        """Handle paste events by reading the system clipboard directly.

        In most terminals (Windows Terminal, etc.), Ctrl+V is intercepted and
        forwarded as a bracketed paste event. For large clipboard content, the
        terminal/PTY can silently truncate the data mid-stream — the paste event
        arrives with incomplete or empty text, so the user sees nothing.

        Bypass this by reading the system clipboard directly via pyperclip.
        Falls back to the paste-event text when pyperclip is unavailable.
        """
        if self.read_only:
            return
        try:
            clipboard = pyperclip.paste()
        except Exception:
            clipboard = event.text
        event.prevent_default()
        if result := self._replace_via_keyboard(clipboard, *self.selection):
            self.move_cursor(result.end_location)

    def action_paste(self) -> None:
        """Paste from system clipboard directly.

        This handles the case where Ctrl+V is NOT intercepted by the terminal
        and reaches the app as a key binding.
        """
        if self.read_only:
            return
        try:
            clipboard = pyperclip.paste()
        except Exception:
            return super().action_paste()
        if result := self._replace_via_keyboard(clipboard, *self.selection):
            self.move_cursor(result.end_location)

    def on_key(self, event: events.Key) -> None:
        screen = getattr(self, 'screen', None)
        if event.key in {'up', 'down'} and bool(screen) and not self.text.strip():
            if getattr(screen, '_welcome_visible', False):
                if event.key == 'up' and hasattr(screen, 'action_focus_prev_card'):
                    screen.action_focus_prev_card()
                elif event.key == 'down' and hasattr(screen, 'action_focus_next_card'):
                    screen.action_focus_next_card()
                event.prevent_default()
                event.stop()
                return
            if hasattr(
                screen, '_handle_communicate_navigation'
            ) and screen._handle_communicate_navigation(event.key):
                event.prevent_default()
                event.stop()
                return


class HUD(Vertical):
    """Multi-line status bar at the very bottom."""

    def compose(self) -> ComposeResult:
        with Horizontal(id='hud-line-2-row'):
            yield Label('[#7a6a4a]Mode:[/]', id='hud-label-mode')
            yield Select(
                [(c.capitalize(), c) for c in VISIBLE_INTERACTION_MODES],
                value=AGENT_MODE,
                id='hud-mode',
                allow_blank=False,
            )
            yield Label('[#6a7a9a]Autonomy:[/]', id='hud-label-autonomy')
            yield Select(
                [(c.capitalize(), c) for c in ('conservative', 'balanced', 'full')],
                value='balanced',
                id='hud-autonomy',
                allow_blank=False,
            )
            yield Label(id='hud-line-2')
        yield Label(id='hud-line-1')


class RendererDrainRequested(Message):
    """Message requesting the screen to drain queued renderer events."""


class ConfirmWidget(Widget):
    """Inline confirmation bar that appears when the agent needs approval.

    Renders as a single compact row inside the main page rather than
    a blocking modal overlay.
    """

    DEFAULT_CSS = """
    ConfirmWidget {
        dock: top;
        height: auto;
        max-height: 5;
        background: #0f1729;
        border-top: tall #1a2744;
        border-bottom: tall #1a2744;
        padding: 0 2;
        display: none;
    }
    ConfirmWidget.-visible {
        display: block;
    }
    ConfirmWidget #confirm-bar {
        layout: horizontal;
        height: auto;
        align: left middle;
    }
    ConfirmWidget #confirm-info {
        width: 1fr;
        height: auto;
        color: #cbd5e1;
        padding: 0 1;
    }
    ConfirmWidget #confirm-actions {
        height: auto;
        dock: right;
        margin-left: 2;
    }
    ConfirmWidget #confirm-actions Button {
        min-width: 0;
        width: auto;
        margin-left: 1;
        height: 1;
    }
    ConfirmWidget Button.-primary {
        background: #2563eb;
        color: #ffffff;
    }
    ConfirmWidget Button.-default {
        background: #1e293b;
        color: #94a3b8;
    }
    ConfirmWidget .confirm-label {
        color: #64748b;
    }
    ConfirmWidget .confirm-type {
        color: #7dd3fc;
        text-style: bold;
    }
    ConfirmWidget .confirm-target {
        color: #e2e8f0;
        text-style: italic;
    }
    ConfirmWidget .confirm-risk-low {
        color: #4ade80;
    }
    ConfirmWidget .confirm-risk-medium {
        color: #fbbf24;
    }
    ConfirmWidget .confirm-risk-high {
        color: #f87171;
    }
    ConfirmWidget .confirm-risk-unknown {
        color: #94a3b8;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._decision_event: asyncio.Event = asyncio.Event()
        self._decision: str | None = None
        self._options: list[tuple[str, str]] = []
        self._recommended: int | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id='confirm-bar'):
            yield Static('', id='confirm-info')
            with Horizontal(id='confirm-actions'):
                pass

    def configure(
        self,
        action_type: str,
        risk_label: str,
        risk_class: str,
        target: str,
        options: list[tuple[str, str]],
        recommended: int | None = None,
    ) -> None:
        """Populate the confirmation bar with action details."""
        if target:
            truncated = target if len(target) <= 50 else target[:47] + '...'
            info = (
                f'[bold cyan]{action_type}[/] '
                f'[dim]→[/] '
                f'[white]{truncated}[/]  '
                f'[{risk_class}]{risk_label}[/]'
            )
        else:
            info = f'[bold cyan]{action_type}[/]  [{risk_class}]{risk_label}[/]'

        info_static = self.query_one('#confirm-info', Static)
        info_static.update(info)

        actions = self.query_one('#confirm-actions', Horizontal)
        actions.remove_children()
        self._options = options
        self._recommended = recommended
        for i, (key, label) in enumerate(options):
            btn = Button(
                label,
                id=f'confirm-{key}',
                variant='primary' if i == (recommended or 0) else 'default',
            )
            actions.mount(btn)

    def show(self) -> None:
        self.add_class('-visible')
        self._decision = None
        self._decision_event.clear()

    def hide(self) -> None:
        self.remove_class('-visible')
        self._decision = None

    async def wait_for_decision(self) -> str | None:
        """Block until the user clicks a button."""
        await self._decision_event.wait()
        return self._decision

    def on_button_pressed(self, event: Button.Pressed) -> None:
        for key, _label in self._options:
            if event.button.id == f'confirm-{key}':
                self._decision = key
                self._decision_event.set()
                self.hide()
                return


class GrintaConfirmDialog(ModalDialog[str | None]):
    """Modal confirmation dialog for one-off confirmations."""

    DEFAULT_CSS = """
    GrintaConfirmDialog > #dialog-container {
        width: 50;
    }
    """

    def __init__(
        self,
        title: str,
        body: str,
        options: list[tuple[str, str]],
        recommended: int | None = None,
    ) -> None:
        super().__init__()
        self._dialog_title = title
        self._dialog_body = body
        self._options = options
        self._recommended = recommended

    def compose(self) -> ComposeResult:
        with Vertical(id='dialog-container'):
            yield Label(f'[bold]{self._dialog_title}[/]', id='dialog-title')
            yield Static(self._dialog_body, id='dialog-body')
            with Horizontal(id='dialog-buttons'):
                for i, (key, label) in enumerate(self._options):
                    yield Button(
                        label,
                        id=f'confirm-{key}',
                        variant='primary'
                        if i == (self._recommended or 0)
                        else 'default',
                    )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        for key, _label in self._options:
            if event.button.id == f'confirm-{key}':
                self.dismiss(key)
                return


class GrintaHelpDialog(ModalDialog[None]):
    """Dedicated help and shortcuts modal."""

    def compose(self) -> ComposeResult:
        help_markup = (
            f'[{NAVY_TEXT_SECONDARY}]/help[/]      [{NAVY_TEXT_TERTIARY}]Show help and shortcuts[/]\n'
            f'[{NAVY_TEXT_SECONDARY}]/clear[/]     [{NAVY_TEXT_TERTIARY}]Clear transcript[/]\n'
            f'[{NAVY_TEXT_SECONDARY}]/settings[/]  [{NAVY_TEXT_TERTIARY}]Open runtime settings[/]\n'
            f'[{NAVY_TEXT_SECONDARY}]/sessions[/]  [{NAVY_TEXT_TERTIARY}]Browse and resume sessions[/]\n'
            f'[{NAVY_TEXT_SECONDARY}]/resume[/]    [{NAVY_TEXT_TERTIARY}]Resume a session directly[/]\n'
            f'[{NAVY_TEXT_SECONDARY}]/quit[/]      [{NAVY_TEXT_TERTIARY}]Exit Grinta[/]\n\n'
            f'[{NAVY_TEXT_SECONDARY}]Ctrl+C[/]     [{NAVY_TEXT_TERTIARY}]Interrupt agent or copy[/]\n'
            f'[{NAVY_TEXT_SECONDARY}]Ctrl+B[/]     [{NAVY_TEXT_TERTIARY}]Toggle sidebar[/]\n'
            f'[{NAVY_TEXT_SECONDARY}]Ctrl+L[/]     [{NAVY_TEXT_TERTIARY}]Clear transcript[/]\n'
            f'[{NAVY_TEXT_SECONDARY}]Ctrl+Space[/] [{NAVY_TEXT_TERTIARY}]Autocomplete slash commands[/]\n'
            f'[{NAVY_TEXT_SECONDARY}]PageUp/Down[/] [{NAVY_TEXT_TERTIARY}]Scroll transcript[/]\n'
            f'[{NAVY_TEXT_SECONDARY}]Home/End[/]   [{NAVY_TEXT_TERTIARY}]Jump transcript[/]'
        )
        with Vertical(id='dialog-container'):
            yield Label('[bold]Help[/]', id='dialog-title')
            yield Static(
                f'[{NAVY_TEXT_MUTED}]Use the transcript for evidence and the pinned strips for runtime state.[/]\n\n'
                f'{help_markup}',
                id='help-body',
            )
            with Horizontal(id='dialog-buttons'):
                yield Button('Close', id='help-close', variant='primary')

    def on_mount(self) -> None:
        self.query_one('#help-close', Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'help-close':
            self.dismiss(None)


class GrintaAddSkillDialog(ModalDialog[dict[str, str] | None]):
    """Dialog to create a custom skill dynamically."""

    BINDINGS = [
        *ModalDialog.BINDINGS,
        Binding('ctrl+s', 'save', 'Save', show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id='dialog-container'):
            yield Label('[bold]Add Custom Skill[/]', id='dialog-title')
            yield Label('Skill Name (e.g. react_best_practices)', classes='field-label')
            yield Input(id='skill-name')
            yield Label('Instructions (Markdown)', classes='field-label')
            yield TextArea(id='skill-content')
            yield Label('', id='dialog-feedback')
            with Horizontal(id='dialog-buttons'):
                yield Button('Save', id='settings-save', variant='primary')
                yield Button('Cancel', id='settings-cancel')

    def on_mount(self) -> None:
        self.query_one('#skill-name', Input).focus()

    def action_save(self) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'settings-save':
            self._submit()
        elif event.button.id == 'settings-cancel':
            self.dismiss(None)

    def _submit(self) -> None:
        name = self.query_one('#skill-name', Input).value.strip()
        content = self.query_one('#skill-content', TextArea).text.strip()
        if not name:
            self.query_one('#dialog-feedback', Label).update(
                '[#f05757]Skill name required.[/]'
            )
            return
        if not content:
            self.query_one('#dialog-feedback', Label).update(
                '[#f05757]Content required.[/]'
            )
            return
        self.dismiss({'name': name, 'content': content})


class GrintaAddMCPDialog(ModalDialog[dict[str, str] | None]):
    """Dialog to add an MCP Server."""

    BINDINGS = [
        *ModalDialog.BINDINGS,
        Binding('ctrl+s', 'save', 'Save', show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id='dialog-container'):
            yield Label('[bold]Add MCP Server[/]', id='dialog-title')
            yield Label('Server Name', classes='field-label')
            yield Input(id='mcp-name')
            yield Label(
                'Command or URL (e.g. npx -y @modelcontextprotocol/server-postgres)',
                classes='field-label',
            )
            yield Input(id='mcp-command')
            yield Label('', id='dialog-feedback')
            with Horizontal(id='dialog-buttons'):
                yield Button('Save', id='settings-save', variant='primary')
                yield Button('Cancel', id='settings-cancel')

    def on_mount(self) -> None:
        self.query_one('#mcp-name', Input).focus()

    def action_save(self) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'settings-save':
            self._submit()
        elif event.button.id == 'settings-cancel':
            self.dismiss(None)

    def _submit(self) -> None:
        name = self.query_one('#mcp-name', Input).value.strip()
        cmd = self.query_one('#mcp-command', Input).value.strip()
        if not name or not cmd:
            self.query_one('#dialog-feedback', Label).update(
                '[#f05757]Name and command required.[/]'
            )
            return
        self.dismiss({'name': name, 'command': cmd})


class GrintaSettingsDialog(ModalDialog[dict[str, Any] | None]):
    """Native settings modal for full-screen TUI."""

    BINDINGS = [
        *ModalDialog.BINDINGS,
        Binding('ctrl+s', 'save', 'Save', show=False),
    ]

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self._config = config

    def compose(self) -> ComposeResult:
        from backend.cli.config_manager import get_current_model, get_masked_api_key

        current_model = get_current_model(self._config)
        masked_key = get_masked_api_key(self._config)
        raw_budget = getattr(self._config, 'max_budget_per_task', None)
        budget_value = '' if raw_budget is None else f'{float(raw_budget):g}'
        icons_enabled = bool(getattr(self._config, 'cli_tool_icons', True))

        with Vertical(id='dialog-container'):
            yield Label('[bold]Settings[/]', id='dialog-title')
            yield Label(f'Current API key: {masked_key}', id='settings-current-key')
            yield Label('Model', classes='field-label')
            yield Input(value=current_model, id='settings-model')
            yield Label(
                'API key (leave blank to keep current key)', classes='field-label'
            )
            yield Input(password=True, id='settings-api-key')
            yield Label(
                'Budget per task (blank/unlimited to keep unlimited)',
                classes='field-label',
            )
            yield Input(value=budget_value, id='settings-budget')
            yield Checkbox(
                'Show tool icons in activity cards',
                value=icons_enabled,
                id='settings-icons',
            )
            yield Label('', id='dialog-feedback')
            with Horizontal(id='dialog-buttons'):
                yield Button('Save', id='settings-save', variant='primary')
                yield Button('Cancel', id='settings-cancel')

    def on_mount(self) -> None:
        self.query_one('#settings-model', Input).focus()

    def action_save(self) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'settings-save':
            self._submit()
            return
        if event.button.id == 'settings-cancel':
            self.dismiss(None)

    def _set_feedback(self, message: str, *, error: bool = False) -> None:
        style = NAVY_ERROR if error else NAVY_READY
        self.query_one('#dialog-feedback', Label).update(f'[{style}]{message}[/]')

    def _submit(self) -> None:
        model = self.query_one('#settings-model', Input).value.strip()
        api_key = self.query_one('#settings-api-key', Input).value.strip()
        budget_raw = self.query_one('#settings-budget', Input).value.strip()
        icons_enabled = self.query_one('#settings-icons', Checkbox).value

        if not model:
            self._set_feedback('Model is required.', error=True)
            return

        budget_value: float | None = None
        if budget_raw and budget_raw.lower() not in {'unlimited', 'none'}:
            try:
                budget_value = float(budget_raw)
            except ValueError:
                self._set_feedback(
                    'Budget must be numeric, unlimited, or empty.', error=True
                )
                return
            if budget_value < 0:
                self._set_feedback('Budget cannot be negative.', error=True)
                return

        self.dismiss(
            {
                'model': model,
                'api_key': api_key,
                'budget': budget_value,
                'icons': bool(icons_enabled),
            }
        )


class GrintaSessionsDialog(ModalDialog[str | None]):
    """Native sessions manager for full-screen TUI."""

    DEFAULT_CSS = """
    GrintaSessionsDialog > #dialog-container {
        max-height: 40;
    }
    """

    BINDINGS = [
        *ModalDialog.BINDINGS,
        Binding('f5', 'refresh', 'Refresh', show=False),
        Binding('delete', 'delete_selected', 'Delete', show=False),
    ]

    def __init__(
        self,
        config: AppConfig,
        *,
        search: str | None = None,
        sort_by: str = 'updated',
        limit: int = 20,
        preview_target: str | None = None,
        delete_targets: list[str] | None = None,
    ) -> None:
        super().__init__()
        self._config = config
        self._search = search or ''
        self._sort_by = sort_by
        self._limit = max(1, int(limit))
        self._preview_target = preview_target
        self._delete_targets = delete_targets or []
        self._all_entries: list[tuple[str, dict[str, Any], int]] = []
        self._visible_entries: list[tuple[str, dict[str, Any], int]] = []
        self._sessions_root: Path | None = None

    def compose(self) -> ComposeResult:
        options = [
            ('Updated', 'updated'),
            ('Created', 'created'),
            ('Events', 'events'),
            ('Cost', 'cost'),
            ('Model', 'model'),
        ]
        with Vertical(id='dialog-container'):
            yield Label('[bold]Sessions[/]', id='dialog-title')
            with Horizontal(id='sessions-filters'):
                yield Input(
                    value=self._search, placeholder='Search…', id='sessions-search'
                )
                yield Select(
                    options=options,
                    value=self._sort_by,
                    allow_blank=False,
                    id='sessions-sort',
                )
                yield Input(
                    value=str(self._limit), restrict=r'\d*', id='sessions-limit'
                )
                yield Button('Refresh', id='sessions-refresh')
            yield DataTable(id='sessions-table')
            yield Static('', id='sessions-preview')
            yield Label('', id='dialog-feedback')
            with Horizontal(id='dialog-buttons'):
                yield Button('Resume', id='sessions-resume', variant='primary')
                yield Button('Delete', id='sessions-delete', variant='error')
                yield Button('Close', id='sessions-close')

    def on_mount(self) -> None:
        table = self.query_one('#sessions-table', DataTable)
        table.cursor_type = 'row'
        table.add_columns('#', 'Session ID', 'Title', 'Events', 'Updated')
        self._refresh_table()
        if self._delete_targets:
            deleted, errors = self._delete_sessions(self._delete_targets)
            self._set_feedback(
                f'Deleted {deleted} session(s). {" ".join(errors)}'.strip()
            )
            self._refresh_table()
        if self._preview_target:
            self._select_target(self._preview_target)
        self.query_one('#sessions-search', Input).focus()

    def action_refresh(self) -> None:
        self._refresh_table()

    async def action_delete_selected(self) -> None:
        sid = self._current_session_id()
        if not sid:
            self._set_feedback('No session selected.', error=True)
            return
        result = await self.app.push_screen_wait(
            GrintaConfirmDialog(
                title='Delete Session',
                body=f'Permanently delete session {sid[:12]}?',
                options=[('cancel', 'Cancel'), ('delete', 'Delete')],
            )
        )
        if result != 'delete':
            return
        deleted, errors = self._delete_sessions([sid])
        if deleted:
            self._set_feedback(f'Deleted session {sid[:12]}.')
        elif errors:
            self._set_feedback(errors[0], error=True)
        self._refresh_table()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == 'sessions-refresh':
            self._refresh_table()
            return
        if bid == 'sessions-delete':
            self.run_worker(self.action_delete_selected(), exclusive=True)
            return
        if bid == 'sessions-resume':
            sid = self._current_session_id()
            if sid:
                self.dismiss(sid)
            else:
                self._set_feedback('No session selected.', error=True)
            return
        if bid == 'sessions-close':
            self.dismiss(None)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._update_preview(event.cursor_row)

    def on_data_table_row_double_clicked(
        self, event: DataTable.RowDoubleClicked
    ) -> None:
        sid = self._current_session_id()
        if sid:
            self.dismiss(sid)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == 'sessions-search':
            self._search = event.value.strip()
            self._refresh_table()
            return
        if event.input.id == 'sessions-limit':
            value = event.value.strip()
            self._limit = int(value) if value.isdigit() and int(value) > 0 else 20
            self._refresh_table()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == 'sessions-sort' and isinstance(event.value, str):
            self._sort_by = event.value
            self._refresh_table()

    def _set_feedback(self, message: str, *, error: bool = False) -> None:
        style = NAVY_ERROR if error else NAVY_READY
        self.query_one('#dialog-feedback', Label).update(f'[{style}]{message}[/]')

    def _refresh_table(self) -> None:
        from backend.cli.session_manager import (
            _filter_sessions_fuzzy,
            _find_sessions_root,
            _list_session_entries,
        )

        self._sessions_root = _find_sessions_root(self._config)
        table = self.query_one('#sessions-table', DataTable)
        table.clear()
        if self._sessions_root is None:
            self._all_entries = []
            self._visible_entries = []
            self._set_feedback('No session storage found.', error=True)
            self.query_one('#sessions-preview', Static).update('')
            return

        entries = _list_session_entries(self._sessions_root, sort_by=self._sort_by)
        self._all_entries = entries
        if self._search:
            entries = _filter_sessions_fuzzy(entries, self._search)
        self._visible_entries = entries[: self._limit]
        for i, (sid, meta, event_count) in enumerate(self._visible_entries, 1):
            title = str(meta.get('title') or meta.get('name') or '—')
            updated = str(meta.get('last_updated_at') or meta.get('created_at') or '—')[
                :19
            ]
            table.add_row(str(i), sid[:12], title, str(event_count), updated, key=sid)

        if self._visible_entries:
            table.move_cursor(row=0, column=0, animate=False, scroll=False)
            self._update_preview(0)
            self._set_feedback(f'{len(self._visible_entries)} session(s) loaded.')
        else:
            self.query_one('#sessions-preview', Static).update('')
            if self._search:
                self._set_feedback(
                    f'No sessions matching "{self._search}".', error=True
                )
            else:
                self._set_feedback('No sessions found.', error=True)

    def _select_target(self, target: str) -> None:
        from backend.cli.session_manager import _resolve_target

        resolved = _resolve_target(self._visible_entries, target)
        if resolved is None:
            self._set_feedback(f"No session at '{target}'", error=True)
            return
        sid = resolved[0]
        for idx, item in enumerate(self._visible_entries):
            if item[0] == sid:
                table = self.query_one('#sessions-table', DataTable)
                table.move_cursor(row=idx, column=0, animate=False, scroll=True)
                self._update_preview(idx)
                break

    def _current_session_id(self) -> str | None:
        table = self.query_one('#sessions-table', DataTable)
        row_index = table.cursor_row
        if row_index < 0 or row_index >= len(self._visible_entries):
            return None
        return self._visible_entries[row_index][0]

    def _update_preview(self, row_index: int) -> None:
        if row_index < 0 or row_index >= len(self._visible_entries):
            self.query_one('#sessions-preview', Static).update('')
            return
        sid, meta, event_count = self._visible_entries[row_index]
        lines = []
        lines.append(f'[bold]ID:[/] {sid}')
        title = str(meta.get('title') or meta.get('name') or '')
        if title:
            lines.append(f'[bold]Title:[/] {title}')
        model = str(meta.get('llm_model') or '')
        if model:
            lines.append(f'[bold]Model:[/] {model}')
        repo = str(meta.get('selected_repository') or '')
        if repo:
            lines.append(f'[bold]Repository:[/] {repo}')
        branch = str(meta.get('selected_branch') or '')
        if branch:
            lines.append(f'[bold]Branch:[/] {branch}')
        trigger = str(meta.get('trigger') or '')
        if trigger:
            lines.append(f'[bold]Trigger:[/] {trigger}')
        lines.append(f'[bold]Events:[/] {event_count}')
        cost = float(meta.get('accumulated_cost') or 0)
        if cost:
            lines.append(f'[bold]Cost:[/] ${cost:.4f}')
        total_tokens = int(meta.get('total_tokens') or 0)
        if total_tokens:
            prompt_tokens = int(meta.get('prompt_tokens') or 0)
            completion_tokens = int(meta.get('completion_tokens') or 0)
            lines.append(
                f'[bold]Tokens:[/] {total_tokens:,} total'
                f'  [{NAVY_TEXT_DIM}](p:{prompt_tokens:,} c:{completion_tokens:,})[/]'
            )
        updated = str(meta.get('last_updated_at') or meta.get('created_at') or '')
        if updated:
            lines.append(f'[bold]Updated:[/] {updated[:19]}')
        created = str(meta.get('created_at') or '')
        if created and str(meta.get('last_updated_at') or '') != created:
            lines.append(f'[bold]Created:[/] {created[:19]}')
        self.query_one('#sessions-preview', Static).update('\n'.join(lines))

    def _delete_sessions(self, targets: list[str]) -> tuple[int, list[str]]:
        from backend.cli.session_manager import _resolve_target

        if self._sessions_root is None:
            return 0, ['No session storage found.']

        deleted = 0
        errors: list[str] = []
        for target in targets:
            resolved = _resolve_target(self._all_entries, target)
            if resolved is None:
                errors.append(f"No session at '{target}'.")
                continue
            sid = resolved[0]
            try:
                shutil.rmtree(self._sessions_root / sid, ignore_errors=False)
                deleted += 1
            except Exception as exc:
                errors.append(f'{sid[:12]}: {exc}')
        return deleted, errors


# ── Main screen ───────────────────────────────────────────────────────────


class GrintaScreen(Screen):
    """Main TUI screen — Mission Control layout."""

    CSS_PATH = 'styles.tcss'

    BINDINGS = [
        Binding('ctrl+c', 'copy_or_interrupt', 'Copy/Interrupt', show=True),
        Binding('ctrl+shift+c', 'copy_transcript', 'Copy Transcript', show=True),
        Binding('escape', 'interrupt_agent', 'Interrupt', show=False),
        Binding('ctrl+l', 'clear_transcript', 'Clear', show=True),
        Binding('ctrl+space', 'complete_command', 'Complete', show=False),
        Binding('ctrl+z', 'suspend', 'Suspend', show=False),
        Binding('enter', 'submit_input', 'Send', show=False, priority=True),
        Binding('pageup', 'scroll_up', 'Scroll Up', show=False),
        Binding('pagedown', 'scroll_down', 'Scroll Down', show=False),
        Binding('home', 'scroll_home', 'Top', show=False),
        Binding('end', 'scroll_end', 'Bottom', show=False),
        Binding('ctrl+b', 'toggle_sidebar', 'Toggle Sidebar', show=True),
        Binding('f1', 'show_help', 'Help', show=True),
        Binding('ctrl+j', 'focus_next_card', 'Next Card', show=False, priority=True),
        Binding('ctrl+k', 'focus_prev_card', 'Prev Card', show=False, priority=True),
        Binding('ctrl+p', 'history_prev', 'History Prev', show=False),
        Binding('ctrl+n', 'history_next', 'History Next', show=False),
    ]

    def __init__(
        self,
        config: AppConfig,
        console: Any,
        loop: asyncio.AbstractEventLoop,
        hud: HUDBar,
        reasoning: ReasoningDisplay,
        app: App,
    ) -> None:
        super().__init__()
        self._config = config
        self._rich_console = console
        self._loop = loop
        self._hud = hud
        self._reasoning = reasoning
        self._main_app = app
        self._renderer: TUIRenderer | None = None
        self._event_stream: Any | None = None
        self._controller: Any | None = None
        self._agent_task: asyncio.Task[Any] | None = None
        self._runtime_stub: Any = None
        self._memory_stub: Any = None
        self._agent_running = True
        self._input_lock = asyncio.Lock()
        self._bootstrapping: asyncio.Event | None = None
        self._bootstrap_task: asyncio.Task[Any] | None = None
        self._is_unmounted = False
        self._suggestion_matches: list[str] = []
        self._command_hint = ''
        self._phase_label = 'Ready'
        self._phase_started_at = time.monotonic()
        self._current_operation_summary = 'Idle'
        self._current_operation_meta = 'Waiting for activity'
        self._current_operation_active = False
        self._worker_summary = 'No delegated work'
        self._worker_meta = 'Idle'
        self._worker_active = False
        self._worker_has_error = False
        self._retry_summary = 'No retry activity'
        self._retry_meta = 'Idle'
        self._retry_active = False
        self._runtime_summary = 'No runtime notices'
        self._runtime_meta = 'Idle'
        self._runtime_active = False
        self._hud_tick = None
        self._command_history: list[str] = []
        self._history_index: int = -1
        self._welcome_visible = False
        self._active_communicate_card: Any | None = None

    _STATE_LABELS = {
        'starting': 'Starting…',
        'loading': 'Loading…',
        'running': 'Running',
        'retrying': 'Retrying',
        'backoff': 'Backoff',
        'awaiting_user_input': 'Ready',
        'paused': 'Paused',
        'stopped': 'Stopped',
        'finished': 'Finished',
        'rejected': 'Rejected',
        'error': 'Error',
        'awaiting_user_confirmation': 'Confirm',
        'user_confirmed': 'Confirmed',
        'user_rejected': 'Rejected',
        'rate_limited': 'Rate Limited',
    }

    _STATE_COLORS = {
        'starting': NAVY_WAITING,
        'loading': NAVY_WAITING,
        'running': NAVY_BRAND,
        'retrying': NAVY_WAITING,
        'backoff': NAVY_WAITING,
        'awaiting_user_input': NAVY_READY,
        'paused': NAVY_WAITING,
        'stopped': NAVY_TEXT_MUTED,
        'finished': NAVY_READY,
        'rejected': NAVY_ERROR,
        'error': NAVY_ERROR,
        'awaiting_user_confirmation': NAVY_WAITING,
        'user_confirmed': NAVY_READY,
        'user_rejected': NAVY_ERROR,
        'rate_limited': NAVY_WAITING,
    }

    @classmethod
    def _resolve_state_display(cls, raw_state: str | None) -> tuple[str, str]:
        raw = (raw_state or 'Ready').strip()
        lookup_key = raw.lower()
        if lookup_key.startswith('agentstate.'):
            lookup_key = lookup_key[len('agentstate.') :]
        if '.' in lookup_key:
            lookup_key = lookup_key.split('.')[-1]

        for prefix in ('backoff', 'retrying'):
            if lookup_key.startswith(prefix):
                return raw, cls._STATE_COLORS[prefix]

        return (
            cls._STATE_LABELS.get(lookup_key, raw or 'Ready'),
            cls._STATE_COLORS.get(lookup_key, NAVY_BRAND),
        )

    _SLASH_HINTS = {
        '/help': '/help [--all|--search <term>|<command>]',
        '/clear': '/clear',
        '/settings': '/settings',
        '/sessions': '/sessions [list] [--limit N] [--search TERM] [--sort updated|created|events|cost|model] [--preview N|ID] [--delete N|ID ...]',
        '/resume': '/resume <N|session_id>',
        '/quit': '/quit',
    }

    def _active_agent_name(self) -> str:
        name = getattr(self._config, 'default_agent', None)
        return name.strip() if isinstance(name, str) and name.strip() else 'agent'

    def _active_agent_config(self) -> Any | None:
        getter = getattr(self._config, 'get_agent_config', None)
        if not callable(getter):
            return None
        try:
            return getter(self._active_agent_name())
        except TypeError:
            return getter()

    def _active_interaction_mode(self) -> str:
        agent_config = self._active_agent_config()
        return normalize_interaction_mode(
            getattr(agent_config, 'mode', AGENT_MODE),
            default=AGENT_MODE,
        )

    def compose(self) -> ComposeResult:
        from backend.cli.tui.widgets.collapsible import CollapsibleSection

        with Horizontal(id='app-layout'):
            with Vertical(id='left-column'):
                yield ConfirmWidget(id='confirm-widget')
                yield Transcript(id='main-display')
                yield ListView(id='suggestions-list', classes='-hidden')
                with InputBar(id='input-bar'):
                    yield Label(id='input-hint')
                    with Horizontal(id='input-row'):
                        yield Static(id='spinner', classes='-hidden')
                        yield PromptTextArea(id='input', show_line_numbers=False)
                yield HUD(id='hud-bar')
            with Vertical(id='sidebar'):
                with InfoSidebar(id='sidebar-container'):
                    yield CollapsibleSection(
                        title='Tasks (0)',
                        content='No tasks yet',
                        collapsed=False,
                        accent_color='#91abec',
                        id='sidebar-tasks',
                    )
                    yield CollapsibleSection(
                        title='MCP Servers (0)',
                        content='No MCP servers configured',
                        collapsed=False,
                        accent_color='#eacb8a',
                        action_label='+',
                        id='sidebar-mcp',
                    )
                    yield CollapsibleSection(
                        title='Skills',
                        content='No skills available',
                        collapsed=True,
                        accent_color='#7a849c',
                        action_label='+',
                        id='sidebar-skills',
                    )

    def on_mount(self) -> None:
        _tui_logger.debug('on_mount: GrintaScreen mounted')
        self._is_unmounted = False

        self._render_hud_bar()
        self._update_input_identity()
        self._hud_tick = self.set_interval(1.0, self._refresh_runtime_feedback)
        ta = self.query_one('#input', TextArea)
        ta.text = ''
        ta.focus()
        self._get_display().scroll_home(animate=False)
        _tui_logger.debug('on_mount: done')
        self._start_background_bootstrap()
        self.set_timer(0.5, self._show_welcome)

    def on_renderer_drain_requested(self, _message: RendererDrainRequested) -> None:
        if self._renderer is not None:
            self._renderer.drain_events()
        if not self._welcome_visible:
            return
        if self._transcript_has_real_content():
            self._hide_welcome()

    def _start_background_bootstrap(self) -> None:
        async def _bg():
            try:
                await self._bootstrap()
            except asyncio.CancelledError:
                _tui_logger.debug('background bootstrap cancelled')
            except Exception as exc:
                _tui_logger.debug(f'background bootstrap failed: {exc}')

        self._bootstrap_task = asyncio.create_task(_bg(), name='grinta-tui-bootstrap')

    def on_unmount(self) -> None:
        _tui_logger.debug('on_unmount: GrintaScreen unmounting')
        self._is_unmounted = True
        if self._hud_tick is not None:
            self._hud_tick.stop()
            self._hud_tick = None
        if self._bootstrap_task and not self._bootstrap_task.done():
            self._bootstrap_task.cancel()
        if self._renderer:
            if self._renderer._event_stream:
                self._renderer._event_stream.unsubscribe(
                    EventStreamSubscriber.CLI, self._renderer._event_stream.sid
                )
            self._renderer._event_stream = None
        if self._event_stream is not None:
            try:
                self._event_stream.unsubscribe(
                    EventStreamSubscriber.CLI, self._event_stream.sid
                )
                close_fn = getattr(self._event_stream, 'close', None)
                if callable(close_fn):
                    close_fn()
                    _tui_logger.debug('on_unmount: event_stream closed')
            except Exception as exc:
                _tui_logger.debug(f'on_unmount: event_stream close failed: {exc}')
            finally:
                self._event_stream = None
        _tui_logger.debug('on_unmount: done')

    # ── HUD Bar ─────────────────────────────────────────────

    def _render_hud_bar(self) -> None:
        hud = self._hud
        raw_state = hud.state.agent_state_label or 'Ready'
        display_state, state_color = self._resolve_state_display(raw_state)

        used = hud.state.context_tokens
        limit = hud.state.context_limit
        # Restore Model and Autonomy
        _, model_short = HUDBar.describe_model(hud.state.model)
        model_display = model_short if model_short != '(not set)' else '(not set)'
        autonomy = hud.state.autonomy_level

        # Top line info
        workspace = str(hud.state.workspace_path or Path(os.getcwd()))
        try:
            home = str(Path.home())
            if workspace.startswith(home):
                workspace = workspace.replace(home, '~', 1)
        except Exception:
            pass
        line1_parts = []
        line1_parts.append('[#91abec bold]GRINTA[/]')
        line1_parts.append(f'[{state_color}]● {display_state}[/]')
        line1_parts.append(f'[{NAVY_TEXT_SECONDARY}]Model: {model_display}[/]')
        ws_display = HUDBar.ellipsize_path(workspace, 35)
        line1_parts.append(f'[{NAVY_TEXT_DIM}]Ws: {ws_display}[/]')
        line1 = '  '.join(line1_parts)

        # Token count with context circle for top-right corner
        if limit > 0:
            pct = min(100, used * 100 // limit)
            ctx_color = (
                NAVY_GREEN_ACCENT
                if pct < 80
                else NAVY_YELLOW_ACCENT
                if pct < 95
                else NAVY_RED_ACCENT
            )
            token_display = (
                f'[{NAVY_TEXT_DIM}]Tok: {used:,} ({pct}%)  [{ctx_color}]●[/][/]'
            )
        else:
            token_display = f'[{NAVY_TEXT_DIM}]Tok: {used:,}[/]'

        help_hint = r'[#54597b]\[[/][#eacb8a bold]F1[/][#54597b]][/] [#969aad]Help[/]'
        line2 = f'{token_display}   {help_hint}'

        hud_bar = self.query_one('#hud-bar', HUD)
        hud_bar.query_one('#hud-line-1', Label).update(line1)
        hud_bar.query_one('#hud-line-2', Label).update(line2)
        try:
            autonomy_select = hud_bar.query_one('#hud-autonomy', Select)
            if autonomy_select.value != autonomy:
                autonomy_select.value = autonomy
        except Exception:
            pass
        try:
            mode_select = hud_bar.query_one('#hud-mode', Select)
            current_mode = self._active_interaction_mode()
            if current_mode not in VISIBLE_INTERACTION_MODES:
                current_mode = CHAT_MODE if is_chat_mode(current_mode) else AGENT_MODE
            if mode_select.value != current_mode:
                mode_select.value = current_mode
        except Exception:
            pass
        try:
            current_mode = self._active_interaction_mode()
            is_agent = current_mode == AGENT_MODE
            hud_bar.query_one('#hud-autonomy').display = is_agent
            hud_bar.query_one('#hud-label-autonomy').display = is_agent
        except Exception:
            pass

    def _update_input_identity(self, mode: str | None = None) -> None:
        """Update InputBar border title and hint based on mode."""
        if mode is None:
            mode = self._active_interaction_mode()
        mode = normalize_interaction_mode(mode)
        try:
            bar = self.query_one('#input-bar', InputBar)
            hint = self.query_one('#input-hint', Label)
            ta = self.query_one('#input', TextArea)
        except Exception:
            return
        if is_chat_mode(mode):
            bar.border_title = ' Chat '
            hint.update('Ask about the codebase or architecture...')
        elif mode == PLAN_MODE:
            bar.border_title = ' Plan '
            hint.update('Describe what Grinta should inspect and plan...')
        else:
            bar.border_title = ' Agent task '
            hint.update('Describe a task for Grinta to execute...')
        hint.display = not bool(ta.text.strip())

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        lst = self.query_one('#suggestions-list', ListView)
        if lst.has_class('-hidden') or not self._suggestion_matches:
            return
        selected = lst.index if lst.index is not None else 0
        ta = self.query_one('#input', TextArea)
        if 0 <= selected < len(self._suggestion_matches):
            ta.text = self._suggestion_matches[selected] + ' '
        lst.add_class('-hidden')
        self._suggestion_matches = []
        ta.focus()

    def _refresh_runtime_feedback(self) -> None:
        if not self._is_unmounted:
            self._render_hud_bar()

    def set_agent_phase(self, state_value: str) -> None:
        key = state_value.lower().strip()
        if key.startswith('agentstate.'):
            key = key[len('agentstate.') :]
        if '.' in key:
            key = key.split('.')[-1]
        if key.startswith('backoff'):
            label = 'Backoff'
        elif key.startswith('retrying'):
            label = 'Retrying'
        else:
            label = self._STATE_LABELS.get(key, state_value)
        if label != self._phase_label:
            self._phase_label = label
            self._phase_started_at = time.monotonic()
            self._render_hud_bar()

    def set_current_operation(
        self,
        summary: str,
        *,
        meta: str = '',
        active: bool = True,
    ) -> None:
        summary_text = re.sub(r'\s+', ' ', (summary or '').strip()) or 'Idle'
        if len(summary_text) > 120:
            summary_text = summary_text[:117] + '...'
        meta_text = re.sub(r'\s+', ' ', (meta or '').strip())
        if len(meta_text) > 140:
            meta_text = meta_text[:137] + '...'
        self._current_operation_summary = summary_text
        self._current_operation_meta = meta_text or 'Waiting for activity'
        self._current_operation_active = active

    def clear_current_operation(self, meta: str = 'Waiting for activity') -> None:
        self.set_current_operation('Idle', meta=meta, active=False)

    def set_retry_status(
        self,
        summary: str,
        *,
        meta: str = '',
        active: bool = True,
    ) -> None:
        summary_text = (
            re.sub(r'\s+', ' ', (summary or '').strip()) or 'No retry activity'
        )
        if len(summary_text) > 120:
            summary_text = summary_text[:117] + '...'
        meta_text = re.sub(r'\s+', ' ', (meta or '').strip()) or 'Idle'
        if len(meta_text) > 160:
            meta_text = meta_text[:157] + '...'
        self._retry_summary = summary_text
        self._retry_meta = meta_text
        self._retry_active = active

    def clear_retry_status(self, meta: str = 'Idle') -> None:
        self.set_retry_status('No retry activity', meta=meta, active=False)

    def set_runtime_status(
        self,
        summary: str,
        *,
        meta: str = '',
        active: bool = False,
    ) -> None:
        summary_text = (
            re.sub(r'\s+', ' ', (summary or '').strip()) or 'No runtime notices'
        )
        if len(summary_text) > 120:
            summary_text = summary_text[:117] + '...'
        meta_text = re.sub(r'\s+', ' ', (meta or '').strip()) or 'Idle'
        if len(meta_text) > 160:
            meta_text = meta_text[:157] + '...'
        self._runtime_summary = summary_text
        self._runtime_meta = meta_text
        self._runtime_active = active

    def clear_runtime_status(self, meta: str = 'Idle') -> None:
        self.set_runtime_status('No runtime notices', meta=meta, active=False)

    def set_worker_status(
        self,
        summary: str,
        *,
        meta: str = '',
        active: bool = False,
        has_error: bool = False,
    ) -> None:
        summary_text = (
            re.sub(r'\s+', ' ', (summary or '').strip()) or 'No delegated work'
        )
        if len(summary_text) > 120:
            summary_text = summary_text[:117] + '...'
        meta_text = re.sub(r'\s+', ' ', (meta or '').strip()) or 'Idle'
        if len(meta_text) > 160:
            meta_text = meta_text[:157] + '...'
        self._worker_summary = summary_text
        self._worker_meta = meta_text
        self._worker_active = active
        self._worker_has_error = has_error

    def _update_command_hint(self, text: str) -> None:
        stripped = _strip_ansi(text).strip()
        if not stripped.startswith('/'):
            if self._command_hint:
                self._command_hint = ''
                self._render_hud_bar()
            return

        try:
            parts = shlex.split(stripped)
        except ValueError:
            hint = 'Command syntax error: check quotes.'
        else:
            if not parts:
                hint = ''
            else:
                cmd = parts[0].lower()
                if cmd in self._SLASH_HINTS:
                    if (
                        cmd == '/sessions'
                        and len(parts) > 1
                        and parts[-1].startswith('--')
                    ):
                        hint = (
                            'Sessions flags: --limit --search --sort --preview --delete'
                        )
                    elif (
                        cmd == '/help' and len(parts) > 1 and parts[-1].startswith('--')
                    ):
                        hint = 'Help flags: --all or --search <term>'
                    else:
                        hint = self._SLASH_HINTS[cmd]
                else:
                    candidates = [c for c in self._SLASH_HINTS if c.startswith(cmd)]
                    hint = (
                        'Commands: ' + ', '.join(candidates[:5])
                        if candidates
                        else 'Commands: /help, /clear, /settings, /sessions, /resume, /quit'
                    )

        if hint != self._command_hint:
            self._command_hint = hint
            self._render_hud_bar()

    # ── Transcript helpers ──────────────────────────────────────────────────

    def _get_display(self) -> Transcript:
        return self.query_one('#main-display', Transcript)

    def _write_log(self, renderable: Any) -> None:
        if self._renderer:
            self._renderer.add_to_history(renderable)

    def add_user_message(self, text: str) -> None:
        """User message."""
        self.finalize_thinking()
        if self._renderer:
            self._renderer._clear_last_active_card_processing()
        display = self._get_display()
        if type(display).__name__ == 'MagicMock':
            display.write(text)
            return
        from backend.cli.tui.widgets.activity_card import UserMessage

        widget = UserMessage(text)
        display.append_widget(widget)

    def add_agent_message(self, text: str) -> None:
        """Agent response."""
        self.finalize_thinking()
        if self._renderer:
            self._renderer._clear_last_active_card_processing()
        display = self._get_display()
        if type(display).__name__ == 'MagicMock':
            display.write(text)
            return
        from backend.cli.tui.widgets.activity_card import AgentMessage

        widget = AgentMessage(text)
        display.append_widget(widget)

    def add_thinking(self, text: str) -> None:
        """Real-time thinking/reasoning — update live display."""
        spinner = self.query_one('#spinner', Static)
        spinner.remove_class('-hidden')
        spinner.update('⟳')

        if self._renderer:
            self._renderer.update_live_thinking(text)

    def finalize_thinking(self) -> None:
        """Agent turn done — hide spinner."""
        self.query_one('#spinner', Static).add_class('-hidden')
        if self._renderer:
            self._renderer.commit_live_thinking()

    def add_system_message(self, text: str) -> None:
        body = _rich_text(text)
        body.stylize(NAVY_TEXT_MUTED)
        self._write_log(body)

    def add_error(self, text: str) -> None:
        import textwrap

        wrapped = textwrap.fill(text, width=80)
        lines = wrapped.split('\n')
        result = Text()
        for i, line in enumerate(lines):
            if i > 0:
                result.append('\n   ')
            if i == 0:
                result.append(Text('✗ ', style=f'bold {NAVY_ERROR}'))
            result.append(Text(line, style=f'bold {NAVY_ERROR}'))
        self._write_log(result)

    def add_success(self, text: str) -> None:
        icon = Text('✓ ', style=f'bold {NAVY_READY}')
        body = _rich_text(text)
        body.stylize(f'bold {NAVY_READY}')
        self._write_log(Text.assemble(icon, body))

    def add_tool_start(self, tool_name: str, *, command: str = '') -> None:
        """Tool call — show in transcript."""
        icon = Text('⚙ ', style='#91abec')
        name = _rich_text(tool_name)
        name.stylize('#91abec')

        if command:
            cmd_text = _rich_text(command)
            self._write_log(
                Text.assemble(icon, name, ' (', cmd_text, ')', style='#969aad')
            )
        else:
            self._write_log(Text.assemble(icon, name))

    def add_tool_result(self, text: str) -> None:
        """Tool result — muted text."""
        body = _rich_text(text)
        body.stylize(NAVY_TEXT_MUTED)
        self._write_log(Text.assemble('  ', body))

    def add_communicate_clarification(self, action: ClarificationRequestAction) -> None:
        """Agent asks a question — render an interactive communicate card."""
        options = [(opt, opt, '', False) for opt in (action.options or [])]
        details = [action.context] if action.context else []
        card = CommunicatePromptWidget(
            'Question',
            action.question or 'The agent needs your input.',
            context=action.thought,
            details=details,
            options=options,
        )
        self._write_log(card)
        self._set_active_communicate_card(card if options else None)

    def add_communicate_uncertainty(self, action: UncertaintyAction) -> None:
        """Agent expresses uncertainty."""
        details = list((action.specific_concerns or [])[:5])
        if action.requested_information:
            details.append(f'Needed: {action.requested_information}')
        card = CommunicatePromptWidget(
            'Needs Context',
            'The agent needs more context before it can continue confidently.',
            context=action.thought,
            details=details,
        )
        self._write_log(card)
        self._set_active_communicate_card(None)

    def add_communicate_proposal(self, action: ProposalAction) -> None:
        """Agent proposes a plan."""
        options: list[tuple[str, str, str, bool]] = []
        for i, opt in enumerate(action.options or []):
            label = opt.get(
                'name',
                opt.get('title', opt.get('approach', f'Option {i + 1}')),
            )
            description = opt.get('description', '')
            if not description:
                pros = ', '.join(opt.get('pros') or [])
                cons = ', '.join(opt.get('cons') or [])
                fragments = []
                if pros:
                    fragments.append(f'Pros: {pros}')
                if cons:
                    fragments.append(f'Cons: {cons}')
                description = ' | '.join(fragments)
            options.append((label, label, description, i == action.recommended))

        card = CommunicatePromptWidget(
            'Options',
            'Choose a path for the agent to take.',
            context=action.thought,
            details=[action.rationale] if action.rationale else [],
            options=options,
        )
        self._write_log(card)
        self._set_active_communicate_card(card if options else None)

    def add_communicate_escalate(self, action: EscalateToHumanAction) -> None:
        """Agent escalates to human."""
        details = list(action.attempts_made or [])
        if action.specific_help_needed:
            details.append(f'Help needed: {action.specific_help_needed}')
        card = CommunicatePromptWidget(
            'Need Your Input',
            action.reason or 'The agent needs your input to continue.',
            context=action.thought,
            details=details,
        )
        self._write_log(card)
        self._set_active_communicate_card(None)

    def add_divider(self) -> None:
        self._write_log(Rule(style=NAVY_BORDER))

    def clear_transcript(self) -> None:
        if self._renderer:
            self._renderer.clear_history()

    def action_clear_transcript(self) -> None:
        self.clear_transcript()

    def action_suspend(self) -> None:
        self._agent_running = False
        self.app.exit()

    def action_copy_or_interrupt(self) -> None:
        """Copy selected text if any, otherwise interrupt the agent."""
        ta = self.query_one('#input', TextArea)
        if ta.selected_text:
            self.app.copy_to_clipboard(ta.selected_text)
            return
        if self._is_agent_running():
            self._interrupt_agent()

    def action_copy_transcript(self) -> None:
        """Copy the entire transcript content to clipboard."""
        if self._renderer and self._renderer._history:
            # Extract plain text from Rich history
            plain_text = self._extract_plain_text_from_history()
            if plain_text:
                self.app.copy_to_clipboard(plain_text)
                self._write_log(Text('  [dim]Transcript copied to clipboard[/dim]'))
            else:
                self._write_log(Text('  [dim]No content to copy[/dim]'))
        else:
            self._write_log(Text('  [dim]No transcript content[/dim]'))

    def _extract_plain_text_from_history(self) -> str:
        """Extract plain text from Rich history for copying."""
        if not self._renderer or not self._renderer._history:
            return ''

        lines = []
        for item in self._renderer._history:
            if hasattr(item, 'plain'):
                # Rich Text object
                lines.append(item.plain)
            elif isinstance(item, str):
                lines.append(item)
            elif hasattr(item, '__rich_console__'):
                # Rich renderable - try to extract text
                try:
                    from rich.console import Console

                    console = Console(force_terminal=True, width=200)
                    with console.capture() as capture:
                        console.print(item)
                    lines.append(capture.get())
                except Exception:
                    pass

        return '\n'.join(line for line in lines if line.strip())

    def action_interrupt_agent(self) -> None:
        """Interrupt the running agent."""
        if self._is_agent_running():
            self._interrupt_agent()

    def _is_agent_running(self) -> bool:
        """Check if the agent is currently running."""
        if self._controller is None:
            return False
        state = self._controller.get_agent_state()
        return state == AgentState.RUNNING

    def _interrupt_agent(self) -> None:
        """Cancel the running agent and clean up."""
        _tui_logger.info('User requested agent interrupt')

        if self._agent_task and not self._agent_task.done():
            self._agent_task.cancel()

        import contextlib

        async def _do_interrupt() -> None:
            if self._controller is not None:
                mark = getattr(self._controller, 'mark_user_interrupt_stop', None)
                if callable(mark):
                    mark()
                with contextlib.suppress(Exception):
                    await self._controller.stop()

            if self._agent_task and not self._agent_task.done():
                try:
                    await asyncio.wait_for(self._agent_task, timeout=5.0)
                except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                    pass

            with contextlib.suppress(Exception):
                from backend.execution.action_execution_server import (
                    client as runtime_client,
                )

                if runtime_client is not None:
                    await runtime_client.hard_kill()

            if self._renderer is not None:
                self._renderer._tui.add_system_message('Interrupted. Ready for input.')

            self.finalize_thinking()
            spinner = self.query_one('#spinner', Static)
            spinner.add_class('-hidden')
            self.query_one('#input-bar', InputBar).remove_class('processing')

        asyncio.create_task(_do_interrupt())

    def action_scroll_up(self) -> None:
        """Scroll transcript up by one page."""
        self._get_display().scroll_page_up(animate=True)

    def action_scroll_down(self) -> None:
        """Scroll transcript down by one page."""
        self._get_display().scroll_page_down(animate=True)

    def action_scroll_home(self) -> None:
        """Scroll transcript to top."""
        self._get_display().scroll_home(animate=True)

    def action_scroll_end(self) -> None:
        """Scroll transcript to bottom."""
        self._scroll_to_bottom()

    def action_toggle_sidebar(self) -> None:
        """Toggle sidebar visibility."""
        sidebar = self.query_one('#sidebar')
        if sidebar.has_class('-hidden'):
            sidebar.remove_class('-hidden')
            transcript = self.query_one('#main-display', Transcript)
            transcript.styles.width = '70%'
        else:
            sidebar.add_class('-hidden')
            transcript = self.query_one('#main-display', Transcript)
            transcript.styles.width = '100%'

    def action_show_help(self) -> None:
        """Show help information."""
        self.show_help()

    def action_history_prev(self) -> None:
        """Navigate backward through command history."""
        if not self._command_history:
            return
        ta = self.query_one('#input', TextArea)
        if self._history_index == -1:
            self._history_index = len(self._command_history) - 1
        elif self._history_index > 0:
            self._history_index -= 1
        ta.text = self._command_history[self._history_index]
        ta.cursor = (len(ta.text.splitlines()), 0)

    def action_history_next(self) -> None:
        """Navigate forward through command history."""
        ta = self.query_one('#input', TextArea)
        if self._history_index == -1:
            return
        self._history_index -= 1
        if self._history_index < 0:
            self._history_index = -1
            ta.text = ''
        else:
            ta.text = self._command_history[self._history_index]
        ta.cursor = (len(ta.text.splitlines()), 0)

    def _scroll_to_bottom(self) -> None:
        self._get_display().force_scroll_end()

    def _find_focusable_cards(self) -> list[Widget]:
        """Return all ActivityCard widgets in the transcript in DOM order."""
        from backend.cli.tui.widgets.activity_card import ActivityCard

        display = self._get_display()
        return [c for c in display.query(ActivityCard) if c.display]

    def _set_active_communicate_card(self, card: Any | None) -> None:
        previous = self._active_communicate_card
        if previous is not None and previous is not card:
            try:
                previous.set_active(False)
            except Exception:
                pass
        self._active_communicate_card = card
        if card is not None:
            try:
                card.set_active(True)
            except Exception:
                pass

    def _handle_communicate_navigation(self, key: str) -> bool:
        card = self._active_communicate_card
        if card is None or not getattr(card, 'has_options', False):
            return False
        if key == 'up':
            card.highlight_prev()
            return True
        if key == 'down':
            card.highlight_next()
            return True
        return False

    def _handle_communicate_selection(
        self,
        text: str,
        *,
        card: Any | None = None,
    ) -> None:
        active = card or self._active_communicate_card
        if active is not None:
            try:
                active.set_active(False)
            except Exception:
                pass
            if active is self._active_communicate_card:
                self._active_communicate_card = None
        ta = self.query_one('#input', TextArea)
        ta.text = text
        self.action_submit_input()

    def action_focus_next_card(self) -> None:
        """Move keyboard focus to the next ActivityCard or suggestion."""
        if self._welcome_visible:
            ta = self.query_one('#input', TextArea)
            if not ta.text.strip():
                widget = self._get_welcome_widget()
                if widget is not None:
                    widget.highlight_next()
                return
        if self.focused and self.focused is self.query_one('#input', TextArea):
            return
        cards = self._find_focusable_cards()
        if not cards:
            return
        focused = self.screen.focused
        start = 0
        if focused in cards:
            start = (cards.index(focused) + 1) % len(cards)
        cards[start].focus()

    def action_focus_prev_card(self) -> None:
        """Move keyboard focus to the previous ActivityCard or suggestion."""
        if self._welcome_visible:
            ta = self.query_one('#input', TextArea)
            if not ta.text.strip():
                widget = self._get_welcome_widget()
                if widget is not None:
                    widget.highlight_prev()
                return
        if self.focused and self.focused is self.query_one('#input', TextArea):
            return
        cards = self._find_focusable_cards()
        if not cards:
            return
        focused = self.screen.focused
        start = -1
        if focused in cards:
            start = cards.index(focused) - 1
        cards[start].focus()

    def _update_suggestions_list(self, text: str) -> None:
        try:
            lst = self.query_one('#suggestions-list', ListView)
        except Exception:
            return
        stripped = _strip_ansi(text).strip()
        if not stripped.startswith('/'):
            lst.add_class('-hidden')
            self._suggestion_matches = []
            return
        try:
            parts = shlex.split(stripped)
        except ValueError:
            lst.add_class('-hidden')
            self._suggestion_matches = []
            return
        if not parts:
            lst.add_class('-hidden')
            self._suggestion_matches = []
            return
        cmd = parts[0].lower()
        matches = [name for name in self._SLASH_HINTS if name.startswith(cmd)]
        if not matches:
            lst.add_class('-hidden')
            self._suggestion_matches = []
            return
        self._suggestion_matches = matches
        lst.clear()
        for name in matches:
            hint = self._SLASH_HINTS[name]
            lst.append(ListItem(Label(f'[#eacb8a]{name}[/]  [#54597b]{hint}[/]')))
        lst.index = 0
        lst.remove_class('-hidden')

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == 'input':
            text = _strip_terminal_control_literals(event.text_area.text)
            if text != event.text_area.text:
                event.text_area.text = text
                return
            self._update_suggestions_list(text)
            try:
                hint = self.query_one('#input-hint', Label)
                hint.display = not bool(text.strip())
            except Exception:
                pass
            self._resize_input_bar()

    _INPUT_HEIGHT_FRACTION = 0.3
    _MIN_INPUT_HEIGHT = 6

    def _resize_input_bar(self) -> None:
        try:
            ta = self.query_one('#input', TextArea)
            bar = self.query_one('#input-bar', InputBar)
        except Exception:
            return
        line_count = ta.text.count('\n') + 1
        max_total = max(
            self._MIN_INPUT_HEIGHT,
            int(self.size.height * self._INPUT_HEIGHT_FRACTION),
        )
        non_content = 3
        max_content = max_total - non_content
        content_rows = min(max(line_count, 2), max_content)
        bar.styles.height = non_content + content_rows

    def on_focus(self, event: events.Focus) -> None:
        if event.control and event.control.id == 'input':
            try:
                self.query_one('#input-bar', InputBar).remove_class('-blurred')
            except Exception:
                pass

    def on_blur(self, event: events.Blur) -> None:
        if event.control and event.control.id == 'input':
            try:
                self.query_one('#input-bar', InputBar).add_class('-blurred')
            except Exception:
                pass

    def on_resize(self, event: events.Resize) -> None:
        self._resize_input_bar()

    def _transcript_has_real_content(self) -> bool:
        """True when transcript has non-welcome, non-badge visible content."""
        try:
            display = self._get_display()
        except Exception:
            return False
        for child in display.children:
            if not getattr(child, 'display', True):
                continue
            if getattr(child, 'id', None) == 'scroll-badge':
                continue
            if type(child) is WelcomeWidget:
                continue
            return True
        return False

    def _get_welcome_widget(self) -> WelcomeWidget | None:
        try:
            display = self._get_display()
        except Exception:
            return None
        for child in display.children:
            if type(child) is WelcomeWidget:
                return child
        return None

    def _show_welcome(self) -> None:
        if self._welcome_visible or self._is_unmounted:
            return
        try:
            if self._transcript_has_real_content():
                return
            display = self._get_display()
            if self._get_welcome_widget() is not None:
                return
            display.mount(WelcomeWidget())
            self._welcome_visible = True
        except Exception:
            pass

    def _hide_welcome(self) -> None:
        if not self._welcome_visible:
            return
        try:
            widget = self._get_welcome_widget()
            if widget is not None:
                widget.remove()
            self._welcome_visible = False
        except Exception:
            self._welcome_visible = False

    def action_welcome_select(self) -> None:
        if not self._welcome_visible:
            return
        ta = self.query_one('#input', TextArea)
        if ta.text.strip():
            return
        widget = self._get_welcome_widget()
        if widget is None:
            return
        text = widget.select_current()
        if text:
            ta.text = text
            self._hide_welcome()
            self.action_submit_input()

    def _handle_welcome_click(self, text: str) -> None:
        if not self._welcome_visible:
            return
        ta = self.query_one('#input', TextArea)
        ta.text = text
        self._hide_welcome()
        self.action_submit_input()

    def on_select_changed(self, event: Select.Changed) -> None:
        event.stop()
        widget_id = event.select.id
        if widget_id == 'hud-autonomy':
            self._apply_autonomy_level(event.value)
        elif widget_id == 'hud-mode':
            self._apply_mode(event.value)

    def _apply_autonomy_level(self, new_level: str) -> None:
        level = (new_level or '').strip().lower()
        if level not in {'conservative', 'balanced', 'full'}:
            return
        controller = self._controller
        if controller is not None:
            ac = getattr(controller, 'autonomy_controller', None)
            if ac is not None:
                ac.autonomy_level = level
        try:
            setattr(self._config, 'autonomy_level', level)
        except Exception:
            pass
        self._hud.update_autonomy(level)
        self._render_hud_bar()
        self.notify(f'Autonomy: {level}', severity='information', timeout=2.0)

    def _apply_mode(self, new_mode: str) -> None:
        mode = normalize_interaction_mode(new_mode, default='')
        if mode not in set(VISIBLE_INTERACTION_MODES):
            return
        agent_config = self._active_agent_config()
        if agent_config is not None:
            agent_config.mode = mode
        controller = self._controller
        if controller is not None:
            agent = getattr(controller, 'agent', None)
            if agent is not None:
                running_config = getattr(agent, 'config', None)
                if running_config is not None:
                    running_config.mode = mode
                planner = getattr(agent, 'planner', None)
                planner_config = getattr(planner, '_config', None)
                if planner_config is not None:
                    planner_config.mode = mode
                if planner is not None and hasattr(planner, 'build_toolset'):
                    try:
                        agent.tools = planner.build_toolset()
                    except Exception:
                        _tui_logger.debug(
                            'Failed to rebuild toolset on mode change', exc_info=True
                        )
            state = getattr(controller, 'state', None)
            extra_data = (
                getattr(state, 'extra_data', None) if state is not None else None
            )
            if isinstance(extra_data, dict):
                if is_chat_mode(mode):
                    extra_data.pop('active_run_mode', None)
                else:
                    extra_data['active_run_mode'] = mode
        self._render_hud_bar()
        self._update_input_identity(mode)
        self._toggle_autonomy_tabs_visibility(mode)
        self.notify(f'Mode: {mode}', severity='information', timeout=2.0)

    def _toggle_autonomy_tabs_visibility(self, mode: str) -> None:
        mode = normalize_interaction_mode(mode)
        try:
            autonomy_tabs = self.query_one('#hud-autonomy')
            autonomy_tabs.display = mode == AGENT_MODE
            self.query_one('#hud-label-autonomy').display = mode == AGENT_MODE
        except Exception:
            pass

    def on_sidebar_row_selected(self, event: Any) -> None:
        """Handle SidebarRow selected events and notify the user."""
        from backend.cli.tui.widgets.collapsible import SidebarRow

        if not isinstance(event, SidebarRow.Selected):
            return
        item_id = event.item_id
        if not item_id:
            return
        if item_id.startswith('task:'):
            task_id = item_id.split(':', 1)[1]
            desc = 'Unknown task'
            tasks = task_panel_signature(
                self._renderer._task_list if self._renderer else []
            )
            for tid, _status, description in tasks:
                if tid == task_id:
                    desc = description or desc
                    break
            self.notify(f'Task {task_id}: {desc}', severity='info', timeout=3.0)
        elif item_id.startswith('mcp:'):
            mcp_name = item_id.split(':', 1)[1]
            self.notify(
                f'MCP Server: {mcp_name}  |  Press Delete to remove',
                severity='info',
                timeout=3.0,
            )
        elif item_id.startswith('skill:'):
            skill_name = item_id.split(':', 1)[1]
            self.notify(
                f'Playbook Skill: {skill_name}.md  |  Press Delete to remove',
                severity='info',
                timeout=3.0,
            )

    async def on_sidebar_row_delete_requested(self, event: Any) -> None:
        """Handle SidebarRow delete events."""
        from backend.cli.tui.widgets.collapsible import SidebarRow

        if not isinstance(event, SidebarRow.DeleteRequested) or not event.item_id:
            return
        item_id = event.item_id
        if item_id.startswith('skill:'):
            skill_name = item_id[6:]
            self.run_worker(self._confirm_delete_skill(skill_name), exclusive=True)
        elif item_id.startswith('mcp:'):
            mcp_name = item_id.split(':', 1)[1]
            self.run_worker(self._confirm_delete_mcp(mcp_name), exclusive=True)

    async def _confirm_delete_skill(self, skill_name: str) -> None:
        result = await self.app.push_screen_wait(
            GrintaConfirmDialog(
                title='Delete Skill',
                body=f'Are you sure you want to delete {skill_name}.md?',
                options=[('cancel', 'Cancel'), ('delete', 'Delete')],
            )
        )
        if result == 'delete':
            self._delete_skill(skill_name)

    async def _confirm_delete_mcp(self, mcp_name: str) -> None:
        result = await self.app.push_screen_wait(
            GrintaConfirmDialog(
                title='Delete MCP Server',
                body=f"Are you sure you want to remove the server '{mcp_name}'?",
                options=[('cancel', 'Cancel'), ('delete', 'Remove')],
            )
        )
        if result == 'delete':
            self._delete_mcp_server(mcp_name)

    def _delete_skill(self, name: str) -> None:
        if not name.endswith('.md'):
            name += '.md'
        skill_path = Path.home() / '.grinta' / 'skills' / name
        try:
            if skill_path.exists():
                skill_path.unlink()
                self.notify(f'Skill deleted: {name}', severity='information')
                self._last_sidebar_state = None
            else:
                self.notify(f'Skill not found: {name}', severity='warning')
        except Exception as e:
            self.notify(f'Failed to delete skill: {e}', severity='error')

    def _delete_mcp_server(self, name: str) -> None:
        from backend.cli.config_manager import remove_mcp_server

        try:
            remove_mcp_server(name)
            self.notify(f'MCP Server removed: {name}', severity='information')
            self._last_sidebar_state = None
        except Exception as e:
            self.notify(f'Failed to remove MCP server: {e}', severity='error')

    @work
    async def on_collapsible_section_action_clicked(self, event: Any) -> None:
        """Handle [+] Add clicks on sidebar sections."""
        if not event.control:
            return

        if event.control.id == 'sidebar-skills':
            result = await self.app.push_screen_wait(GrintaAddSkillDialog())
            if result:
                self._create_skill(result['name'], result['content'])
        elif event.control.id == 'sidebar-mcp':
            result = await self.app.push_screen_wait(GrintaAddMCPDialog())
            if result:
                self._add_mcp_server(result['name'], result['command'])

    def _create_skill(self, name: str, content: str) -> None:
        skills_dir = Path.home() / '.grinta' / 'skills'
        skills_dir.mkdir(parents=True, exist_ok=True)
        if not name.endswith('.md'):
            name += '.md'
        skill_path = skills_dir / name
        try:
            skill_path.write_text(content, encoding='utf-8')
            self.notify(f'Skill created: {name}', severity='information')
            self._last_sidebar_state = None  # Force full refresh next tick
        except Exception as e:
            self.notify(f'Failed to create skill: {e}', severity='error')

    def _add_mcp_server(self, name: str, command: str) -> None:
        from backend.cli.config_manager import add_mcp_server

        try:
            add_mcp_server(name, command=command)
            self.notify(f'MCP Server added: {name}', severity='information')
            self._last_sidebar_state = None  # Force full refresh next tick
        except Exception as e:
            self.notify(f'Failed to add MCP server: {e}', severity='error')

    # ── Input handling ──────────────────────────────────────────────────────

    def action_complete_command(self) -> None:
        ta = self.query_one('#input', TextArea)
        raw = _strip_ansi(ta.text)
        if not raw.strip().startswith('/'):
            return

        lst = self.query_one('#suggestions-list', ListView)
        if not lst.has_class('-hidden') and self._suggestion_matches:
            selected = lst.index if lst.index is not None else 0
            if 0 <= selected < len(self._suggestion_matches):
                ta.text = self._suggestion_matches[selected] + ' '
            lst.add_class('-hidden')
            self._suggestion_matches = []
            ta.focus()
            return

        try:
            parts = shlex.split(raw.strip())
        except ValueError:
            self.add_error('Cannot autocomplete: malformed command.')
            return
        if not parts:
            return

        cmd = parts[0].lower()
        if len(parts) == 1:
            matches = [name for name in self._SLASH_HINTS if name.startswith(cmd)]
            if not matches:
                return
            if len(matches) == 1:
                ta.text = matches[0] + ' '
            return

        if cmd == '/sessions' and parts[-1].startswith('--'):
            flags = ['--limit', '--search', '--sort', '--preview', '--delete']
            matches = [flag for flag in flags if flag.startswith(parts[-1])]
            if len(matches) == 1:
                prefix = raw.rstrip()
                ta.text = prefix[: -len(parts[-1])] + matches[0] + ' '
        elif cmd == '/help' and parts[-1].startswith('--'):
            flags = ['--all', '--search']
            matches = [flag for flag in flags if flag.startswith(parts[-1])]
            if len(matches) == 1:
                prefix = raw.rstrip()
                ta.text = prefix[: -len(parts[-1])] + matches[0] + ' '

    def action_submit_input(self) -> None:
        _tui_logger.debug(
            f'action_submit_input: lock_locked={self._input_lock.locked()}'
        )
        if self._input_lock.locked():
            _tui_logger.debug('action_submit_input: lock held, ignoring')
            return
        ta = self.query_one('#input', TextArea)
        clean_text = _strip_terminal_control_literals(ta.text)
        if clean_text != ta.text:
            ta.text = clean_text
        text = _strip_ansi(clean_text).strip()
        _tui_logger.debug(f'action_submit_input: text_len={len(text)}')
        if not text:
            if self._welcome_visible:
                _tui_logger.debug('action_submit_input: routing to welcome select')
                self.action_welcome_select()
            elif self._active_communicate_card is not None and getattr(
                self._active_communicate_card, 'has_options', False
            ):
                _tui_logger.debug(
                    'action_submit_input: routing to communicate selection'
                )
                self._active_communicate_card.action_submit_option()
            else:
                _tui_logger.debug('action_submit_input: empty text, ignoring')
            return
        if self._welcome_visible:
            self._hide_welcome()
        if self._active_communicate_card is not None:
            try:
                self._active_communicate_card.set_active(False)
            except Exception:
                pass
            self._active_communicate_card = None
        if not self._command_history or self._command_history[-1] != text:
            self._command_history.append(text)
        self._history_index = -1
        _tui_logger.debug('action_submit_input: creating task for _handle_input')
        try:
            task = asyncio.create_task(self._handle_input(text))
            _tui_logger.debug(f'action_submit_input: task created {task}')

            def _on_done(t: asyncio.Task[Any]) -> None:
                exc = t.exception()
                if exc:
                    _tui_logger.debug(
                        f'_handle_input task FAILED: {type(exc).__name__}: {exc}'
                    )
                else:
                    _tui_logger.debug('_handle_input task completed OK')

            task.add_done_callback(_on_done)
        except Exception as exc:
            _tui_logger.debug(
                f'action_submit_input: create_task FAILED: {type(exc).__name__}: {exc}'
            )

    async def _handle_input(self, text: str) -> None:
        try:
            _tui_logger.debug(f'_handle_input ENTER text={text[:80]}')
        except Exception as exc:
            _tui_logger.debug(
                f'_handle_input: _trace FAILED: {type(exc).__name__}: {exc}'
            )
        async with self._input_lock:
            # Drain any stale events from previous turn before starting new one
            if self._renderer:
                self._renderer.drain_events()

            ta = self.query_one('#input', TextArea)
            ta.clear()
            lst = self.query_one('#suggestions-list', ListView)
            lst.add_class('-hidden')
            self._suggestion_matches = []
            ta.focus()
            self._scroll_to_bottom()

            if text.startswith('/'):
                await self._handle_slash_command(text)
                return

            self.add_user_message(text)
            self._render_hud_bar()
            self.query_one('#input-bar', InputBar).add_class('processing')

            try:
                _tui_logger.debug(
                    f'_handle_input: controller={self._controller is not None}'
                )
                if self._controller is None:
                    if (
                        self._bootstrapping is not None
                        and not self._bootstrapping.is_set()
                    ):
                        _tui_logger.debug(
                            '_handle_input: waiting for background bootstrap'
                        )
                        logger.info(
                            '[TUI] _handle_input: waiting for background bootstrap'
                        )
                        await self._bootstrapping.wait()
                    if self._controller is None:
                        _tui_logger.debug('_handle_input: calling _bootstrap()')
                        logger.info(
                            '[TUI] _handle_input: bootstrapping (no controller)'
                        )
                        # Internal bootstrap - no user-facing message
                        await self._bootstrap()
                    if self._controller is None:
                        raise RuntimeError('Bootstrap failed to initialize controller')
                    _tui_logger.debug(  # type: ignore[unreachable]
                        f'_handle_input: _bootstrap done, state={self._controller.get_agent_state()}'
                    )
                    logger.info(
                        '[TUI] _handle_input: bootstrap complete, state=%s',
                        self._controller.get_agent_state(),
                    )
                    # Internal ready - no user-facing message
                else:
                    _tui_logger.debug(
                        '_handle_input: controller exists, dispatch will ensure task'
                    )
                    logger.info('[TUI] _handle_input: controller exists')
                assert self._controller is not None, (
                    'Controller must be initialized after agent task setup'
                )
                _tui_logger.debug('_handle_input: calling _dispatch_to_agent()')
                logger.info('[TUI] _handle_input: dispatching to agent')
                await self._dispatch_to_agent(text)
                _tui_logger.debug(
                    f'_handle_input: _dispatch_to_agent done, state={self._controller.get_agent_state()}'
                )
                logger.info(
                    '[TUI] _handle_input: dispatch complete, state=%s',
                    self._controller.get_agent_state() if self._controller else 'N/A',
                )
            except Exception as exc:
                _tui_logger.debug(f'_handle_input: EXCEPTION in try block: {exc}')
                logger.exception('[TUI] _handle_input FAILED')
                self.add_error(f'Agent error: {type(exc).__name__}: {exc}')
                self._render_hud_bar()
                if self._controller:
                    try:
                        actual = str(self._controller.get_agent_state())
                        self._hud.update_agent_state(actual or 'Error')
                        self._render_hud_bar()
                        self._render_hud_bar()
                    except Exception:
                        self._hud.update_agent_state('Error')
                        self._render_hud_bar()
                        self._render_hud_bar()
            finally:
                self.finalize_thinking()
                self._render_hud_bar()
                self.query_one('#input-bar', InputBar).remove_class('processing')
                if self._renderer:
                    self._renderer.drain_events()
                actual_state = (
                    str(self._controller.get_agent_state()) if self._controller else ''
                )
                self._hud.update_agent_state(actual_state or 'Ready')
                self._render_hud_bar()
                self._render_hud_bar()

    def update_hud(self) -> None:
        self._hud.update_agent_state(self._hud.state.agent_state_label or 'Ready')
        self._render_hud_bar()

    async def _handle_slash_command(self, text: str) -> None:
        raw = text.strip()
        if not raw:
            return
        try:
            parts = shlex.split(raw)
        except ValueError as exc:
            self.add_error(f'Invalid command syntax: {exc}')
            return
        if not parts:
            return
        cmd = parts[0].lower()
        args = parts[1:]
        if cmd in ('/help', '/h', '/?'):
            self.show_help()
        elif cmd in ('/clear', '/c'):
            self.clear_transcript()
        elif cmd in ('/quit', '/q', '/exit'):
            self._agent_running = False
            self.app.exit()
        elif cmd == '/settings':
            await self._open_settings_tui()
        elif cmd == '/sessions':
            await self._run_sessions_tui(args)
        elif cmd == '/resume':
            await self._run_resume_tui(args)
        else:
            self.add_error(f'Unknown command: {text}')

    async def _open_settings_tui(self) -> None:
        from backend.cli.config_manager import (
            get_current_model,
            update_api_key,
            update_budget,
            update_cli_tool_icons,
            update_model,
        )
        from backend.core.config import load_app_config

        result = await self.app.push_screen_wait(GrintaSettingsDialog(self._config))
        if not result:
            return
        try:
            update_model(str(result.get('model', '')).strip())
            api_key = str(result.get('api_key', '')).strip()
            if api_key:
                update_api_key(api_key)
            budget = result.get('budget')
            if budget is not None:
                update_budget(float(budget))
            update_cli_tool_icons(bool(result.get('icons', True)))
        except Exception as exc:
            logger.exception('[TUI] /settings failed to persist')
            self.add_error(f'/settings failed: {type(exc).__name__}: {exc}')
            return

        self._config = load_app_config()
        self._hud.update_model(get_current_model(self._config))
        mcp_servers = getattr(getattr(self._config, 'mcp', None), 'servers', []) or []
        mcp_count = sum(
            1 for server in mcp_servers if getattr(server, 'name', '') != 'app-mcp'
        )
        self._hud.update_mcp_servers(mcp_count)
        self._render_hud_bar()
        self.add_success('Settings updated.')

    async def _run_sessions_tui(self, args: list[str]) -> None:
        remaining = list(args)
        if remaining and remaining[0].lower() == 'list':
            remaining.pop(0)

        search = None
        sort_by = 'updated'
        limit = 20
        preview_idx = None
        delete_targets: list[str] = []

        i = 0
        while i < len(remaining):
            token = remaining[i]
            if token in ('--search', '-s') and i + 1 < len(remaining):
                search = remaining[i + 1]
                i += 2
                continue
            if token == '--sort' and i + 1 < len(remaining):
                allowed = ('updated', 'created', 'events', 'cost', 'model')
                if remaining[i + 1] not in allowed:
                    self.add_error(f'Sort must be one of: {", ".join(allowed)}')
                    return
                sort_by = remaining[i + 1]
                i += 2
                continue
            if token in ('--delete', '-d') and i + 1 < len(remaining):
                i += 1
                while i < len(remaining) and not remaining[i].startswith('-'):
                    delete_targets.append(remaining[i])
                    i += 1
                continue
            if token in ('--limit', '-l') and i + 1 < len(remaining):
                try:
                    limit = int(remaining[i + 1])
                except ValueError:
                    self.add_error('Limit must be a number.')
                    return
                if limit < 1:
                    self.add_error('Limit must be 1 or greater.')
                    return
                i += 2
                continue
            if token == '--preview' and i + 1 < len(remaining):
                preview_idx = remaining[i + 1]
                i += 2
                continue
            try:
                parsed_limit = int(token)
            except ValueError:
                self.add_error(f'Unknown option: {token}')
                return
            if parsed_limit < 1:
                self.add_error('Limit must be 1 or greater.')
                return
            limit = parsed_limit
            i += 1

        sid_to_resume = await self.app.push_screen_wait(
            GrintaSessionsDialog(
                self._config,
                search=search,
                sort_by=sort_by,
                limit=limit,
                preview_target=preview_idx,
                delete_targets=delete_targets,
            )
        )
        if sid_to_resume:
            await self._resume_session_target(sid_to_resume)

    async def _run_resume_tui(self, args: list[str]) -> None:
        if len(args) != 1:
            self.add_error('Usage: /resume <N|session_id>')
            return
        await self._resume_session_target(args[0])

    async def _resume_session_target(self, target: str) -> None:
        from backend.cli.session_manager import resolve_session_id

        cleaned_target = (target or '').strip()
        if not cleaned_target:
            self.add_error('Usage: /resume <N|session_id>')
            return

        resolved_id, resolve_error = resolve_session_id(cleaned_target, self._config)
        if resolve_error or resolved_id is None:
            self.add_error(resolve_error or f'No session matches: {cleaned_target}')
            return

        self.add_system_message(f'Resuming session: {resolved_id}')
        self._phase_label = 'Loading…'
        self._phase_started_at = time.monotonic()
        self._render_hud_bar()
        input_bar = self.query_one('#input-bar', InputBar)
        input_bar.add_class('processing')
        try:
            if self._bootstrapping is not None and not self._bootstrapping.is_set():
                await self._bootstrapping.wait()
            await self._teardown_active_session()
            await self._bootstrap(session_id=resolved_id)
            if self._controller is None:
                raise RuntimeError('Resume bootstrap did not initialize controller.')
        except Exception as exc:
            logger.exception('[TUI] /resume failed')
            self.add_error(f'Resume failed: {type(exc).__name__}: {exc}')
        else:
            self.add_success(
                f'Session {resolved_id[:12]} resumed. Send a message to continue.'
            )
        finally:
            input_bar.remove_class('processing')
            self.finalize_thinking()
            self._render_hud_bar()

    async def _teardown_active_session(self) -> None:
        old_task = self._agent_task
        self._agent_task = None
        if old_task is not None and not old_task.done():
            old_task.cancel()
            with contextlib.suppress(
                asyncio.CancelledError, asyncio.TimeoutError, Exception
            ):
                await asyncio.wait_for(old_task, timeout=5.0)

        old_controller = self._controller
        self._controller = None
        if old_controller is not None:
            mark_interrupt = getattr(old_controller, 'mark_user_interrupt_stop', None)
            if callable(mark_interrupt):
                with contextlib.suppress(Exception):
                    mark_interrupt()
            stop_fn = getattr(old_controller, 'stop', None)
            if callable(stop_fn):
                with contextlib.suppress(asyncio.TimeoutError, Exception):
                    await asyncio.wait_for(stop_fn(), timeout=5.0)

        old_runtime = self._runtime_stub
        self._runtime_stub = None
        if old_runtime is not None:
            rebind = getattr(old_runtime, 'rebind_event_stream', None)
            if callable(rebind):
                with contextlib.suppress(Exception):
                    rebind(None)
            close_runtime = getattr(old_runtime, 'close', None)
            if callable(close_runtime):
                with contextlib.suppress(Exception):
                    close_runtime()

        old_stream = self._event_stream
        self._event_stream = None
        if old_stream is not None:
            with contextlib.suppress(Exception):
                old_stream.unsubscribe(EventStreamSubscriber.CLI, old_stream.sid)
            close_fn = getattr(old_stream, 'close', None)
            if callable(close_fn):
                with contextlib.suppress(Exception):
                    close_fn()
        self._memory_stub = None

    def show_help(self) -> None:
        self.app.push_screen(GrintaHelpDialog())

    # ── Bootstrap (preserved agent logic) ───────────────────────────────────

    async def _bootstrap(self, session_id: str | None = None) -> None:
        _tui_logger.debug('_bootstrap: start')
        logger.info('TUI _bootstrap: starting')
        self._hud.update_agent_state('Initializing')
        self._render_hud_bar()
        self._render_hud_bar()

        _bootstrapping = asyncio.Event()
        self._bootstrapping = _bootstrapping

        config = self._config

        event_stream = None
        try:
            file_store = get_file_store(config)
            sid = session_id.strip() if session_id else generate_sid(config)
            event_stream = EventStream(sid=sid, file_store=file_store)
            self._event_stream = event_stream
            try:
                agent, runtime, conversation_stats = await asyncio.to_thread(
                    self._bootstrap_sync_phase1, config, event_stream
                )
            except Exception as exc:
                _tui_logger.debug(
                    f'_bootstrap: EXCEPTION phase1 {type(exc).__name__}: {exc}'
                )
                logger.exception('TUI _bootstrap: failed in phase1')
                raise
            if self._is_unmounted:
                _tui_logger.debug('_bootstrap: screen already unmounted, aborting')
                if event_stream is not None:
                    close_fn = getattr(event_stream, 'close', None)
                    if callable(close_fn):
                        close_fn()
                self._event_stream = None
                return

            _tui_logger.debug(
                f'_bootstrap: runtime created, type={type(runtime).__name__}'
            )

            connect_fn = getattr(runtime, 'connect', None)
            if callable(connect_fn):
                try:
                    _tui_logger.debug('_bootstrap: awaiting runtime.connect()')
                    await connect_fn()
                    _tui_logger.debug('_bootstrap: runtime.connect() OK')
                except Exception as exc:
                    _tui_logger.debug(
                        f'_bootstrap: runtime.connect() FAILED: {type(exc).__name__}: {exc}'
                    )
                    raise

            try:
                memory, controller = await asyncio.to_thread(
                    self._bootstrap_sync_phase2,
                    agent,
                    runtime,
                    event_stream,
                    config,
                    conversation_stats,
                )
            except Exception as exc:
                _tui_logger.debug(
                    f'_bootstrap: EXCEPTION phase2 {type(exc).__name__}: {exc}'
                )
                logger.exception('TUI _bootstrap: failed in phase2')
                raise

            # Warm up MCP servers (best-effort — failure is non-fatal)
            try:
                from backend.core.bootstrap.main import _setup_mcp_tools

                await _setup_mcp_tools(agent, runtime, memory)
                mcp_status = getattr(agent, 'mcp_capability_status', None) or {}
                try:
                    mcp_n = int(mcp_status.get('connected_client_count') or 0)
                except (TypeError, ValueError):
                    mcp_n = 0
                self._hud.update_mcp_servers(mcp_n)
            except Exception:
                _tui_logger.debug('_bootstrap: MCP warmup failed (non-fatal)')
                self._hud.update_mcp_servers(0)

            _tui_logger.debug(
                f'_bootstrap: controller created, state={controller.get_agent_state()}'
            )
            logger.info(
                'TUI _bootstrap: controller created, initial state=%s (type=%s)',
                controller.get_agent_state(),
                type(controller.get_agent_state()),
            )
            if self._is_unmounted:
                _tui_logger.debug(
                    '_bootstrap: screen unmounted after init, skipping subscribe'
                )
                if event_stream is not None:
                    close_fn = getattr(event_stream, 'close', None)
                    if callable(close_fn):
                        close_fn()
                self._event_stream = None
                return
            self._runtime_stub = runtime
            self._memory_stub = memory
            self._controller = controller

            from backend.utils.async_utils import set_main_event_loop

            set_main_event_loop(self._loop)
            _tui_logger.debug(f'_bootstrap: set_main_event_loop to {self._loop}')

            if self._renderer is None:
                import sys

                sys.stdin.isatty()
                self._renderer = TUIRenderer(
                    console=self._rich_console,
                    hud=self._hud,
                    reasoning=self._reasoning,
                    tui=self,
                    loop=self._loop,
                )
            self._renderer.subscribe(event_stream, event_stream.sid)

            state_after_create = controller.get_agent_state()
            _tui_logger.debug(f'_bootstrap: state after subscribe={state_after_create}')
            logger.info(
                'TUI _bootstrap: state after renderer subscribe=%s', state_after_create
            )
            # Show "Ready" once bootstrap completes — the agent is waiting for input
            self._hud.update_agent_state('awaiting_user_input')
            self._render_hud_bar()
            self._render_hud_bar()
            self._renderer.drain_events()
            _tui_logger.debug('_bootstrap: done')
        except BaseException:
            if event_stream is not None:
                close_fn = getattr(event_stream, 'close', None)
                if callable(close_fn):
                    try:
                        close_fn()
                    except Exception:
                        pass
            if self._event_stream is event_stream:
                self._event_stream = None
            raise
        finally:
            _bootstrapping.set()

    def _bootstrap_sync_phase1(
        self,
        config: Any,
        event_stream: Any,
    ) -> tuple[Any, Any, Any]:
        _tui_logger.debug(
            '_bootstrap_sync_phase1: create_registry_and_conversation_stats'
        )
        llm_registry, conv_stats, _app_cfg = create_registry_and_conversation_stats(
            config,
            sid=event_stream.sid,
            user_id='tui',
            retry_listener=self._make_llm_retry_listener(event_stream),
        )
        _tui_logger.debug('_bootstrap_sync_phase1: create_runtime')
        runtime = create_runtime(
            config,
            llm_registry=llm_registry,
            sid=event_stream.sid,
            event_stream=event_stream,
        )
        _tui_logger.debug('_bootstrap_sync_phase1: create_agent')
        agent = create_agent(config, llm_registry)
        _tui_logger.debug('_bootstrap_sync_phase1: done')
        return agent, runtime, conv_stats

    def _make_llm_retry_listener(self, event_stream: Any):
        def _listener(attempt: int, max_attempts: int, **kwargs: Any) -> None:
            status_type = str(kwargs.get('status_type') or 'llm_retry_pending')
            reason = str(kwargs.get('reason') or 'transient failure')
            wait_seconds = kwargs.get('wait_seconds')
            extras = {
                'attempt': attempt,
                'max_attempts': max_attempts,
                'reason': reason,
                'source': kwargs.get('source') or 'llm',
                'streaming': bool(kwargs.get('streaming', False)),
            }
            if wait_seconds is not None:
                extras['delay_seconds'] = wait_seconds
            try:
                event_stream.add_event(
                    StatusObservation(
                        content='',
                        status_type=status_type,
                        extras=extras,
                    ),
                    EventSource.ENVIRONMENT,
                )
            except Exception:
                logger.debug('Failed to emit LLM retry status event', exc_info=True)

        return _listener

    def _bootstrap_sync_phase2(
        self,
        agent: Any,
        runtime: Any,
        event_stream: Any,
        config: Any,
        conversation_stats: Any,
    ) -> tuple[Any, Any]:
        _tui_logger.debug('_bootstrap_sync_phase2: create_memory')
        memory = create_memory(runtime, event_stream, sid=event_stream.sid)
        _tui_logger.debug('_bootstrap_sync_phase2: create_memory done')
        _tui_logger.debug('_bootstrap_sync_phase2: controller')
        controller = self._get_or_create_controller(
            agent,
            runtime,
            memory,
            event_stream,
            config,
            conversation_stats,
        )
        _tui_logger.debug('_bootstrap_sync_phase2: controller done')
        return memory, controller

    def _get_or_create_controller(
        self,
        agent: Any,
        runtime: Any,
        memory: Any,
        event_stream: Any,
        config: Any,
        conversation_stats: Any,
    ) -> Any:
        controller, _initial_state = create_controller(
            agent=agent,
            runtime=runtime,
            config=config,
            conversation_stats=conversation_stats,
            headless_mode=True,
        )
        return controller

    async def _run_agent_loop(self) -> None:
        if self._controller is None:
            _tui_logger.debug('_run_agent_loop: no controller, aborting')
            return
        _tui_logger.debug('_run_agent_loop: ENTER')
        end_states = [
            AgentState.AWAITING_USER_INPUT,
            AgentState.FINISHED,
            AgentState.ERROR,
            AgentState.STOPPED,
        ]
        try:
            _tui_logger.debug('_run_agent_loop: calling run_agent_until_done')
            await run_agent_until_done(
                self._controller,
                self._runtime_stub,
                self._memory_stub,
                end_states,
            )
            _tui_logger.debug('_run_agent_loop: run_agent_until_done returned')
        except Exception as exc:
            _tui_logger.debug(f'_run_agent_loop: EXCEPTION {type(exc).__name__}: {exc}')
            logger.exception('Agent loop exited with error')
        _tui_logger.debug('_run_agent_loop: EXIT')

    async def _ensure_agent_task(self) -> None:
        if self._controller is None:
            _tui_logger.debug('_ensure_agent_task: no controller, returning')
            return

        state = self._controller.get_agent_state()
        _tui_logger.debug(f'_ensure_agent_task: current state={state}')
        logger.info('TUI _ensure_agent_task: current state=%s', state)
        if state in {
            AgentState.LOADING,
            AgentState.AWAITING_USER_INPUT,
            AgentState.FINISHED,
            AgentState.ERROR,
            AgentState.REJECTED,
            AgentState.STOPPED,
        }:
            _tui_logger.debug(f'_ensure_agent_task: transitioning {state} -> RUNNING')
            logger.info('TUI _ensure_agent_task: transitioning %s -> RUNNING', state)
            await self._controller.set_agent_state_to(AgentState.RUNNING)
        elif state == AgentState.RUNNING:
            _tui_logger.debug('_ensure_agent_task: already RUNNING')
            logger.info('TUI _ensure_agent_task: already RUNNING')

        state_after = self._controller.get_agent_state()
        _tui_logger.debug(f'_ensure_agent_task: state after transition={state_after}')
        logger.info('TUI _ensure_agent_task: state after transition=%s', state_after)

        if self._agent_task is None or self._agent_task.done():
            _tui_logger.debug('_ensure_agent_task: creating new agent task')
            logger.info('TUI _ensure_agent_task: creating new agent task')
            self._agent_task = asyncio.create_task(
                run_agent_until_done(
                    self._controller,
                    self._runtime_stub,
                    self._memory_stub,
                    [
                        AgentState.AWAITING_USER_INPUT,
                        AgentState.FINISHED,
                        AgentState.ERROR,
                        AgentState.STOPPED,
                    ],
                ),
                name='grinta-tui-agent',
            )

            def _on_agent_done(t: asyncio.Task[Any]) -> None:
                if t.cancelled():
                    _tui_logger.debug('_agent_task cancelled')
                    return
                exc = t.exception()
                if exc:
                    _tui_logger.debug(
                        f'_agent_task FAILED: {type(exc).__name__}: {exc}'
                    )
                    logger.exception('TUI _agent_task failed')
                else:
                    _tui_logger.debug('_agent_task completed OK')

            self._agent_task.add_done_callback(_on_agent_done)
        else:
            _tui_logger.debug(
                f'_ensure_agent_task: agent task already running task={self._agent_task}'
            )
            logger.info(
                'TUI _ensure_agent_task: agent task already running (task=%s)',
                self._agent_task,
            )

    async def _dispatch_to_agent(self, text: str) -> None:
        _tui_logger.debug('_dispatch_to_agent: ENTER')
        if self._controller is None or self._event_stream is None:
            _tui_logger.debug(
                '_dispatch_to_agent: missing controller or event_stream, returning'
            )
            return

        action = MessageAction(content=text)
        self._event_stream.add_event(action, EventSource.USER)
        _tui_logger.debug('_dispatch_to_agent: event added')
        try:
            logger.info('[TUI] _dispatch_to_agent: event added')
        except Exception as exc:
            _tui_logger.debug(
                f'_dispatch_to_agent: logger.info FAILED: {type(exc).__name__}: {exc}'
            )
        try:
            await self._ensure_agent_task()
            _tui_logger.debug('_dispatch_to_agent: _ensure_agent_task OK')
        except Exception as exc:
            _tui_logger.debug(
                f'_dispatch_to_agent: _ensure_agent_task FAILED: {type(exc).__name__}: {exc}'
            )
            raise
        try:
            end_states = {
                AgentState.AWAITING_USER_INPUT,
                AgentState.FINISHED,
                AgentState.ERROR,
                AgentState.STOPPED,
                AgentState.AWAITING_USER_CONFIRMATION,
            }
            _tui_logger.debug('_dispatch_to_agent: end_states created')
        except Exception as exc:
            _tui_logger.debug(
                f'_dispatch_to_agent: end_states FAILED: {type(exc).__name__}: {exc}'
            )
            raise
        loop_count = 0
        import time as _time

        _poll_started = _time.monotonic()
        _max_poll_seconds = 3600  # 1 hour hard cap for the polling loop
        while True:
            _tui_logger.debug('_dispatch_to_agent: entering poll loop')
            while True:
                try:
                    if self._renderer is not None:
                        await self._renderer.wait_for_activity(wait_timeout_sec=0.5)
                    else:
                        await asyncio.sleep(0.5)
                    loop_count += 1
                    state = self._controller.get_agent_state()
                    if loop_count == 1 or loop_count % 20 == 0:
                        _tui_logger.debug(
                            f'_dispatch_to_agent: poll #{loop_count}, state={state}'
                        )
                        logger.info(
                            '[TUI] _dispatch_to_agent: poll #%d, state=%s',
                            loop_count,
                            state,
                        )
                    if state in end_states:
                        _tui_logger.debug(
                            f'_dispatch_to_agent: reached end state {state}'
                        )
                        logger.info(
                            '[TUI] _dispatch_to_agent: reached end state %s', state
                        )
                        break
                    if self._agent_task and self._agent_task.done():
                        _tui_logger.debug(
                            f'_dispatch_to_agent: agent task done, state={state}'
                        )
                        logger.info(
                            '[TUI] _dispatch_to_agent: agent task done, state=%s', state
                        )
                        break
                    # Hard timeout: prevent infinite polling if the agent gets stuck.
                    if _time.monotonic() - _poll_started > _max_poll_seconds:
                        _tui_logger.debug('_dispatch_to_agent: poll timeout reached')
                        logger.error(
                            '[TUI] _dispatch_to_agent: poll timeout after %.0fs in state=%s',
                            _max_poll_seconds,
                            state,
                        )
                        self.add_error('Agent timed out — check app.log')
                        break
                except Exception as exc:
                    _tui_logger.debug(
                        f'_dispatch_to_agent: poll loop EXCEPTION {type(exc).__name__}: {exc}'
                    )
                    raise
            if state == AgentState.AWAITING_USER_CONFIRMATION:
                await self._handle_confirmation_dialog()
                continue
            break
        _tui_logger.debug('_dispatch_to_agent: poll loop exited')
        if self._renderer:
            self._renderer.drain_events()

    # ── Confirmation ────────────────────────────────────────────────────────

    _ACTION_TYPE_LABELS: dict[str, str] = {
        'CmdRunAction': 'Run Command',
        'FileWriteAction': 'Write File',
        'FileEditAction': 'Edit File',
        'FileReadAction': 'Read File',
        'FileEditActionMulti': 'Edit File',
        'MCPAction': 'MCP Tool',
        'BrowserToolAction': 'Browser',
        'DelegateTaskAction': 'Delegate',
        'MessageAction': 'Message',
        'FinishAction': 'Finish',
        'SystemMessageAction': 'System',
        'NoteAction': 'Note',
    }

    _RISK_LABELS: dict[str, tuple[str, str]] = {
        'UNKNOWN': ('Unknown', 'dim'),
        'LOW': ('Low', 'green'),
        'MEDIUM': ('Medium', 'yellow'),
        'HIGH': ('High', 'bold red'),
    }

    async def _handle_confirmation_dialog(self) -> None:
        """Show inline confirmation widget and wait for user decision."""
        pending = None
        try:
            action_service = getattr(self._controller, 'action_service', None)
            if action_service is not None:
                pending = action_service.get_pending_action()
        except Exception:
            pass

        action_type_raw = type(pending).__name__ if pending else 'Unknown'
        action_type = self._ACTION_TYPE_LABELS.get(action_type_raw, action_type_raw)
        target = ''
        risk_raw = 'UNKNOWN'

        if pending:
            if hasattr(pending, 'command') and pending.command:
                target = pending.command
            elif hasattr(pending, 'path') and pending.path:
                target = pending.path

            risk = getattr(pending, 'security_risk', None)
            if risk is not None:
                risk_raw = str(risk)

        risk_label, risk_class = self._RISK_LABELS.get(
            risk_raw, ('· Unknown', 'confirm-risk-unknown')
        )

        options: list[tuple[str, str]] = [
            ('approve', 'Approve'),
            ('reject', 'Reject'),
        ]

        ac = getattr(self._controller, 'autonomy_controller', None)
        if ac is not None and hasattr(ac, 'remember_always_allow'):
            options.append(('always', 'Always'))

        widget = self.query_one('#confirm-widget', ConfirmWidget)
        widget.configure(
            action_type, risk_label, risk_class, target, options, recommended=0
        )
        widget.show()
        try:
            result = await widget.wait_for_decision()
        finally:
            widget.hide()

        if result == 'approve':
            decision = AgentState.USER_CONFIRMED
        elif result == 'always':
            decision = AgentState.USER_CONFIRMED
            if ac is not None and pending is not None:
                ac.remember_always_allow(pending)
        else:
            decision = AgentState.USER_REJECTED

        action = ChangeAgentStateAction(agent_state=decision)
        self._event_stream.add_event(action, EventSource.USER)


# ── TUIRenderer ───────────────────────────────────────────────────────────


class TUIRenderer:
    """Rich-driven renderer for Textual — manages history and real-time display."""

    _FILE_EDIT_VERBS: dict[str, tuple[str, bool]] = {
        'create_file': ('Created', False),
        'replace_string': ('Edited', False),
        'multi_edit': ('Edited', False),
    }

    def __init__(
        self,
        console: Any,
        hud: HUDBar,
        reasoning: ReasoningDisplay,
        tui: GrintaScreen,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._console = console
        self._hud = hud
        self._reasoning = reasoning
        self._tui = tui
        self._loop = loop
        self._event_stream: Any | None = None
        self._state_event = asyncio.Event()
        self._current_state: Any = None
        self._pending_events: deque[Any] = deque()
        self._pending_lock = threading.Lock()
        self._drain_scheduled = False
        self._pending_events_dropped = 0

        # History & Live state
        self._live_thinking_widget: Any | None = None
        self._live_response_widget: Any | None = None
        self._task_list: list[dict[str, Any]] = []
        self._last_sidebar_state: Any = None

        # Unit test compatibility
        self._history: list[Any] = []
        self._history_items_dropped: int = 0
        self._live_thinking: str = ''
        self._live_thinking_dirty: bool = False
        self._live_response: str = ''
        self._live_response_dirty: bool = False
        self._last_final_response_text: str = ''

        # Turn tracking for grouping tool calls by agent turn
        self._turn_count: int = 0
        self._in_agent_turn: bool = False
        self._tools_in_turn: int = 0
        self._turn_start_time: float = 0.0
        self._terminal_cards_by_session: dict[str, Any] = {}
        self._terminal_commands_by_session: dict[str, str] = {}
        self._pending_terminal_command: str | None = None
        self._pending_terminal_card: Any | None = None
        self._pending_shell_cards_by_command: dict[str, deque[Any]] = defaultdict(deque)
        self._active_worker_tasks: list[str] = []
        self._worker_recent_results: deque[str] = deque(maxlen=3)
        self._worker_completed: int = 0
        self._worker_failed: int = 0
        self._condensation_count: int = 0
        self._last_browser_action_card: Any | None = None
        self._last_browser_cmd: str = ''

    def subscribe(self, event_stream: Any, sid: str) -> None:
        self._event_stream = event_stream
        event_stream.subscribe(EventStreamSubscriber.CLI, self._on_event, sid)

    def add_to_history(self, renderable: Any) -> None:
        """Add a finalized renderable or widget to the transcript."""
        self._history.append(renderable)
        self._history.append(Text(''))
        overflow = len(self._history) - _TUI_HISTORY_RENDER_LIMIT
        if overflow > 0:
            del self._history[:overflow]
            self._history_items_dropped += overflow

        self.commit_live_thinking()
        self.clear_live_response()

        display = self._tui._get_display()
        if type(display).__name__ == 'MagicMock':
            display.write(renderable)
        else:
            from textual.widget import Widget

            if isinstance(renderable, Widget):
                display.append_widget(renderable)
            else:
                display.append_widget(Static(renderable))
        self._refresh_display()

    def update_live_thinking(self, text: str) -> None:
        """Update the real-time reasoning preview in-place."""
        self._live_thinking = text
        self._live_thinking_dirty = bool(text.strip())

        if text.strip():
            self._clear_last_active_card_processing()

        display = self._tui._get_display()
        if type(display).__name__ == 'MagicMock':
            display.clear()
            display.write(text)
            return

        if not text.strip():
            return

        if not self._live_thinking_widget:
            from backend.cli.tui.widgets.activity_card import ThinkingIndicator

            self._live_thinking_widget = ThinkingIndicator()
            display.append_widget(self._live_thinking_widget)
            self._live_thinking_widget.start()

        self._live_thinking_widget.set_thoughts(text)
        if not display._user_scrolled_away:
            display.scroll_end(animate=False)

    def update_live_response(self, text: str) -> None:
        """Update the in-flight assistant response in-place."""
        self._live_response = text
        self._live_response_dirty = bool(text.strip())

        if text.strip():
            self._clear_last_active_card_processing()

        display = self._tui._get_display()
        if type(display).__name__ == 'MagicMock':
            if not self._live_response_dirty:
                self.clear_live_response()
                return
            display.clear()
            display.write(text)
            return

        if not text.strip():
            self.clear_live_response()
            return

        if not self._live_response_widget:
            from backend.cli.tui.widgets.activity_card import AgentMessage

            self._live_response_widget = AgentMessage(text)
            display.append_widget(self._live_response_widget)
        else:
            self._live_response_widget.update_message(text)
            if not display._user_scrolled_away:
                display.scroll_end(animate=False)

    def clear_live_response(self) -> None:
        """Clear the in-flight response preview widget."""
        self._live_response = ''
        self._live_response_dirty = False

        display = self._tui._get_display()
        if type(display).__name__ == 'MagicMock':
            display.clear()
            return

        if self._live_response_widget:
            self._live_response_widget.remove()
            self._live_response_widget = None

    def commit_live_thinking(self) -> None:
        """Commit live reasoning into transcript as a CollapsibleSection."""
        display = self._tui._get_display()
        if type(display).__name__ == 'MagicMock':
            if self._live_thinking_dirty:
                if self._live_thinking.strip():
                    self._history.append(self._live_thinking)
                    display.write(self._live_thinking)
            self._live_thinking = ''
            self._live_thinking_dirty = False
            return

        if self._live_thinking_widget:
            self._live_thinking_widget.stop()
            thoughts = list(self._live_thinking_widget._thoughts)
            self._live_thinking_widget.remove()
            self._live_thinking_widget = None

            if thoughts and self._live_thinking_dirty:
                display = self._tui._get_display()
                if type(display).__name__ != 'MagicMock':
                    content = Text('\n  '.join(thoughts), style='rgb(150,154,189)')
                    display.append_widget(
                        Static(
                            Text.assemble(
                                ('Thinking:', 'bold #5eead4'),
                                '  ',
                                content,
                            )
                        )
                    )
            self._live_thinking_dirty = False

            self._live_thinking = ''
            self._live_thinking_dirty = False

    def clear_history(self) -> None:
        self._live_thinking_widget = None
        self._live_response_widget = None
        self._terminal_cards_by_session = {}
        self._terminal_commands_by_session = {}
        self._pending_terminal_command = None
        self._pending_terminal_card = None
        self._pending_shell_cards_by_command = defaultdict(deque)
        self._active_worker_tasks = []
        self._worker_recent_results.clear()
        self._worker_completed = 0
        self._worker_failed = 0
        self._history = []
        self._history_items_dropped = 0
        self._live_thinking = ''
        self._live_thinking_dirty = False
        self._live_response = ''
        self._live_response_dirty = False
        try:
            self._tui._get_display().clear()
        except (AttributeError, NoMatches):
            pass
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Refresh derived sidebar state; transcript writes are incremental."""
        from backend.cli._event_renderer.sidebar import _load_playbook_skills
        from backend.cli.tui.widgets.collapsible import CollapsibleSection

        _TASK_TO_SIDEBAR_STATUS = {
            'done': 'ok',
            'doing': 'running',
            'blocked': 'err',
            'todo': 'neutral',
            'skipped': 'warn',
        }

        mcp_count = self._hud.state.mcp_servers
        skill_count = self._hud.bundled_skill_count

        # Build actual MCP server list from config
        mcp_servers = None
        if (
            self._tui._config
            and getattr(self._tui._config, 'mcp', None)
            and getattr(self._tui._config.mcp, 'servers', None)
        ):
            mcp_servers = [
                {'name': s.name, 'type': s.type}
                for s in self._tui._config.mcp.servers
                if s.name != 'app-mcp'
            ]

        if not mcp_servers and mcp_count:
            mcp_servers = [
                {'name': f'MCP Server {i + 1}', 'type': 'active'}
                for i in range(mcp_count)
            ]

        task_signature = task_panel_signature(self._task_list)
        current_state = (task_signature, mcp_servers, skill_count)
        if current_state != self._last_sidebar_state:
            # 1. Update Tasks Section
            try:
                tasks_widget = self._tui.query_one('#sidebar-tasks', CollapsibleSection)
                task_items = []
                for task_id, status, desc in task_signature:
                    item_status = _TASK_TO_SIDEBAR_STATUS.get(status, 'neutral')
                    meta = task_id if task_id and task_id != '?' else None
                    task_items.append(
                        (desc, f'task:{task_id}', False, item_status, meta)
                    )

                tasks_widget.set_title(f'Tasks ({len(task_signature)})')
                tasks_widget.set_items(task_items)
            except Exception:
                pass

            # 2. Update MCP Servers Section
            try:
                mcp_widget = self._tui.query_one('#sidebar-mcp', CollapsibleSection)
                mcp_items = []
                if mcp_servers:
                    for server in mcp_servers:
                        name = server.get('name', 'unknown')
                        server_type = server.get('type', 'stdio')
                        mcp_items.append(
                            (name, f'mcp:{name}', True, 'info', server_type)
                        )

                mcp_widget.set_title(
                    f'MCP Servers ({len(mcp_servers) if mcp_servers else 0})'
                )
                mcp_widget.set_items(mcp_items)
            except Exception:
                pass

            # 3. Update Skills Section
            try:
                skills_widget = self._tui.query_one(
                    '#sidebar-skills', CollapsibleSection
                )
                skills_list = _load_playbook_skills()
                skill_items = []
                if skills_list:
                    for skill in sorted(skills_list):
                        skill_items.append(
                            (skill, f'skill:{skill}', True, 'neutral', None)
                        )

                skills_widget.set_title(f'Skills ({len(skills_list)})')
                skills_widget.set_items(skill_items)
            except Exception:
                pass

            self._last_sidebar_state = current_state

    def _write_lines(self, lines: list[Any]) -> None:
        from rich.text import Text

        items = []
        for line in lines:
            if isinstance(line, str):
                items.append(Text.from_markup(line))
            else:
                items.append(line)
        self.add_to_history(Group(*items))

    def _clear_last_active_card_processing(self) -> None:
        """Clear the pulsing processing indicator on the last active card."""
        if hasattr(self, '_last_active_card') and self._last_active_card:
            try:
                self._last_active_card.set_processing(False)
            except Exception:
                pass
            self._last_active_card = None
        clear_current_operation = getattr(self._tui, 'clear_current_operation', None)
        if callable(clear_current_operation):
            clear_current_operation()

    def _update_retry_strip(self, summary: str, meta: str) -> None:
        self._tui.set_retry_status(summary, meta=meta, active=True)

    def _clear_retry_strip(self, meta: str = 'Idle') -> None:
        self._tui.clear_retry_status(meta=meta)

    def _update_runtime_strip(
        self, summary: str, meta: str, *, active: bool = False
    ) -> None:
        self._tui.set_runtime_status(summary, meta=meta, active=active)

    def _clear_runtime_strip(self, meta: str = 'Idle') -> None:
        self._tui.clear_runtime_status(meta=meta)

    @staticmethod
    def _summarize_worker_task(task: str) -> str:
        compact = re.sub(r'\s+', ' ', (task or '').strip())
        if not compact:
            return 'delegated task'
        return compact[:72] + ('...' if len(compact) > 72 else '')

    def _sync_worker_strip(self) -> None:
        active = len(self._active_worker_tasks)
        if active:
            summary = f'{active} worker{"s" if active != 1 else ""} active'
            meta_parts = [
                ' | '.join(self._active_worker_tasks[:2]),
                f'done {self._worker_completed}',
            ]
            if self._worker_failed:
                meta_parts.append(f'failed {self._worker_failed}')
            self._tui.set_worker_status(
                summary,
                meta='  •  '.join(part for part in meta_parts if part),
                active=True,
                has_error=self._worker_failed > 0,
            )
            return

        if self._worker_completed or self._worker_failed:
            summary = 'Workers idle'
            meta_parts = [f'done {self._worker_completed}']
            if self._worker_failed:
                meta_parts.append(f'failed {self._worker_failed}')
            if self._worker_recent_results:
                meta_parts.append('latest: ' + ' | '.join(self._worker_recent_results))
            self._tui.set_worker_status(
                summary,
                meta='  •  '.join(meta_parts),
                active=False,
                has_error=self._worker_failed > 0,
            )
            return

        self._tui.set_worker_status(
            'No delegated work', meta='Idle', active=False, has_error=False
        )

    def _write_card(
        self,
        card: ActivityCard,
        *,
        collapsed: bool = True,
    ) -> Any:
        """Write an activity card to the transcript using native ActivityCard widget."""
        self._clear_last_active_card_processing()

        extra_content = None
        if card.extra_lines:
            extra_parts = []
            for extra in card.extra_lines:
                indent = '  ' * extra.indent
                extra_parts.append(f'{indent}{extra.text}')
            extra_content = '\n'.join(extra_parts)

        from backend.cli.tui.widgets.activity_card import (
            ActivityCard as TUIActivityCard,
        )

        status_map = {
            'ok': 'ok',
            'err': 'err',
            'warn': 'warn',
            'neutral': 'neutral',
        }
        status = status_map.get(card.secondary_kind, 'neutral')
        widget = TUIActivityCard(
            verb=card.verb,
            detail=card.detail,
            badge_category=card.badge_category,
            status=status,
            outcome=card.secondary,
            extra_content=extra_content,
            collapsed=collapsed,
        )

        is_tool = card.badge_category in (
            'tool',
            'shell',
            'terminal',
            'files',
            'browser',
            'mcp',
            'workers',
            'code',
        )
        is_active = is_tool and (not card.secondary or card.secondary_kind == 'neutral')
        if is_active:
            widget.set_processing(True)
            self._clear_last_active_card_processing()
            widget.set_processing(True)
            self._last_active_card = widget
            self._tui.set_current_operation(
                f'{card.verb} {card.detail}'.strip(),
                meta=card.secondary or 'Running',
                active=True,
            )
        else:
            if self._last_active_card is widget:
                self._last_active_card = None
            self._tui.set_current_operation(
                f'{card.verb} {card.detail}'.strip(),
                meta=card.secondary or 'Completed',
                active=False,
            )

        display = self._tui._get_display()
        display.append_widget(widget)
        return widget

    def _write_tui_file_card(
        self,
        verb: str,
        detail: str,
        *,
        secondary: str | None = None,
        secondary_kind: str = 'neutral',
        extra_content: str | None = None,
        collapsed: bool = False,
    ) -> None:
        from backend.cli.tui.widgets.activity_card import (
            ActivityCard as TUIActivityCard,
        )

        self._clear_last_active_card_processing()
        status_map = {'ok': 'ok', 'err': 'err', 'warn': 'warn', 'neutral': 'neutral'}
        status = status_map.get(secondary_kind, 'neutral')
        widget = TUIActivityCard(
            verb=verb,
            detail=detail,
            badge_category='files',
            status=status,
            outcome=secondary,
            extra_content=extra_content,
            collapsed=collapsed,
            diff_encoded=True,
        )
        self._tui.set_current_operation(
            f'{verb} {detail}'.strip(),
            meta=secondary or 'Completed',
            active=False,
        )
        display = self._tui._get_display()
        display.append_widget(widget)

    def _remember_terminal_command(self, session_id: str, command: str) -> None:
        """Remember the most relevant command for a terminal session."""
        clean_command = _sanitize_terminal_display_text(command or '').strip()
        if not clean_command:
            return
        if session_id:
            self._terminal_commands_by_session[session_id] = clean_command
            if self._pending_terminal_command == clean_command:
                self._pending_terminal_command = None
            return
        self._pending_terminal_command = clean_command

    def _resolve_terminal_command(self, session_id: str = '') -> str | None:
        """Resolve the active command for a terminal session, if known."""
        if session_id:
            command = self._terminal_commands_by_session.get(session_id)
            if command:
                return command
            if self._pending_terminal_command:
                command = self._pending_terminal_command
                self._terminal_commands_by_session[session_id] = command
                self._pending_terminal_command = None
                return command
            return None
        return self._pending_terminal_command

    def _terminal_card_detail(self, session_id: str = '', command: str = '') -> str:
        """Build a stable terminal card headline."""
        if command.strip():
            self._remember_terminal_command(session_id, command)
        active_command = self._resolve_terminal_command(session_id)
        if active_command:
            preview = active_command[:80] + ('...' if len(active_command) > 80 else '')
            return f'$ {preview}'
        if session_id:
            return f'session {session_id}'
        return 'terminal session'

    @staticmethod
    def _terminal_session_label(session_id: str) -> str | None:
        """Format the session label used in terminal card secondary text."""
        return f'session {session_id}' if session_id else None

    def _upsert_terminal_session_card(
        self,
        *,
        session_id: str,
        verb: str,
        detail: str,
        secondary: str | None = None,
        secondary_kind: str = 'neutral',
        extra_content: str | None = None,
        processing: bool = True,
        collapse_after_update: bool = False,
    ) -> None:
        session_key = session_id or 'terminal'
        widget = self._terminal_cards_by_session.get(session_key)
        if widget is None and session_id and self._pending_terminal_card is not None:
            widget = self._pending_terminal_card
            self._terminal_cards_by_session[session_key] = widget
            self._pending_terminal_card = None
        if widget is None:
            card = ActivityRenderer.terminal_action(
                verb,
                detail,
                secondary=secondary,
                secondary_kind=secondary_kind,
                extra_content=extra_content,
            )
            widget = self._write_card(card, collapsed=collapse_after_update)
            if session_id:
                self._terminal_cards_by_session[session_key] = widget
            else:
                self._pending_terminal_card = widget
            return

        # Update existing widget for same session
        widget.set_verb(verb, detail=detail)
        widget.set_status(
            'ok'
            if secondary_kind == 'ok'
            else 'err'
            if secondary_kind == 'err'
            else 'neutral',
            outcome=secondary,
        )
        if extra_content:
            widget.append_content(extra_content)

        if collapse_after_update:
            widget.set_collapsed(True)

        widget.set_processing(processing)
        if processing:
            self._clear_last_active_card_processing()
            widget.set_processing(True)
            self._last_active_card = widget
            self._tui.set_current_operation(
                f'{verb} {detail}'.strip(),
                meta=secondary or f'session {session_key}',
                active=True,
            )
        else:
            if self._last_active_card is widget:
                self._last_active_card = None
            self._tui.set_current_operation(
                f'{verb} {detail}'.strip(),
                meta=secondary or f'session {session_key}',
                active=False,
            )

    def _create_shell_command_card(self, command: str) -> Any:
        from backend.cli.tui.widgets.activity_card import (
            ActivityCard as TUIActivityCard,
        )

        card = ActivityRenderer.shell_command(command)
        widget = TUIActivityCard(
            verb=card.verb,
            detail=card.detail,
            badge_category=card.badge_category,
            status='running',
            outcome=card.secondary,
            extra_content=None,
            collapsed=True,
        )
        widget.set_processing(True)
        self._clear_last_active_card_processing()
        self._last_active_card = widget
        self._pending_shell_cards_by_command[command].append(widget)
        self._tui.set_current_operation(
            f'{card.verb} {card.detail}'.strip(),
            meta='running',
            active=True,
        )
        display = self._tui._get_display()
        display.mount(widget)
        display.scroll_end(animate=False)
        return widget

    def _complete_shell_command_card(
        self,
        command: str,
        *,
        output: str,
        exit_code: int | None,
        cwd: str | None = None,
    ) -> None:
        queue = self._pending_shell_cards_by_command.get(command)
        widget = queue.popleft() if queue else None
        if queue is not None and not queue:
            self._pending_shell_cards_by_command.pop(command, None)

        card = ActivityRenderer.shell_command(
            command, output=output, exit_code=exit_code
        )
        if widget is None:
            self._write_card(card)
            return

        if self._last_active_card is widget:
            self._last_active_card = None

        status = 'ok' if exit_code == 0 else 'err'
        widget.set_status(status, outcome=card.secondary)

        # Build expanded content with metadata header per spec
        meta_lines = [f'$ {command}']
        if cwd:
            meta_lines.append(f'cwd: {cwd}')
        meta_lines.append(f'exit: {exit_code}')
        meta_lines.append('─' * 50)

        extra_parts = list(meta_lines)
        if card.extra_lines:
            for extra in card.extra_lines:
                indent = '  ' * extra.indent
                extra_parts.append(f'{indent}{extra.text}')
        extra_content = '\n'.join(extra_parts)

        widget.update_content(extra_content)
        widget.set_collapsed(False)
        widget.set_processing(False)
        self._tui.set_current_operation(
            f'{card.verb} {card.detail}'.strip(),
            meta=card.secondary or 'completed',
            active=False,
        )

    def drain_events(self) -> None:
        with self._pending_lock:
            events = list(self._pending_events)
            self._pending_events.clear()
            self._drain_scheduled = False
            dropped = self._pending_events_dropped
            self._pending_events_dropped = 0
        if not events:
            self._refresh_display()  # Keep sidebar/HUD in sync
            return
        if dropped:
            self._history.append(
                Text(
                    f'... {dropped} TUI event(s) dropped while the renderer was backlogged ...',
                    style=NAVY_TEXT_DIM,
                )
            )
            self._history.append(Text(''))
            overflow = len(self._history) - _TUI_HISTORY_RENDER_LIMIT
            if overflow > 0:
                del self._history[:overflow]
        for event in events:
            self._process_event(event)
        self._refresh_display()

    async def wait_for_activity(self, wait_timeout_sec: float = 0.5) -> Any:
        with self._pending_lock:
            has_pending = bool(self._pending_events)
        if has_pending:
            self.drain_events()
            self._state_event.clear()
            return self._current_state
        try:
            await asyncio.wait_for(self._state_event.wait(), timeout=wait_timeout_sec)
        except TimeoutError:
            return None
        finally:
            self._state_event.clear()
        self.drain_events()
        return self._current_state

    def _on_event(self, event: Any) -> None:
        should_schedule_drain = False
        with self._pending_lock:
            if len(self._pending_events) >= _TUI_PENDING_EVENT_LIMIT:
                self._pending_events.popleft()
                self._pending_events_dropped += 1
            self._pending_events.append(event)
            if not self._drain_scheduled:
                self._drain_scheduled = True
                should_schedule_drain = True
        try:
            self._loop.call_soon_threadsafe(
                self._signal_activity,
                should_schedule_drain,
            )
        except RuntimeError:
            pass

    def _signal_activity(self, should_schedule_drain: bool) -> None:
        self._state_event.set()
        if not should_schedule_drain:
            return
        try:
            self._tui.post_message(RendererDrainRequested())
        except Exception:
            with self._pending_lock:
                self._drain_scheduled = False

    def _process_event(self, event: Any) -> None:
        self._update_metrics(event)
        if isinstance(event, NullAction) or isinstance(event, NullObservation):
            return

        source = getattr(event, 'source', None)

        # Detect start of agent turn (first tool action after user input)
        if not self._in_agent_turn and not isinstance(
            event, (MessageAction, StreamingChunkAction, AgentStateChangedObservation)
        ):
            self._in_agent_turn = True
            self._turn_count += 1
            self._tools_in_turn = 0
            self._turn_start_time = time.monotonic()

        # Count tools in current turn
        if self._in_agent_turn and isinstance(
            event,
            (
                FileReadAction,
                FileEditAction,
                FileWriteAction,
                CmdRunAction,
                MCPAction,
                BrowserToolAction,
                BrowseInteractiveAction,
                LspQueryAction,
                TerminalRunAction,
                TerminalInputAction,
                TerminalReadAction,
                RecallAction,
                DelegateTaskAction,
            ),
        ):
            self._tools_in_turn += 1

        if isinstance(event, MessageAction):
            if self._is_user_source(source):
                return
            self._handle_message_action(event)
        elif isinstance(event, FileReadAction):
            path = getattr(event, 'path', '')
            view_range = getattr(event, 'view_range', None)
            start = getattr(event, 'start', 0)
            end = getattr(event, 'end', -1)
            if view_range and len(view_range) == 2:
                line_range = f'L{view_range[0]}:L{view_range[1]}'
            elif start not in (0, 1) or end != -1:
                end_str = str(end) if end != -1 else 'end'
                line_range = f'L{start}:{end_str}'
            else:
                line_range = ''
            card = ActivityRenderer.file_read(path, line_range)
            self._write_card(card)
        elif isinstance(event, FileEditAction):
            cmd = getattr(event, 'command', '')
            path = event.path
            insert_line = getattr(event, 'insert_line', None)
            start = getattr(event, 'start', 1)
            end = getattr(event, 'end', -1)
            start_line = getattr(event, 'start_line', None)
            end_line = getattr(event, 'end_line', None)

            verb_entry = self._FILE_EDIT_VERBS.get(cmd)
            if verb_entry is not None:
                verb, include_stats = verb_entry
                if include_stats and insert_line is not None:
                    line_range = f'line {insert_line}'
                else:
                    line_range = ''
            elif not cmd:
                end_str = f'L{end}' if end != -1 else 'end'
                verb = 'Edited'
                line_range = f'L{start}:{end_str}'
            elif cmd == 'edit':
                edit_mode = getattr(event, 'edit_mode', '')
                if (
                    edit_mode == 'range'
                    and start_line is not None
                    and end_line is not None
                ):
                    verb = 'Edited'
                    line_range = f'L{start_line}:L{end_line}'
                else:
                    verb = 'Edited'
                    line_range = ''
            else:
                verb = 'Edited'
                line_range = ''

            if cmd == 'create_file':
                file_text = getattr(event, 'file_text', '') or ''
                card = ActivityRenderer.file_create(
                    path,
                    line_count=_count_text_lines(file_text),
                )
                self._write_card(card)
            else:
                card = ActivityRenderer.file_edit(verb, path, line_range)
                self._write_card(card)
        elif isinstance(event, FileWriteAction):
            content = getattr(event, 'content', '') or ''
            card = ActivityRenderer.file_create(
                event.path,
                line_count=_count_text_lines(content),
                preview_content=content,
            )
            self._write_card(card)
        elif isinstance(event, FileReadObservation):
            pass
        elif isinstance(event, FileEditObservation):
            # Strip agent-facing indentation warnings from user-visible content
            from backend.cli.transcript import strip_indentation_warnings

            if hasattr(event, 'content') and event.content:
                event.content = strip_indentation_warnings(event.content)

            path = (getattr(event, 'path', '') or '').strip()
            added = event.added
            removed = event.removed

            if not getattr(event, 'prev_exist', True):
                new_content = getattr(event, 'new_content', '') or ''
                card = ActivityRenderer.file_create(
                    path or event.path,
                    line_count=added or _count_text_lines(new_content),
                    preview_content=new_content,
                )
                self._write_card(card)
            elif not path or path == '.':
                # Multi-file edit — split combined diff into per-file cards
                diff_text = self._extract_file_edit_diff(event)
                if diff_text:
                    per_file = _split_combined_diff(diff_text)
                    if per_file:
                        for fp, file_diff in per_file:
                            f_added = sum(
                                1
                                for line in file_diff.splitlines()
                                if line.startswith('+') and not line.startswith('+++')
                            )
                            f_removed = sum(
                                1
                                for line in file_diff.splitlines()
                                if line.startswith('-') and not line.startswith('---')
                            )
                            encoded = _encode_unified_diff_text(file_diff)
                            if encoded:
                                self._write_tui_file_card(
                                    'Edited',
                                    fp,
                                    secondary=_format_diff_summary(f_added, f_removed),
                                    secondary_kind='ok' if f_added else 'neutral',
                                    extra_content=encoded,
                                    collapsed=_should_collapse_file_diff(encoded),
                                )
                    else:
                        self._write_card(
                            ActivityRenderer.file_edit('Edited', path or '?')
                        )
                else:
                    self._write_card(ActivityRenderer.file_edit('Edited', path or '?'))
            else:
                encoded_diff = self._extract_file_edit_group_rows(event)
                if not encoded_diff:
                    diff_text = self._extract_file_edit_diff(event)
                    encoded_diff = (
                        _encode_unified_diff_text(diff_text) if diff_text else None
                    )
                if encoded_diff:
                    self._write_tui_file_card(
                        'Edited',
                        path,
                        secondary=_format_diff_summary(added, removed),
                        secondary_kind='ok' if added and not removed else 'neutral',
                        extra_content=encoded_diff,
                        collapsed=_should_collapse_file_diff(encoded_diff),
                    )
                else:
                    card = ActivityRenderer.file_edit(
                        'Edited',
                        path,
                        added=added,
                        removed=removed,
                    )
                    self._write_card(card)
        elif isinstance(event, FileWriteObservation):
            diff_text = self._extract_file_observation_diff(event)
            if diff_text:
                self._write_tui_file_card(
                    'Edited',
                    event.path,
                    secondary=None,
                    secondary_kind='neutral',
                    extra_content=_encode_unified_diff_text(diff_text),
                    collapsed=_should_collapse_file_diff(diff_text),
                )
        elif isinstance(event, MCPAction):
            card = ActivityRenderer.mcp_tool(event.name, event.arguments)
            self._write_card(card)
        elif isinstance(event, CmdRunAction):
            cmd = getattr(event, 'command', '') or ''
            if not getattr(event, 'hidden', False):
                self._create_shell_command_card(cmd)
        elif isinstance(event, MCPObservation):
            card = ActivityRenderer.mcp_tool(
                event.name,
                event.arguments,
                result=event.content or '',
                success=True,
            )
            self._write_card(card)
        elif isinstance(event, CmdOutputObservation):
            output = (event.content or '').strip()
            exit_code = getattr(event, 'exit_code', None)
            cmd = getattr(event, 'command', '') or ''
            cwd = (
                getattr(event.metadata, 'working_dir', None)
                if hasattr(event, 'metadata') and event.metadata
                else None
            )
            if output:
                output = _sanitize_terminal_display_text(
                    strip_tool_result_validation_annotations(output)
                ).strip()
            if output or exit_code is not None:
                self._complete_shell_command_card(
                    cmd,
                    output=output[:500],
                    exit_code=exit_code,
                    cwd=cwd,
                )
        elif isinstance(event, ErrorObservation):
            self._tui.add_error(event.content or 'An unknown error occurred')
        elif isinstance(event, SuccessObservation):
            self._clear_retry_strip('Recovered')
            self._clear_runtime_status('Recovered')
            self._tui.add_success(event.content or 'Done')
        elif isinstance(event, StatusObservation):
            status_type = str(getattr(event, 'status_type', '') or '')
            extras = getattr(event, 'extras', None) or {}
            if status_type in (
                'retry_pending',
                'retry_resuming',
                'llm_retry_pending',
                'llm_retry_resuming',
            ):
                label, last_status, message = self._format_retry_status_message(
                    status_type, extras
                )
                self._hud.update_ledger('Backoff')
                self._hud.update_agent_state(label)
                self._tui.set_agent_phase(label)
                self._update_retry_strip(label, message)
                return
            if status_type == 'compaction':
                self._clear_retry_strip('Idle')
                self._hud.update_agent_state('Compacting')
                self._tui.set_agent_phase('Compacting context...')
                self._update_runtime_strip(
                    'Compacting context',
                    'Reducing context to continue the task',
                    active=True,
                )
                return
            msg = (event.content or '').strip()
            if msg:
                summary = (
                    status_type.replace('_', ' ').strip().title()
                    if status_type
                    else 'Runtime notice'
                )
                self._update_runtime_strip(summary, msg, active=False)
        elif isinstance(event, AgentThinkAction):
            source_tool = getattr(event, 'source_tool', '') or ''
            thought = getattr(event, 'thought', '') or getattr(event, 'content', '')

            if source_tool == 'search_code' and thought:
                self._handle_search_code_action(thought)
            elif thought and thought.strip() != 'Your thought has been logged.':
                self._tui.add_thinking(thought)
        elif isinstance(event, AgentThinkObservation):
            thought = getattr(event, 'thought', '') or getattr(event, 'content', '')
            if thought and thought.strip() != 'Your thought has been logged.':
                self._tui.add_thinking(thought)
        elif isinstance(event, BrowserToolAction):
            action_name = getattr(event, 'command', 'browser') or 'browser'
            url = ''
            if action_name == 'navigate':
                url = (getattr(event, 'params', {}) or {}).get('url', '')
            elif action_name == 'click':
                selector = (getattr(event, 'params', {}) or {}).get('selector', '')
                url = selector[:80] if selector else ''
            card = ActivityRenderer.browser_action(action_name, url)
            widget = self._write_card(card)
            self._last_browser_action_card = widget
            self._last_browser_cmd = action_name
        elif isinstance(event, BrowseInteractiveAction):
            actions = getattr(event, 'browser_actions', '') or ''
            detail = (
                actions[:80] + ('...' if len(actions) > 80 else '') if actions else ''
            )
            card = ActivityRenderer.browser_action('browse', detail)
            widget = self._write_card(card)
            self._last_browser_action_card = widget
            self._last_browser_cmd = 'browse'
        elif isinstance(event, BrowserScreenshotObservation):
            url = getattr(event, 'image_path', '') or ''
            card = ActivityRenderer.browser_action(
                'screenshot', url, result=event.content or 'captured'
            )
            widget = self._write_card(card)
            prev = getattr(self, '_last_browser_action_card', None)
            if prev is not None and getattr(self, '_last_browser_cmd', '') in (
                'screenshot',
                'browse',
                'browser',
            ):
                try:
                    prev.set_processing(False)
                    if self._last_active_card is prev:
                        self._last_active_card = None
                except Exception:
                    pass
        elif isinstance(event, LspQueryAction):
            symbol = getattr(event, 'symbol', '') or getattr(event, 'query', '') or ''
            card = ActivityRenderer.lsp_query(symbol)
            self._write_card(card)
        elif isinstance(event, LspQueryObservation):
            content = (event.content or '').strip()
            symbol = getattr(event, 'symbol', '') or ''
            available = bool(getattr(event, 'available', True))
            card = ActivityRenderer.lsp_query(
                symbol, result=content, available=available
            )
            self._write_card(card)
        elif isinstance(event, TerminalRunAction):
            cmd = getattr(event, 'command', '') or ''
            session_id = getattr(event, 'session_id', '') or ''
            detail = self._terminal_card_detail(session_id, cmd)
            self._upsert_terminal_session_card(
                session_id=session_id,
                verb='Started',
                detail=detail,
                secondary=_join_secondary_parts(
                    self._terminal_session_label(session_id),
                    'starting session',
                ),
                secondary_kind='neutral',
                processing=True,
            )
        elif isinstance(event, TerminalInputAction):
            session_id = getattr(event, 'session_id', '') or ''
            submitted = _sanitize_terminal_display_text(
                getattr(event, 'input', '') or ''
            )
            detail = self._terminal_card_detail(session_id, submitted)
            self._upsert_terminal_session_card(
                session_id=session_id,
                verb='Sent',
                detail=detail,
                secondary=_join_secondary_parts(
                    self._terminal_session_label(session_id),
                    'awaiting output',
                ),
                secondary_kind='neutral',
                extra_content=f'$ {submitted.rstrip()}' if submitted.strip() else None,
                processing=True,
            )
        elif isinstance(event, TerminalReadAction):
            session_id = getattr(event, 'session_id', '') or ''
            self._upsert_terminal_session_card(
                session_id=session_id,
                verb='Reading',
                detail=self._terminal_card_detail(session_id),
                secondary=_join_secondary_parts(
                    self._terminal_session_label(session_id),
                    'streaming output',
                ),
                secondary_kind='neutral',
                processing=True,
            )
        elif isinstance(event, TerminalObservation):
            content = event.content or ''
            session_id = getattr(event, 'session_id', '') or ''
            exit_code = getattr(event, 'exit_code', None)
            state = getattr(event, 'state', None)
            secondary = _join_secondary_parts(
                self._terminal_session_label(session_id),
                (f'exit {exit_code}' if exit_code is not None else (state or None)),
            )
            secondary_kind = (
                'ok'
                if exit_code == 0
                else ('err' if exit_code is not None and exit_code != 0 else 'neutral')
            )
            if content:
                content = _sanitize_terminal_display_text(
                    strip_tool_result_validation_annotations(content)
                ).strip()
            self._upsert_terminal_session_card(
                session_id=session_id,
                verb='Output',
                detail=self._terminal_card_detail(session_id),
                secondary=secondary,
                secondary_kind=secondary_kind,
                extra_content=content or None,
                processing=exit_code is None,
                collapse_after_update=exit_code == 0 and bool(content),
            )
        elif isinstance(event, RecallAction):
            # Don't show memory recall as a visible card - it's an internal operation
            pass
        elif isinstance(event, RecallObservation):
            pass
        elif isinstance(event, RecallFailureObservation):
            pass
        elif isinstance(event, CondensationAction):
            count = self._condensation_count + 1
            self._condensation_count = count
            card = ActivityRenderer.condensation(count=count)
            self._write_card(card)
            self._hud.update_condensation_count(count)
        elif isinstance(event, AgentCondensationObservation):
            self._update_runtime_strip(
                'Context compacted',
                'Context compressed successfully',
                active=False,
            )
            count = max(self._condensation_count, 1)
            card = ActivityRenderer.condensation(count=count, result=event.content)
            self._write_card(card)
        elif isinstance(event, DelegateTaskAction):
            task = (
                getattr(event, 'task_description', '')
                or getattr(event, 'task', '')
                or ''
            )
            worker = getattr(event, 'worker', '') or ''
            if getattr(event, 'parallel_tasks', None):
                for item in list(getattr(event, 'parallel_tasks', []) or []):
                    task_desc = self._summarize_worker_task(
                        str(item.get('task_description') or 'delegated task')
                    )
                    self._active_worker_tasks.append(task_desc)
            else:
                self._active_worker_tasks.append(self._summarize_worker_task(task))
            self._sync_worker_strip()
            card = ActivityRenderer.delegation(task, worker)
            self._write_card(card)
        elif isinstance(event, DelegateTaskObservation):
            content = (event.content or '').strip()
            success = bool(getattr(event, 'success', True))
            error_message = (getattr(event, 'error_message', '') or '').strip()
            resolved_task = (
                self._active_worker_tasks.pop(0)
                if self._active_worker_tasks
                else 'delegated task'
            )
            if success:
                self._worker_completed += 1
                if resolved_task:
                    self._worker_recent_results.append(f'ok: {resolved_task}')
            else:
                self._worker_failed += 1
                if resolved_task:
                    self._worker_recent_results.append(f'fail: {resolved_task}')
            self._sync_worker_strip()
            card = ActivityRenderer.delegation(
                resolved_task,
                result=error_message or content,
                success=success,
            )
            self._write_card(card)
        elif isinstance(event, PlaybookFinishAction):
            message = getattr(event, 'message', '') or ''
            if message:
                self._tui._write_log(Markdown(message))
        elif isinstance(event, UserRejectObservation):
            card = ActivityRenderer.user_reject()
            self._write_card(card)
        elif isinstance(event, ServerReadyObservation):
            url = getattr(event, 'url', '')
            port = getattr(event, 'port', '')
            card = ActivityRenderer.server_ready(url, port)
            self._write_card(card)
        elif isinstance(event, FileDownloadObservation):
            url = getattr(event, 'url', '') or ''
            self._tui._write_log(
                Text(f'  [bold #91abec]Downloaded[/] {url}', style=NAVY_TEXT_PRIMARY)
            )
        elif isinstance(event, TaskTrackingObservation):
            if self._should_replace_task_list_from_event(event):
                self._task_list = list(getattr(event, 'task_list', []) or [])
                self._refresh_display()
        elif isinstance(event, StreamingChunkAction):
            self._handle_streaming_chunk(event)
        elif isinstance(event, AgentStateChangedObservation):
            self._handle_state_change(event)
        elif isinstance(event, ClarificationRequestAction):
            self._tui.add_communicate_clarification(event)
        elif isinstance(event, UncertaintyAction):
            self._tui.add_communicate_uncertainty(event)
        elif isinstance(event, ProposalAction):
            self._tui.add_communicate_proposal(event)
        elif isinstance(event, EscalateToHumanAction):
            self._tui.add_communicate_escalate(event)
        elif isinstance(event, TaskTrackingAction):
            if self._should_replace_task_list_from_event(event):
                self._task_list = list(getattr(event, 'task_list', []) or [])
                self._refresh_display()
        else:
            name = type(event).__name__
            self._tui._write_log(Text(f'  [{name}]', style=NAVY_TEXT_MUTED))

    def _should_replace_task_list_from_event(self, event: Any) -> bool:
        """Ignore empty task payloads unless they clearly mean to clear the plan."""
        command = str(getattr(event, 'command', '') or '').strip().lower()
        task_list = list(getattr(event, 'task_list', []) or [])
        if task_list:
            return True
        if command == 'view':
            return False
        if command == 'clear':
            return True

        content = str(getattr(event, 'content', '') or '').strip().lower()
        thought = str(getattr(event, 'thought', '') or '').strip().lower()
        explicit_clear_markers = (
            'clearing the task list',
            'plan updated with 0 tasks',
            'cleared task list',
            'cleared the task list',
        )
        if any(marker in content for marker in explicit_clear_markers):
            return True
        if any(marker in thought for marker in explicit_clear_markers):
            return True
        return not self._task_list

    def _extract_file_observation_diff(self, event: Any) -> str | None:
        """Extract unified diff text from any file edit/write observation."""
        return self._extract_file_edit_diff(event)

    def _extract_file_edit_group_rows(self, event: Any) -> str | None:
        """Extract two-pane diff rows from before/after edit groups."""
        old_content = getattr(event, 'old_content', None)
        new_content = getattr(event, 'new_content', None)
        if old_content is None or new_content is None:
            return None
        return _encode_split_diff_contents(old_content, new_content)

    def _extract_file_edit_diff(self, event: Any) -> str | None:
        """Extract unified diff from a FileEditObservation for TUI display."""
        explicit_diff = getattr(event, 'diff', None)
        if isinstance(explicit_diff, str) and explicit_diff.strip():
            return explicit_diff

        content = getattr(event, 'content', None)
        if isinstance(content, str) and content:
            marker = '[EDIT_DIFF]'
            marker_index = content.find(marker)
            if marker_index != -1:
                embedded = content[marker_index + len(marker) :].strip()
                if embedded:
                    return embedded

            preview = _extract_tagged_block(
                content,
                '<DIFF_PREVIEW>',
                '</DIFF_PREVIEW>',
            )
            if preview:
                return preview

        try:
            from backend.execution.utils.diff import get_diff

            old_content = getattr(event, 'old_content', None)
            new_content = getattr(event, 'new_content', None)
            if old_content is None or new_content is None:
                return self._extract_git_file_diff(getattr(event, 'path', ''))

            diff = get_diff(old_content, new_content, path=event.path)
            if diff:
                return diff
            return None
        except Exception:
            pass
        return self._extract_git_file_diff(getattr(event, 'path', ''))

    def _extract_git_file_diff(self, path: str) -> str | None:
        """Best-effort fallback when observations omit inline diff payloads."""
        clean_path = (path or '').strip()
        if not clean_path or clean_path == '.':
            return None
        try:
            workspace = resolve_cli_workspace_directory(
                getattr(self._tui, '_config', None)
            )
            if workspace is None:
                return None

            path_obj = Path(clean_path)
            if path_obj.is_absolute():
                try:
                    clean_path = str(
                        path_obj.resolve().relative_to(workspace.resolve())
                    )
                except (OSError, ValueError):
                    return None

            for args in (
                ['git', '-C', str(workspace), '--no-pager', 'diff', '--', clean_path],
                [
                    'git',
                    '-C',
                    str(workspace),
                    '--no-pager',
                    'diff',
                    '--cached',
                    '--',
                    clean_path,
                ],
            ):
                result = subprocess.run(
                    args,
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout
        except Exception:
            return None
        return None

    def _handle_search_code_action(self, thought: str) -> None:
        """Handle search_code action and render as a card."""
        import re

        # Strip <search_results> tags
        content = re.sub(r'</?search_results>', '', thought).strip()
        if not content:
            return

        from backend.cli._tool_display.renderers.search import extract_file_summary

        match_count, file_count, file_list = extract_file_summary(content)
        lines = content.splitlines()
        query = ''
        scope = ''
        result_lines: list[str] = []

        if lines:
            first = lines[0].strip()
            # Check if first line has an embedded query hint like "Query: ..." or "pattern: ..."
            query_match = re.match(
                r'^(?:query|pattern|searching for):\s*(.+?)$', first, re.I
            )
            if query_match:
                query = query_match.group(1).strip().strip('"\'')
                result_lines = [
                    line
                    for line in lines[1:]
                    if line.strip() and ':' in line.split(None, 1)[0]
                ]
            elif re.match(r'^.*:\d+:', first):
                # First line is already file:line:content — no separate query line
                result_lines = [line for line in lines if line.strip()]
            else:
                # First line is the query itself
                query = first.strip().strip('"\'')
                result_lines = [
                    line
                    for line in lines[1:]
                    if line.strip() and ':' in line.split(None, 1)[0]
                ]

        if not query:
            query = 'code search'

        card = ActivityRenderer.search_results(
            query=query,
            match_count=match_count,
            file_count=file_count,
            file_list=file_list,
            result_lines=result_lines,
            scope=scope,
        )
        self._write_card(card)

    @staticmethod
    def _is_user_source(source: Any) -> bool:
        value = getattr(source, 'value', source)
        return str(value or '').strip().lower() == EventSource.USER.value

    @staticmethod
    def _normalize_final_response_text(text: str) -> str:
        from backend.cli.transcript import strip_pseudo_xml_function_calls

        content = strip_pseudo_xml_function_calls(text or '')
        content = re.sub(
            r'\s*<minimax:tool_call\b[^>]*>.*?(?:</minimax:tool_call>|\Z)',
            '',
            content,
            flags=re.DOTALL | re.IGNORECASE,
        )
        content = re.sub(
            r'\s*<tool_call\b[^>]*>.*?(?:</tool_call>|\Z)',
            '',
            content,
            flags=re.DOTALL | re.IGNORECASE,
        )
        content = re.sub(
            r'\s*<function_calls\b[^>]*>.*?(?:</function_calls>|\Z)',
            '',
            content,
            flags=re.DOTALL | re.IGNORECASE,
        )
        return sanitize_visible_transcript_text(content).strip()

    def _commit_final_response(self, text: str) -> None:
        """Commit a final assistant response once, regardless of event shape."""
        content = self._normalize_final_response_text(text)
        self._tui.finalize_thinking()
        self.clear_live_response()
        if not content:
            return
        if content == self._last_final_response_text:
            return
        self._last_final_response_text = content
        from backend.cli.tui.widgets.activity_card import AgentMessage

        self.add_to_history(AgentMessage(content))

    def _handle_message_action(self, action: MessageAction) -> None:
        if bool(getattr(action, 'suppress_cli', False)):
            self._tui.finalize_thinking()
            self.clear_live_response()
            return

        thought = (getattr(action, 'thought', '') or '').strip()
        if thought and thought != 'Your thought has been logged.':
            self._tui.add_thinking(thought)
            self._tui.finalize_thinking()

        content = (getattr(action, 'content', '') or '').strip()
        if not content:
            self._tui.finalize_thinking()
            self.clear_live_response()
            return

        self._commit_final_response(content)

    @staticmethod
    def _format_retry_status_message(
        status_type: str, extras: dict[str, Any]
    ) -> tuple[str, str, str]:
        attempt = max(1, int(extras.get('attempt') or 1))
        max_attempts = max(attempt, int(extras.get('max_attempts') or attempt))
        reason = str(extras.get('reason') or 'transient failure').strip()
        source = str(extras.get('source') or '').strip().lower()
        retry_target = 'provider stream' if source == 'llm_stream' else 'provider'
        if status_type in ('retry_pending', 'llm_retry_pending'):
            delay_seconds = extras.get('delay_seconds')
            try:
                delay = float(delay_seconds) if delay_seconds is not None else 0.0
            except (TypeError, ValueError):
                delay = 0.0
            delay_str = f'{int(delay)}s' if delay >= 1 else '<1s'
            return (
                f'Backoff {attempt}/{max_attempts} (retrying in {delay_str})',
                f'Waiting {delay_str} to retry after {reason}',
                f'Auto-retrying {retry_target} in {delay_str} ({attempt}/{max_attempts}) after {reason}.',
            )

        return (
            f'Retrying {attempt}/{max_attempts}',
            f'Resuming after {reason}',
            f'Retrying {retry_target} now ({attempt}/{max_attempts}) after {reason}.',
        )

    def _handle_streaming_chunk(self, action: StreamingChunkAction) -> None:
        if action.is_tool_call:
            return

        thinking = (action.thinking_accumulated or '').strip()
        if thinking and thinking != 'Your thought has been logged.':
            self._tui.add_thinking(thinking)

        content = self._normalize_final_response_text(action.accumulated or '')

        if action.is_final:
            self._commit_final_response(content)
            return

        if content:
            self.update_live_response(content)

    def _update_metrics(self, event: Any) -> None:
        if hasattr(event, 'model') and event.model:
            self._hud.update_model(event.model)
        if hasattr(event, 'llm_metrics') and event.llm_metrics:
            self._hud.update_from_llm_metrics(event.llm_metrics)
        cost = getattr(event, 'cost_usd', None)
        if cost is not None and cost > 0:
            self._hud.update_cost(self._hud.state.cost_usd + cost)
        self._tui._render_hud_bar()

    def _handle_state_change(self, obs: Any) -> None:
        state = obs.agent_state
        try:
            state = AgentState(state)
        except (ValueError, TypeError):
            pass

        self._current_state = state
        current_label = (self._hud.state.agent_state_label or '').strip()
        if state == AgentState.RATE_LIMITED:
            self._hud.update_ledger('Backoff')
            if not current_label.startswith(('Backoff', 'Retrying')):
                self._hud.update_agent_state('Rate Limited')
                current_label = 'Rate Limited'
            self._tui.set_agent_phase(current_label)
        else:
            self._clear_retry_strip('Idle')
            if state not in (AgentState.ERROR,):
                self._clear_runtime_strip('Idle')
            self._hud.update_agent_state(str(state))
            self._tui.set_agent_phase(str(state))

        # End agent turn when reaching idle/terminal state
        if self._in_agent_turn and state in (
            AgentState.AWAITING_USER_INPUT,
            AgentState.FINISHED,
            AgentState.ERROR,
            AgentState.STOPPED,
        ):
            self._in_agent_turn = False
            if self._tools_in_turn > 0:
                elapsed = time.monotonic() - self._turn_start_time
                duration_str = f'{elapsed:.1f}s'

                from backend.cli.tui.widgets.activity_card import TurnCompletion

                self._tui._write_log(TurnCompletion(duration_str))

        # Ensure thinking UI is cleared on any idle/terminal state
        if state in (
            AgentState.AWAITING_USER_INPUT,
            AgentState.FINISHED,
            AgentState.ERROR,
            AgentState.STOPPED,
        ):
            self._tui.finalize_thinking()

        self._state_event.set()
        self._tui._render_hud_bar()
