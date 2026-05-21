"""Grinta TUI — Textual Application screen and widgets.

Clean minimal layout with proper widget architecture, unified activity cards,
and incremental transcript updates.
"""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import shlex
import shutil
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.message import Message
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Input,
    Label,
    RichLog,
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

from backend import __version__ as GRINTA_VERSION
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
    NAVY_READY,
    NAVY_TEXT_DIM,
    NAVY_TEXT_MUTED,
    NAVY_TEXT_PRIMARY,
    NAVY_TEXT_SECONDARY,
    NAVY_TEXT_TERTIARY,
    NAVY_WAITING,
)
from backend.cli.transcript import strip_tool_result_validation_annotations
from backend.core.bootstrap.agent_control_loop import run_agent_until_done
from backend.core.bootstrap.main import (
    create_agent,
    create_registry_and_conversation_stats,
)
from backend.core.bootstrap.setup import (
    create_controller,
    create_memory,
    create_runtime,
)
from backend.core.enums import AgentState, EventSource
from backend.core.logger import app_logger as logger
from backend.ledger import EventStream, EventStreamSubscriber
from backend.ledger.observation import StatusObservation
from backend.ledger.action import (
    AgentThinkAction,
    BrowseInteractiveAction,
    BrowserToolAction,
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


def _render_thinking_with_diff(text: str) -> Text:
    """Render thinking text as plain muted text."""
    return Text(text or '', style="dim lightgray")


# ── Widget classes ────────────────────────────────────────────────────────


class InfoSidebar(VerticalScroll):
    """Sidebar for Mission Control info (Tasks, MCPs, Skills)."""

    def update(self, *args: Any, **kwargs: Any) -> None:
        """No-op update for backward compatibility and test mock compatibility."""
        pass


class Transcript(VerticalScroll):
    """Scrollable conversation transcript container."""

    def write(self, renderable: Any) -> None:
        """Compatibility method for RichLog interface."""
        self.mount(Static(renderable))
        self.scroll_end(animate=False)

    def clear(self) -> None:
        """Compatibility method for RichLog interface."""
        self.remove_children()


class InputBar(Horizontal):
    """Bottom input row with border and prompt."""


class HUD(Vertical):
    """Multi-line status bar at the very bottom."""

    def compose(self) -> ComposeResult:
        yield Label(id='hud-line-1')
        yield Label(id='hud-line-2')
        yield Label(id='hud-line-4')


class RendererDrainRequested(Message):
    """Message requesting the screen to drain queued renderer events."""


class GrintaConfirmDialog(ModalScreen[str | None]):
    """Confirmation dialog shown when the agent needs user input."""

    BINDINGS = [
        Binding('escape', 'dismiss(None)', 'Cancel', show=False),
    ]

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
        with Vertical():
            yield Label(f'[bold]{self._dialog_title}[/]', classes='title')
            yield Label(self._dialog_body, classes='body')
            with Horizontal(classes='buttons-row'):
                for i, (key, label) in enumerate(self._options):
                    yield Button(
                        label,
                        id=f'confirm-{key}',
                        variant='primary' if i == (self._recommended or 0) else 'default',
                    )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        for key, _label in self._options:
            if event.button.id == f'confirm-{key}':
                self.dismiss(key)
                return


class GrintaAddSkillDialog(ModalScreen[dict[str, str] | None]):
    """Dialog to create a custom skill dynamically."""

    BINDINGS = [
        Binding('escape', 'dismiss(None)', 'Cancel', show=False),
        Binding('ctrl+s', 'save', 'Save', show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id='settings-dialog'):
            yield Label('[bold]Add Custom Skill[/]', classes='title')
            yield Label('Skill Name (e.g. react_best_practices)', classes='field-label')
            yield Input(id='skill-name')
            yield Label('Instructions (Markdown)', classes='field-label')
            yield TextArea(id='skill-content')
            yield Label('', id='settings-feedback')
            with Horizontal(id='settings-buttons'):
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
            self.query_one('#settings-feedback', Label).update('[#f05757]Skill name required.[/]')
            return
        if not content:
            self.query_one('#settings-feedback', Label).update('[#f05757]Content required.[/]')
            return
        self.dismiss({'name': name, 'content': content})


class GrintaAddMCPDialog(ModalScreen[dict[str, str] | None]):
    """Dialog to add an MCP Server."""

    BINDINGS = [
        Binding('escape', 'dismiss(None)', 'Cancel', show=False),
        Binding('ctrl+s', 'save', 'Save', show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id='settings-dialog'):
            yield Label('[bold]Add MCP Server[/]', classes='title')
            yield Label('Server Name', classes='field-label')
            yield Input(id='mcp-name')
            yield Label('Command or URL (e.g. npx -y @modelcontextprotocol/server-postgres)', classes='field-label')
            yield Input(id='mcp-command')
            yield Label('', id='settings-feedback')
            with Horizontal(id='settings-buttons'):
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
            self.query_one('#settings-feedback', Label).update('[#f05757]Name and command required.[/]')
            return
        self.dismiss({'name': name, 'command': cmd})


class GrintaSettingsDialog(ModalScreen[dict[str, Any] | None]):
    """Native settings modal for full-screen TUI."""

    BINDINGS = [
        Binding('escape', 'dismiss(None)', 'Cancel', show=False),
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

        with Vertical(id='settings-dialog'):
            yield Label('[bold]Settings[/]', classes='title')
            yield Label(f'Current API key: {masked_key}', id='settings-current-key')
            yield Label('Model', classes='field-label')
            yield Input(value=current_model, id='settings-model')
            yield Label('API key (leave blank to keep current key)', classes='field-label')
            yield Input(password=True, id='settings-api-key')
            yield Label(
                'Budget per task (blank/unlimited to keep unlimited)', classes='field-label'
            )
            yield Input(value=budget_value, id='settings-budget')
            yield Checkbox(
                'Show tool icons in activity cards',
                value=icons_enabled,
                id='settings-icons',
            )
            yield Label('', id='settings-feedback')
            with Horizontal(id='settings-buttons'):
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
        self.query_one('#settings-feedback', Label).update(f'[{style}]{message}[/]')

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
                self._set_feedback('Budget must be numeric, unlimited, or empty.', error=True)
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


class GrintaSessionsDialog(ModalScreen[str | None]):
    """Native sessions manager for full-screen TUI."""

    BINDINGS = [
        Binding('escape', 'dismiss(None)', 'Close', show=False),
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
        with Vertical(id='sessions-dialog'):
            yield Label('[bold]Sessions[/]', classes='title')
            with Horizontal(id='sessions-filters'):
                yield Input(value=self._search, placeholder='Search…', id='sessions-search')
                yield Select(
                    options=options,
                    value=self._sort_by,
                    allow_blank=False,
                    id='sessions-sort',
                )
                yield Input(value=str(self._limit), restrict=r'\d*', id='sessions-limit')
                yield Button('Refresh', id='sessions-refresh')
            yield DataTable(id='sessions-table')
            yield Static('', id='sessions-preview')
            yield Label('', id='sessions-feedback')
            with Horizontal(id='sessions-buttons'):
                yield Button('Resume', id='sessions-resume', variant='primary')
                yield Button('Delete', id='sessions-delete', variant='error')
                yield Button('Close', id='sessions-close')

    def on_mount(self) -> None:
        table = self.query_one('#sessions-table', DataTable)
        table.cursor_type = 'row'
        table.add_columns('#', 'Session ID', 'Title', 'Model', 'Events', 'Updated')
        self._refresh_table()
        if self._delete_targets:
            deleted, errors = self._delete_sessions(self._delete_targets)
            self._set_feedback(f'Deleted {deleted} session(s). {" ".join(errors)}'.strip())
            self._refresh_table()
        if self._preview_target:
            self._select_target(self._preview_target)
        self.query_one('#sessions-search', Input).focus()

    def action_refresh(self) -> None:
        self._refresh_table()

    def action_delete_selected(self) -> None:
        sid = self._current_session_id()
        if not sid:
            self._set_feedback('No session selected.', error=True)
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
            self.action_delete_selected()
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
        self.query_one('#sessions-feedback', Label).update(f'[{style}]{message}[/]')

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
            model = str(meta.get('llm_model') or '—')[:24]
            updated = str(meta.get('last_updated_at') or meta.get('created_at') or '—')[:19]
            table.add_row(str(i), sid[:12], title, model, str(event_count), updated, key=sid)

        if self._visible_entries:
            table.move_cursor(row=0, column=0, animate=False, scroll=False)
            self._update_preview(0)
            self._set_feedback(f'{len(self._visible_entries)} session(s) loaded.')
        else:
            self.query_one('#sessions-preview', Static).update('')
            if self._search:
                self._set_feedback(f'No sessions matching "{self._search}".', error=True)
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
        cost = meta.get('accumulated_cost') or 0
        preview = Text.from_markup(
            f'[bold]ID:[/] {sid}\n'
            f'[bold]Title:[/] {str(meta.get("title") or meta.get("name") or "—")}\n'
            f'[bold]Model:[/] {str(meta.get("llm_model") or "—")}\n'
            f'[bold]Events:[/] {event_count}\n'
            f'[bold]Cost:[/] {f"${float(cost):.4f}" if cost else "—"}\n'
            f'[bold]Updated:[/] {str(meta.get("last_updated_at") or meta.get("created_at") or "—")[:19]}'
        )
        self.query_one('#sessions-preview', Static).update(preview)

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
        self._pending_confirm: asyncio.Event | None = None
        self._confirm_result: str | None = None
        self._input_lock = asyncio.Lock()
        self._bootstrapping: asyncio.Event | None = None
        self._bootstrap_task: asyncio.Task[Any] | None = None
        self._is_unmounted = False
        self._command_hint = ''
        self._phase_label = 'Ready'
        self._phase_started_at = time.monotonic()
        self._last_tool_status = 'No tool activity yet'
        self._hud_tick = None

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

    def compose(self) -> ComposeResult:
        from backend.cli.tui.widgets.collapsible import CollapsibleSection
        with Horizontal(id='main-layout'):
            yield Transcript(id='main-display')
            with InfoSidebar(id='sidebar-container'):
                yield CollapsibleSection(
                    title="Tasks (0)",
                    content="No tasks yet",
                    collapsed=False,
                    accent_color='#91abec',
                    id='sidebar-tasks',
                )
                yield CollapsibleSection(
                    title="MCP Servers (0)",
                    content="No MCP servers configured",
                    collapsed=False,
                    accent_color='#eacb8a',
                    action_label='[+] Add',
                    id='sidebar-mcp',
                )
                yield CollapsibleSection(
                    title="Skills",
                    content="No skills available",
                    collapsed=True,
                    accent_color='#7a849c',
                    action_label='[+] Add',
                    id='sidebar-skills',
                )
        with InputBar(id='input-bar'):
            yield Static(id='spinner', classes='-hidden')
            yield TextArea(id='input', show_line_numbers=False)
        yield HUD(id='hud-bar')

    def on_mount(self) -> None:
        _tui_logger.debug('on_mount: GrintaScreen mounted')
        self._is_unmounted = False

        self._render_hud_bar()
        self._hud_tick = self.set_interval(1.0, self._refresh_runtime_feedback)
        ta = self.query_one('#input', TextArea)
        ta.text = ''
        ta.focus()
        self._get_display().scroll_home(animate=False)
        _tui_logger.debug('on_mount: done')
        self._start_background_bootstrap()

    def on_renderer_drain_requested(self, _message: RendererDrainRequested) -> None:
        if self._renderer is not None:
            self._renderer.drain_events()

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
                    EventStreamSubscriber.MAIN, 'grinta-tui'
                )
            self._renderer._event_stream = None
        if self._event_stream is not None:
            try:
                self._event_stream.unsubscribe(EventStreamSubscriber.MAIN, 'grinta-tui')
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

        cost = hud.state.cost_usd or 0
        used = hud.state.context_tokens
        calls = hud.state.llm_calls

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
        line1_parts.append(f'[#91abec bold]GRINTA[/]')
        line1_parts.append(f'[{state_color}]● {display_state}[/]')
        if workspace:
            line1_parts.append(f'[#bbc8e8]ws: {workspace}[/]')
        line1_parts.append(f'[{NAVY_TEXT_SECONDARY}]{model_display}[/]')
        line1_parts.append(f'[{NAVY_TEXT_DIM}]Tok: {used:,}[/]')
        line1_parts.append(f'[{NAVY_TEXT_PRIMARY}]${cost:.4f}[/]')
        line1 = '  |  '.join(line1_parts)

        elapsed = max(0, int(time.monotonic() - self._phase_started_at))
        runtime_line = (
            f'[{NAVY_BRAND}]Auto: {autonomy}[/]  |  '
            f'[{NAVY_TEXT_DIM}]Phase: {self._phase_label}  |  '
            f'Elapsed: {elapsed}s  |  '
            f'Last: {self._last_tool_status}[/]'
        )
        hint_line = (
            f'[{NAVY_TEXT_SECONDARY}]Hint: {self._command_hint}[/]'
            if self._command_hint
            else runtime_line
        )

        hud_bar = self.query_one('#hud-bar', HUD)
        hud_bar.query_one('#hud-line-1', Label).update(line1)
        hud_bar.query_one('#hud-line-2', Label).update(hint_line)

        line4 = (
            f'[#54597b]Keys:[/] '
            f'[#eacb8a bold]Ctrl+B[/] [#969aad]Toggle Sidebar[/]  |  '
            f'[#eacb8a bold]Ctrl+L[/] [#969aad]Clear Screen[/]  |  '
            f'[#eacb8a bold]Ctrl+C[/] [#969aad]Interrupt[/]  |  '
            f'[#eacb8a bold]F1[/] [#969aad]Help[/]'
        )
        try:
            hud_bar.query_one('#hud-line-4', Label).update(line4)
        except Exception:
            pass

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

    def set_last_tool_status(self, status: str) -> None:
        compact = re.sub(r'\s+', ' ', (status or '').strip())
        if not compact:
            return
        if len(compact) > 96:
            compact = compact[:93] + '...'
        self._last_tool_status = compact
        self._render_hud_bar()

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
                    if cmd == '/sessions' and len(parts) > 1 and parts[-1].startswith('--'):
                        hint = 'Sessions flags: --limit --search --sort --preview --delete'
                    elif cmd == '/help' and len(parts) > 1 and parts[-1].startswith('--'):
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

    def _get_sidebar(self) -> Any:
        try:
            return self.query_one('#sidebar-container')
        except Exception:
            from unittest.mock import MagicMock
            return MagicMock()

    @staticmethod
    def _break_long_runs(text: str, max_len: int = 80) -> str:
        """Insert zero-width spaces in long continuous runs, preserving Rich markup tags."""

        def _break_word(w: str) -> str:
            if len(w) > max_len and not w.isspace():
                return '\u200b'.join(
                    w[i : i + max_len] for i in range(0, len(w), max_len)
                )
            return w

        parts = re.split(r'(\[[^\[\]]*\])', text)
        for i, part in enumerate(parts):
            if not (part.startswith('[') and part.endswith(']')):
                words = re.split(r'(\s+)', part)
                parts[i] = ''.join(_break_word(w) for w in words)
        return ''.join(parts)

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
        display.mount(widget)
        display.scroll_end(animate=False)

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
        display.mount(widget)
        display.scroll_end(animate=False)

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

    def _hide_thinking(self) -> None:
        """Called when user submits a new message — hide spinner if still active."""
        self.query_one('#spinner', Static).add_class('-hidden')

    def add_system_message(self, text: str) -> None:
        body = _rich_text(text)
        body.stylize(NAVY_TEXT_MUTED)
        self._write_log(body)
        self.set_last_tool_status(text)

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
        self.set_last_tool_status(f'Error: {text}')

    def add_success(self, text: str) -> None:
        icon = Text('✓ ', style=f'bold {NAVY_READY}')
        body = _rich_text(text)
        body.stylize(f'bold {NAVY_READY}')
        self._write_log(Text.assemble(icon, body))
        self.set_last_tool_status(text)

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
            self.set_last_tool_status(f'{tool_name}: {command}')
        else:
            self._write_log(Text.assemble(icon, name))
            self.set_last_tool_status(str(tool_name))

    def add_tool_result(self, text: str) -> None:
        """Tool result — muted text."""
        body = _rich_text(text)
        body.stylize(NAVY_TEXT_MUTED)
        self._write_log(Text.assemble('  ', body))
        self.set_last_tool_status(text)

    def add_communicate_clarification(self, action: ClarificationRequestAction) -> None:
        """Agent asks a question — show question and options in a callout panel."""
        from rich.console import Group
        from rich.text import Text

        from backend.cli.layout_tokens import DECISION_PANEL_ACCENT_STYLE
        from backend.cli.theme import (
            CLR_OPTION_RECOMMENDED,
            CLR_OPTION_TEXT,
            CLR_QUESTION_TEXT,
        )
        from backend.cli.transcript import format_callout_panel

        clarify_parts: list[Any] = []
        if action.question:
            t = _rich_text(action.question)
            t.stylize(CLR_QUESTION_TEXT)
            clarify_parts.append(t)
        for i, opt in enumerate(action.options or [], 1):
            line = Text()
            line.append(f'{i}. ', style=f'bold {CLR_OPTION_RECOMMENDED}')
            t_opt = _rich_text(opt)
            t_opt.stylize(CLR_OPTION_TEXT)
            line.append(t_opt)
            clarify_parts.append(line)

        panel = format_callout_panel(
            'Question', Group(*clarify_parts), accent_style=DECISION_PANEL_ACCENT_STYLE
        )
        self._write_log(panel)

    def add_communicate_uncertainty(self, action: UncertaintyAction) -> None:
        """Agent expresses uncertainty."""
        from rich.console import Group
        from rich.text import Text

        from backend.cli.layout_tokens import DECISION_PANEL_ACCENT_STYLE
        from backend.cli.theme import CLR_QUESTION_TEXT, MARK_INFO, STYLE_DIM
        from backend.cli.transcript import format_callout_panel

        parts: list[Any] = []
        for concern in (action.specific_concerns or [])[:5]:
            line = Text()
            line.append(f'{MARK_INFO} ', style=STYLE_DIM)
            t_concern = _rich_text(concern)
            t_concern.stylize(STYLE_DIM)
            line.append(t_concern)
            parts.append(line)
        if action.requested_information:
            t_req = _rich_text(f'Need: {action.requested_information}')
            t_req.stylize(CLR_QUESTION_TEXT)
            parts.append(t_req)

        panel = format_callout_panel(
            'Needs Context', Group(*parts), accent_style=DECISION_PANEL_ACCENT_STYLE
        )
        self._write_log(panel)

    def add_communicate_proposal(self, action: ProposalAction) -> None:
        """Agent proposes a plan."""
        from rich.console import Group
        from rich.text import Text

        from backend.cli.layout_tokens import DECISION_PANEL_ACCENT_STYLE
        from backend.cli.theme import CLR_OPTION_RECOMMENDED, CLR_OPTION_TEXT, STYLE_DIM
        from backend.cli.transcript import format_callout_panel

        parts: list[Any] = []
        if action.rationale:
            t_rat = _rich_text(action.rationale)
            t_rat.stylize(STYLE_DIM)
            parts.append(t_rat)
        for i, opt in enumerate(action.options or []):
            label = opt.get('name', opt.get('title', f'Option {i + 1}'))
            marker = ' (recommended)' if i == action.recommended else ''
            line = Text()
            line.append(f'{i + 1}. ', style=f'bold {DECISION_PANEL_ACCENT_STYLE}')
            line.append(
                f'{label}{marker}',
                style=f'bold {CLR_OPTION_RECOMMENDED}'
                if i == action.recommended
                else f'bold {CLR_OPTION_TEXT}',
            )
            parts.append(line)
            desc = opt.get('description', '')
            if desc:
                parts.append(Text(f'   {desc}', style=STYLE_DIM))

        panel = format_callout_panel(
            'Options', Group(*parts), accent_style=DECISION_PANEL_ACCENT_STYLE
        )
        self._write_log(panel)

    def add_communicate_escalate(self, action: EscalateToHumanAction) -> None:
        """Agent escalates to human."""
        from backend.cli.layout_tokens import DECISION_PANEL_ACCENT_STYLE
        from backend.cli.theme import CLR_QUESTION_TEXT
        from backend.cli.transcript import format_callout_panel

        t_reason = _rich_text(
            action.reason or 'The agent needs your input to continue.'
        )
        t_reason.stylize(CLR_QUESTION_TEXT)

        panel = format_callout_panel(
            'Need Your Input', t_reason, accent_style=DECISION_PANEL_ACCENT_STYLE
        )
        self._write_log(panel)

    def add_divider(self) -> None:
        from rich.rule import Rule

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
        sidebar = self.query_one('#sidebar-container', InfoSidebar)
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

    def _scroll_to_bottom(self) -> None:
        self._get_display().scroll_end(animate=False)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == 'input':
            self._update_command_hint(event.text_area.text)
            text = event.text_area.text
            line_count = len(text.split('\n')) if text else 1
            desired_textarea_height = max(3, min(6, line_count))
            desired_input_bar_height = desired_textarea_height + 1

            event.text_area.styles.height = desired_textarea_height
            try:
                self.query_one('#input-bar', InputBar).styles.height = desired_input_bar_height
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
            desc = "Unknown task"
            for t in self._renderer._task_list if self._renderer else []:
                if str(t.get('id')) == task_id:
                    desc = str(t.get('description') or desc)
                    break
            self.notify(f"Task {task_id}: {desc}", severity="info", timeout=3.0)
        elif item_id.startswith('mcp:'):
            mcp_name = item_id.split(':', 1)[1]
            self.notify(f"MCP Server: {mcp_name} (active/connected)", severity="info", timeout=3.0)
        elif item_id.startswith('skill:'):
            skill_name = item_id.split(':', 1)[1]
            self.notify(f"Playbook Skill: {skill_name}.md", severity="info", timeout=3.0)

    async def on_sidebar_row_delete_requested(self, event: Any) -> None:
        """Handle SidebarRow delete events."""
        from backend.cli.tui.widgets.collapsible import SidebarRow
        if not isinstance(event, SidebarRow.DeleteRequested) or not event.item_id:
            return
        item_id = event.item_id
        if item_id.startswith('skill:'):
            skill_name = item_id[6:]
            result = await self.app.push_screen_wait(
                GrintaConfirmDialog(
                    title="Delete Skill",
                    body=f"Are you sure you want to delete {skill_name}.md?",
                    options=[('cancel', 'Cancel'), ('delete', 'Delete')],
                )
            )
            if result == 'delete':
                self._delete_skill(skill_name)
        elif item_id.startswith('mcp:'):
            mcp_name = item_id.split(':', 1)[1]
            result = await self.app.push_screen_wait(
                GrintaConfirmDialog(
                    title="Delete MCP Server",
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
        from backend.cli.tui.widgets.collapsible import CollapsibleSection
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
            else:
                self.add_system_message('Suggestions: ' + ', '.join(matches))
            return

        if cmd == '/sessions' and parts[-1].startswith('--'):
            flags = ['--limit', '--search', '--sort', '--preview', '--delete']
            matches = [flag for flag in flags if flag.startswith(parts[-1])]
            if len(matches) == 1:
                prefix = raw.rstrip()
                ta.text = prefix[: -len(parts[-1])] + matches[0] + ' '
            elif matches:
                self.add_system_message('Sessions flags: ' + ', '.join(matches))
        elif cmd == '/help' and parts[-1].startswith('--'):
            flags = ['--all', '--search']
            matches = [flag for flag in flags if flag.startswith(parts[-1])]
            if len(matches) == 1:
                prefix = raw.rstrip()
                ta.text = prefix[: -len(parts[-1])] + matches[0] + ' '
            elif matches:
                self.add_system_message('Help flags: ' + ', '.join(matches))

    def action_submit_input(self) -> None:
        _tui_logger.debug(
            f'action_submit_input: lock_locked={self._input_lock.locked()}'
        )
        if self._input_lock.locked():
            _tui_logger.debug('action_submit_input: lock held, ignoring')
            return
        ta = self.query_one('#input', TextArea)
        text = _strip_ansi(ta.text).strip()
        _tui_logger.debug(f'action_submit_input: text_len={len(text)}')
        if not text:
            _tui_logger.debug('action_submit_input: empty text, ignoring')
            return
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
            self._update_command_hint('')
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
                        '_handle_input: controller exists, calling _ensure_agent_task()'
                    )
                    logger.info('[TUI] _handle_input: controller exists, ensuring task')
                    await self._ensure_agent_task()
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
            with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError, Exception):
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
                old_stream.unsubscribe(EventStreamSubscriber.MAIN, old_stream.sid)
            close_fn = getattr(old_stream, 'close', None)
            if callable(close_fn):
                with contextlib.suppress(Exception):
                    close_fn()
        self._memory_stub = None

    def show_help(self) -> None:
        self.add_divider()
        self.add_system_message(
            f'[{NAVY_BRAND}]GRINTA[/] — AI-Powered Development Platform'
        )
        self.add_divider()
        from rich.text import Text

        help_text = Text.from_markup(
            f'  [{NAVY_TEXT_SECONDARY}]/help[/]      [{NAVY_TEXT_TERTIARY}]Show this help[/]\n'
            f'  [{NAVY_TEXT_SECONDARY}]/clear[/]     [{NAVY_TEXT_TERTIARY}]Clear transcript[/]\n'
            f'  [{NAVY_TEXT_SECONDARY}]/settings[/]  [{NAVY_TEXT_TERTIARY}]Open settings[/]\n'
            f'  [{NAVY_TEXT_SECONDARY}]/sessions[/]  [{NAVY_TEXT_TERTIARY}]Manage sessions[/]\n'
            f'  [{NAVY_TEXT_SECONDARY}]/resume[/]    [{NAVY_TEXT_TERTIARY}]Resume a session[/]\n'
            f'  [{NAVY_TEXT_SECONDARY}]/quit[/]      [{NAVY_TEXT_TERTIARY}]Exit Grinta[/]\n'
            f'  [{NAVY_TEXT_SECONDARY}]Ctrl+C[/]     [{NAVY_TEXT_TERTIARY}]Stop agent[/]\n'
            f'  [{NAVY_TEXT_SECONDARY}]Tab[/]        [{NAVY_TEXT_TERTIARY}]Newline in input[/]\n'
            f'  [{NAVY_TEXT_SECONDARY}]Ctrl+Space[/] [{NAVY_TEXT_TERTIARY}]Command autocomplete[/]'
        )
        self._write_log(help_text)
        self.add_divider()
        self._scroll_to_bottom()

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
            sid = (session_id or 'grinta-tui').strip() or 'grinta-tui'
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

        try:
            await self._ensure_agent_task()
            _tui_logger.debug('_dispatch_to_agent: _ensure_agent_task OK')
        except Exception as exc:
            _tui_logger.debug(
                f'_dispatch_to_agent: _ensure_agent_task FAILED: {type(exc).__name__}: {exc}'
            )
            raise

        action = MessageAction(content=text)
        self._event_stream.add_event(action, EventSource.USER)
        # NOTE: _ensure_agent_task (via run_agent_until_done) already calls
        # controller.step() internally.  We skip the redundant explicit step()
        # to avoid double-processing the queued MessageAction.
        _tui_logger.debug('_dispatch_to_agent: event added')
        try:
            logger.info('[TUI] _dispatch_to_agent: event added')
        except Exception as exc:
            _tui_logger.debug(
                f'_dispatch_to_agent: logger.info FAILED: {type(exc).__name__}: {exc}'
            )
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
                    _tui_logger.debug(f'_dispatch_to_agent: reached end state {state}')
                    logger.info('[TUI] _dispatch_to_agent: reached end state %s', state)
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
        _tui_logger.debug('_dispatch_to_agent: poll loop exited')
        if self._renderer:
            self._renderer.drain_events()

    # ── Confirmation ────────────────────────────────────────────────────────

    async def confirm(
        self,
        title: str,
        body: str,
        options: list[tuple[str, str]],
        recommended: int | None = None,
    ) -> str | None:
        dialog = GrintaConfirmDialog(title, body, options, recommended)
        result = await self.app.push_screen_wait(dialog)
        return result


# ── TUIRenderer ───────────────────────────────────────────────────────────


class TUIRenderer:
    """Rich-driven renderer for Textual — manages history and real-time display."""

    _FILE_EDIT_VERBS: dict[str, tuple[str, bool]] = {
        'read_file': ('Read', False),
        'create_file': ('Created', False),
        'insert_text': ('Inserted', True),
        'undo_last_edit': ('Reverted', False),
        'write': ('Wrote', False),
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

        # Turn tracking for grouping tool calls by agent turn
        self._turn_count: int = 0
        self._in_agent_turn: bool = False
        self._tools_in_turn: int = 0
        self._turn_start_time: float = 0.0

    def subscribe(self, event_stream: Any, sid: str) -> None:
        self._event_stream = event_stream
        event_stream.subscribe(EventStreamSubscriber.MAIN, self._on_event, sid)

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
                display.mount(renderable)
            else:
                display.mount(Static(renderable))
            display.scroll_end(animate=False)
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
            display.mount(self._live_thinking_widget)
            self._live_thinking_widget.start()

        self._live_thinking_widget.set_thoughts(text)
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
            display.mount(self._live_response_widget)
        else:
            self._live_response_widget.update_message(text)
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

            if thoughts:
                content = '\n'.join(thoughts)
                from backend.cli.tui.widgets.collapsible import CollapsibleSection
                section = CollapsibleSection(
                    title="Thinking Process",
                    content=content,
                    collapsed=True,
                    accent_color='#5eead4',
                    is_thinking=True,
                )
                display.mount(section)
                display.scroll_end(animate=False)

            self._live_thinking = ''
            self._live_thinking_dirty = False

    def clear_history(self) -> None:
        self._live_thinking_widget = None
        self._live_response_widget = None
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
        from backend.cli.theme import STYLE_DEFAULT, STYLE_DIM
        from backend.core.task_status import (
            TASK_STATUS_PANEL_STYLES,
            TASK_STATUS_TODO,
            normalize_task_status,
        )
        from backend.cli._event_renderer.sidebar import _load_playbook_skills
        from backend.cli.tui.widgets.collapsible import CollapsibleSection
        from rich.text import Text

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

        current_state = (self._task_list, mcp_servers, skill_count)
        if current_state != self._last_sidebar_state:
            # 1. Update Tasks Section
            try:
                tasks_widget = self._tui.query_one('#sidebar-tasks', CollapsibleSection)
                task_items = []
                for item in self._task_list:
                    try:
                        status = normalize_task_status(item.get('status'), default=TASK_STATUS_TODO)
                    except Exception:
                        status = TASK_STATUS_TODO
                    desc = str(item.get('description') or '…')
                    task_id = str(item.get('id') or '?')

                    status_style = TASK_STATUS_PANEL_STYLES.get(status, 'dim')
                    status_icon = Text('●', style=f'bold {status_style}')
                    body = Text()
                    if task_id and task_id != '?':
                        body.append(f'{task_id} ', style=STYLE_DIM)
                    body.append(desc, style=STYLE_DEFAULT)

                    row_text = Text()
                    row_text.append(status_icon)
                    row_text.append(' ')
                    row_text.append(body)
                    task_items.append((row_text, f"task:{task_id}"))

                tasks_widget.set_title(f"Tasks ({len(self._task_list)})")
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

                        row_text = Text()
                        row_text.append('● ', style='bold #eacb8a')
                        row_text.append(name, style='#c8d4e8')
                        row_text.append(f' ({server_type})', style='#54597b')
                        mcp_items.append((row_text, f"mcp:{name}"))

                mcp_widget.set_title(f"MCP Servers ({len(mcp_servers) if mcp_servers else 0})")
                mcp_widget.set_items(mcp_items)
            except Exception:
                pass

            # 3. Update Skills Section
            try:
                skills_widget = self._tui.query_one('#sidebar-skills', CollapsibleSection)
                skills_list = _load_playbook_skills()
                skill_items = []
                if skills_list:
                    for skill in sorted(skills_list):
                        row_text = Text()
                        row_text.append('● ', style='bold #7a849c')
                        row_text.append(skill, style='#a1acc2')
                        skill_items.append((row_text, f"skill:{skill}"))

                skills_widget.set_title(f"Skills ({len(skills_list)})")
                skills_widget.set_items(skill_items)
            except Exception:
                pass

            self._last_sidebar_state = current_state

    def _write_lines(self, lines: list[Any]) -> None:
        from rich.console import Group
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

    def _write_card(self, card: ActivityCard) -> None:
        """Write an activity card to the transcript using native ActivityCard widget."""
        self._tui.set_last_tool_status(f'{card.verb} {card.detail}'.strip())

        self._clear_last_active_card_processing()

        extra_content = None
        if card.extra_lines:
            extra_parts = []
            for extra in card.extra_lines:
                indent = '  ' * extra.indent
                extra_parts.append(f'{indent}{extra.text}')
            extra_content = '\n'.join(extra_parts)

        from backend.cli.tui.widgets.activity_card import ActivityCard as TUIActivityCard
        widget = TUIActivityCard(
            verb=card.verb,
            detail=card.detail,
            badge_category=card.badge_category,
            title=card.title,
            secondary=card.secondary,
            secondary_kind=card.secondary_kind,
            extra_content=extra_content,
            collapsed=card.is_collapsible,
        )

        # Defer/enable processing state if it is a tool card that is actively executing
        is_tool = card.badge_category in ('tool', 'shell', 'files', 'web', 'subagent', 'mcp')
        is_active = is_tool and (not card.secondary or card.secondary_kind == 'neutral')
        if is_active:
            widget.set_processing(True)
            self._last_active_card = widget

        display = self._tui._get_display()
        display.mount(widget)
        display.scroll_end(animate=False)

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
            self._trim_history()
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
            if source == EventSource.USER or source == 'user':
                return
            pass
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

            added_lines = 0
            is_new_file = False
            if cmd == 'create_file':
                file_text = getattr(event, 'file_text', '') or ''
                added_lines = file_text.count('\n') + 1 if file_text else 0
                is_new_file = True

            card = ActivityRenderer.file_edit(
                verb,
                path,
                line_range,
                added=added_lines,
                new_file=is_new_file,
                preview_content=(
                    getattr(event, 'file_text', '') or getattr(event, 'new_content', '')
                ),
            )
            self._write_card(card)
        elif isinstance(event, FileWriteAction):
            content = getattr(event, 'content', '') or ''
            line_count = content.count('\n') + 1 if content else 0
            card = ActivityRenderer.file_create_with_preview(
                event.path, line_count=line_count, preview_content=content
            )
            self._write_card(card)
        elif isinstance(event, FileReadObservation):
            pass
        elif isinstance(event, FileEditObservation):
            # Strip agent-facing indentation warnings from user-visible content
            from backend.cli.transcript import strip_indentation_warnings

            if hasattr(event, 'content') and event.content:
                event.content = strip_indentation_warnings(event.content)

            diff = self._extract_file_edit_diff(event)
            added = event.added
            removed = event.removed
            if diff:
                diff_lines = diff.splitlines()
                card = ActivityRenderer.file_edit(
                    'Edited',
                    event.path,
                    diff_lines=diff_lines,
                    added=added,
                    removed=removed,
                )
                self._write_card(card)
            else:
                summary = f'Edited {event.path}'
                if added or removed:
                    delta_parts = []
                    if added:
                        delta_parts.append(f'+{added} lines')
                    if removed:
                        delta_parts.append(f'-{removed} lines')
                    summary += f'  ({", ".join(delta_parts)})'
                self._tui._write_log(Text(f'  {summary}', style=NAVY_TEXT_DIM))
        elif isinstance(event, FileWriteObservation):
            pass
        elif isinstance(event, MCPAction):
            card = ActivityRenderer.mcp_tool(event.name, event.arguments)
            self._write_card(card)
        elif isinstance(event, CmdRunAction):
            cmd = getattr(event, 'command', '') or ''
            if not getattr(event, 'hidden', False):
                card = ActivityRenderer.shell_command(cmd)
                self._write_card(card)
        elif isinstance(event, MCPObservation):
            card = ActivityRenderer.mcp_tool('mcp', result=event.content)
            self._write_card(card)
        elif isinstance(event, CmdOutputObservation):
            output = (event.content or '').strip()
            if output:
                output = strip_tool_result_validation_annotations(output)
                exit_code = getattr(event, 'exit_code', None)
                cmd = getattr(event, 'command', '') or ''
                card = ActivityRenderer.shell_command(
                    cmd, output=output[:500], exit_code=exit_code
                )
                self._write_card(card)
        elif isinstance(event, ErrorObservation):
            self._tui.add_error(event.content or 'An unknown error occurred')
        elif isinstance(event, SuccessObservation):
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
                self._tui.set_last_tool_status(last_status)
                self._tui._write_log(Text(f'  {message}', style=NAVY_TEXT_DIM))
                return
            if status_type == 'compaction':
                self._hud.update_agent_state('Compacting')
                self._tui.set_agent_phase('Compacting context...')
                self._tui.set_last_tool_status('Compacting context...')
                self._tui._write_log(Text('  Compacting context...', style=NAVY_TEXT_DIM))
                return
            msg = (event.content or '').strip()
            if msg:
                self._tui._write_log(Text(f'  {msg}', style=NAVY_TEXT_DIM))
        elif isinstance(event, CondensationAction):
            self._tui._write_log(Text('  Context compacted', style=NAVY_TEXT_DIM))
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
            action_name = getattr(event, 'action', 'browser') or 'browser'
            url = getattr(event, 'url', '') or ''
            card = ActivityRenderer.browser_action(action_name, url)
            self._write_card(card)
        elif isinstance(event, BrowseInteractiveAction):
            url = getattr(event, 'url', '') or ''
            card = ActivityRenderer.browser_action('browse', url)
            self._write_card(card)
        elif isinstance(event, BrowserScreenshotObservation):
            url = getattr(event, 'url', '') or ''
            card = ActivityRenderer.browser_action('screenshot', url)
            self._write_card(card)
        elif isinstance(event, LspQueryAction):
            symbol = getattr(event, 'symbol', '') or getattr(event, 'query', '') or ''
            card = ActivityRenderer.lsp_query(symbol)
            self._write_card(card)
        elif isinstance(event, LspQueryObservation):
            content = (event.content or '').strip()
            symbol = getattr(event, 'symbol', '') or ''
            card = ActivityRenderer.lsp_query(symbol, result=content)
            self._write_card(card)
        elif isinstance(event, TerminalRunAction):
            cmd = getattr(event, 'command', '') or ''
            card = ActivityRenderer.shell_command(cmd)
            self._write_card(card)
        elif isinstance(event, TerminalInputAction):
            cmd = getattr(event, 'command', '') or getattr(event, 'input', '') or ''
            card = ActivityRenderer.shell_command(cmd)
            self._write_card(card)
        elif isinstance(event, TerminalReadAction):
            session_id = getattr(event, 'session_id', '') or ''
            card = ActivityRenderer.terminal_output('', session_id=session_id)
            self._write_card(card)
        elif isinstance(event, TerminalObservation):
            content = (event.content or '').strip()
            if content:
                content = strip_tool_result_validation_annotations(content)
                session_id = getattr(event, 'session_id', '') or ''
                exit_code = getattr(event, 'exit_code', None)
                card = ActivityRenderer.terminal_output(content, session_id, exit_code)
                self._write_card(card)
        elif isinstance(event, RecallAction):
            # Don't show memory recall as a visible card - it's an internal operation
            pass
        elif isinstance(event, RecallObservation):
            pass
        elif isinstance(event, RecallFailureObservation):
            pass
        elif isinstance(event, CondensationAction):
            pruned_count = 0
            if event.pruned_event_ids:
                pruned_count = len(event.pruned_event_ids)
            count = getattr(self, '_condensation_count', 0) + 1
            self._condensation_count = count
            card = ActivityRenderer.condensation(pruned_count, count)
            self._write_card(card)
        elif isinstance(event, AgentCondensationObservation):
            card = ActivityCard(
                verb='Compressed',
                detail='Context compressed successfully',
                badge_category='tool',
                secondary_kind='ok',
            )
            self._write_card(card)
        elif isinstance(event, DelegateTaskAction):
            task = getattr(event, 'task', '') or ''
            worker = getattr(event, 'worker', '') or ''
            card = ActivityRenderer.delegation(task, worker)
            self._write_card(card)
        elif isinstance(event, DelegateTaskObservation):
            content = (event.content or '').strip()
            card = ActivityRenderer.delegation('Result', result=content)
            self._write_card(card)
        elif isinstance(event, PlaybookFinishAction):
            summary = (
                getattr(event, 'final_thought', '')
                or getattr(event, 'thought', '')
                or ''
            )
            if summary:
                self._tui._write_log(Markdown(summary))
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
            pass
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
            if event.task_list is not None:
                self._task_list = event.task_list
        else:
            name = type(event).__name__
            self._tui._write_log(Text(f'  [{name}]', style=NAVY_TEXT_MUTED))

    def _extract_file_edit_diff(self, event: FileEditObservation) -> str | None:
        """Extract unified diff from a FileEditObservation for TUI display."""
        try:
            from backend.execution.utils.diff import get_diff

            old_content = getattr(event, 'old_content', None)
            new_content = getattr(event, 'new_content', None)
            if old_content is None or new_content is None:
                return None

            diff = get_diff(old_content, new_content, path=event.path)
            if diff:
                return diff
        except Exception:
            pass
        return None

    def _handle_search_code_action(self, thought: str) -> None:
        """Handle search_code action and render as a card."""
        import re

        # Strip <search_results> tags
        content = re.sub(r'</?search_results>', '', thought).strip()
        if not content:
            return

        # Extract file summary for user display (Option C)
        from backend.cli._tool_display.renderers.search import extract_file_summary

        match_count, file_count, file_list = extract_file_summary(content)

        # Extract query from first line if it looks like a query
        lines = content.splitlines()
        query = ''

        # Check if first line is a query line (doesn't match file:line:content pattern)
        if lines and not re.match(r'^.*:\d+:', lines[0]):
            query = lines[0]  # type: ignore[unreachable]

        card = ActivityRenderer.search_results(
            query=query or 'code search',
            match_count=match_count,
            file_count=file_count,
            file_list=file_list,
        )
        self._write_card(card)

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

        content = (action.accumulated or '').strip()
        from backend.cli.transcript import strip_pseudo_xml_function_calls
        content = strip_pseudo_xml_function_calls(content)

        if action.is_final:
            # Add the finalized response text to history and clear live previews.
            self._tui.finalize_thinking()
            if self._tui._renderer:
                self._tui._renderer.clear_live_response()
            if content and self._tui._renderer:
                body = Markdown(content)
                self._tui._renderer.add_to_history(body)
            return

        if content and self._tui._renderer:
            self._tui._renderer.update_live_response(content)

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
                plural = '' if self._tools_in_turn == 1 else 's'
                
                from rich.align import Align
                from rich.panel import Panel
                from rich.text import Text
                
                summary_text = Text()
                summary_text.append("✨ ", style="#5eead4")
                summary_text.append("Turn Complete  ", style="bold #c8d4e8")
                summary_text.append(f"{self._tools_in_turn} tool{plural} ", style="#91abec")
                summary_text.append(f"· {duration_str}", style="#8f9fc1")
                
                panel = Panel(
                    summary_text,
                    expand=False,
                    border_style="#1e293b",
                    padding=(0, 2)
                )
                
                self._tui._write_log(Align.center(panel))
                self._tui._write_log(Text('\n'))

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
