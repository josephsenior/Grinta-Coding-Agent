"""Grinta TUI — Textual Application screen and widgets.

Clean minimal layout with proper widget architecture, unified activity cards,
and incremental transcript updates.
"""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Label, Static, TextArea

_tui_logger = logging.getLogger('grinta.tui')
_tui_logger.setLevel(logging.DEBUG)

from backend.cli._event_renderer.unified_renderer import ActivityCard, ActivityLine, ActivityRenderer
from backend.cli._tool_display.renderers import (
    render_browser_navigation,
    render_browser_screenshot,
    render_condensation_action,
    render_condensation_complete,
    render_delegation_action,
    render_delegation_result,
    render_file_create,
    render_file_download,
    render_file_edit,
    render_file_read,
    render_lsp_query,
    render_lsp_result,
    render_mcp_tool,
    render_memory_update,
    render_server_ready,
    render_shell_command,
    render_terminal_output,
    render_terminal_read,
    render_user_reject,
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
from backend.core.bootstrap.setup import create_memory, create_runtime
from backend.core.enums import AgentState, EventSource
from backend.core.logger import app_logger as logger
from backend.ledger import EventStream, EventStreamSubscriber
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
from backend.orchestration.conversation_stats import ConversationStats  # noqa: E402
from backend.orchestration.orchestration_config import OrchestrationConfig  # noqa: E402
from backend.orchestration.session_orchestrator import SessionOrchestrator  # noqa: E402
from backend.persistence import get_file_store  # noqa: E402


def _rich_text(text: str) -> Text:
    """Convert text with potential ANSI and markup to a Rich Text object."""
    return Text.from_ansi(text)


def _strip_ansi(text: str) -> str:
    """Strip all ANSI escape sequences from text using Rich's parser."""
    return _rich_text(text).plain


# ── Widget classes ────────────────────────────────────────────────────────


class InfoSidebar(VerticalScroll):
    """Sidebar for Mission Control info (Tasks, MCPs, Skills)."""


class Transcript(VerticalScroll):
    """Scrollable conversation transcript container."""


class InputBar(Horizontal):
    """Bottom input row with border and prompt."""


class HUD(Vertical):
    """Multi-line status bar at the very bottom."""
    def compose(self) -> ComposeResult:
        yield Label(id='hud-line-1')
        yield Label(id='hud-line-2')


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


# ── Main screen ───────────────────────────────────────────────────────────


class GrintaScreen(Screen):
    """Main TUI screen — Mission Control layout."""

    CSS_PATH = 'styles.tcss'

    BINDINGS = [
        Binding('ctrl+c', 'copy_or_interrupt', 'Copy/Interrupt', show=True),
        Binding('ctrl+shift+c', 'copy_transcript', 'Copy Transcript', show=True),
        Binding('escape', 'interrupt_agent', 'Interrupt', show=False),
        Binding('ctrl+l', 'clear_transcript', 'Clear', show=True),
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

        self._bootstrapping: asyncio.Event | None = None

    _STATE_LABELS = {
        'starting': 'Starting…',
        'loading': 'Loading…',
        'running': 'Running',
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

    def compose(self) -> ComposeResult:
        with Horizontal(id='main-layout'):
            with Transcript(id='transcript-container'):
                yield Static(id='main-display')
            with InfoSidebar(id='sidebar-container'):
                yield Static(id='sidebar-display')
        with InputBar(id='input-bar'):
            yield Static(id='spinner', classes='-hidden')
            yield TextArea(id='input', show_line_numbers=False)
        yield HUD(id='hud-bar')

    def on_mount(self) -> None:
        _tui_logger.debug('on_mount: GrintaScreen mounted')

        self._render_hud_bar()
        ta = self.query_one('#input', TextArea)
        ta.text = ''
        ta.focus()
        transcript = self.query_one('#transcript-container', Transcript)
        transcript.scroll_home(animate=False)
        _tui_logger.debug('on_mount: done')
        self._start_background_bootstrap()


    def _start_background_bootstrap(self) -> None:
        async def _bg():
            try:
                await self._bootstrap()
            except Exception as exc:
                _tui_logger.debug(f'background bootstrap failed: {exc}')
        asyncio.create_task(_bg())

    def on_unmount(self) -> None:
        _tui_logger.debug('on_unmount: GrintaScreen unmounting')
        if self._renderer:
            if self._renderer._event_stream:
                self._renderer._event_stream.unsubscribe(EventStreamSubscriber.MAIN, 'grinta-tui')
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
        _tui_logger.debug('on_unmount: done')

    # ── HUD Bar ─────────────────────────────────────────────

    def _render_hud_bar(self) -> None:
        hud = self._hud
        raw_state = hud.state.agent_state_label or 'Ready'
        lookup_key = raw_state.lower()
        if lookup_key.startswith('agentstate.'):
            lookup_key = lookup_key[len('agentstate.') :]
        if '.' in lookup_key:
            lookup_key = lookup_key.split('.')[-1]

        display_state = self._STATE_LABELS.get(lookup_key, 'Ready')
        state_color = self._STATE_COLORS.get(lookup_key, NAVY_BRAND)

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
        line1 = f'[#91abec bold]GRINTA[/]  |  [#bbc8e8 bold]Workspace: {workspace}[/]  |  [#8f9fc1]Version: 1.0 rc[/]'

        # Build second-line HUD
        line2_parts = []
        line2_parts.append(f'[{state_color}]● {display_state}[/]')
        line2_parts.append(f'[{NAVY_TEXT_SECONDARY}]Model: {model_display}[/]')
        line2_parts.append(f'[{NAVY_BRAND}]Auto: {autonomy}[/]')
        line2_parts.append(f'[{NAVY_TEXT_DIM}]Tokens: {used:,}[/]')
        line2_parts.append(f'[{NAVY_TEXT_PRIMARY}]${cost:.4f}[/]')
        line2_parts.append(f'[{NAVY_TEXT_DIM}]Calls: {calls}[/]')

        hud = self.query_one('#hud-bar', HUD)
        hud.query_one('#hud-line-1', Label).update(line1)
        hud.query_one('#hud-line-2', Label).update('  |  '.join(line2_parts))

    # ── Transcript helpers ──────────────────────────────────────────────────

    def _get_display(self) -> Static:
        return self.query_one('#main-display', Static)

    def _get_sidebar(self) -> Static:
        return self.query_one('#sidebar-display', Static)

    @staticmethod
    def _break_long_runs(text: str, max_len: int = 80) -> str:
        """Insert zero-width spaces in long continuous runs, preserving Rich markup tags."""
        def _break_word(w: str) -> str:
            if len(w) > max_len and not w.isspace():
                return '\u200b'.join(w[i:i+max_len] for i in range(0, len(w), max_len))
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
        """User message — clear bold header."""
        self._hide_thinking()
        header = Text('\nYOU\n', style='bold #91abec')
        body = _rich_text(text)
        self._write_log(Text.assemble(header, body, '\n'))

    def add_agent_message(self, text: str) -> None:
        """Agent response — clear bold header."""
        self.finalize_thinking()
        header = Text('\nGRINTA\n', style='bold #54efae')
        body = _rich_text(text)
        self._write_log(Text.assemble(header, body, '\n'))

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

    def add_error(self, text: str) -> None:
        icon = Text('✗ ', style=f'bold {NAVY_ERROR}')
        body = _rich_text(text)
        body.stylize(f'bold {NAVY_ERROR}')
        self._write_log(Text.assemble(icon, body))

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
            self._write_log(Text.assemble(icon, name, ' (', cmd_text, ')', style='#969aad'))
        else:
            self._write_log(Text.assemble(icon, name))

    def add_tool_result(self, text: str) -> None:
        """Tool result — muted text."""
        body = _rich_text(text)
        body.stylize(NAVY_TEXT_MUTED)
        self._write_log(Text.assemble('  ', body))

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
            'Question',
            Group(*clarify_parts),
            accent_style=DECISION_PANEL_ACCENT_STYLE
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
            'Needs Context',
            Group(*parts),
            accent_style=DECISION_PANEL_ACCENT_STYLE
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
            label = opt.get('name', opt.get('title', f'Option {i+1}'))
            marker = ' (recommended)' if i == action.recommended else ''
            line = Text()
            line.append(f'{i+1}. ', style=f'bold {DECISION_PANEL_ACCENT_STYLE}')
            line.append(f'{label}{marker}', style=f'bold {CLR_OPTION_RECOMMENDED}' if i == action.recommended else f'bold {CLR_OPTION_TEXT}')
            parts.append(line)
            desc = opt.get('description', '')
            if desc:
                parts.append(Text(f'   {desc}', style=STYLE_DIM))

        panel = format_callout_panel(
            'Options',
            Group(*parts),
            accent_style=DECISION_PANEL_ACCENT_STYLE
        )
        self._write_log(panel)

    def add_communicate_escalate(self, action: EscalateToHumanAction) -> None:
        """Agent escalates to human."""
        from backend.cli.layout_tokens import DECISION_PANEL_ACCENT_STYLE
        from backend.cli.theme import CLR_QUESTION_TEXT
        from backend.cli.transcript import format_callout_panel

        t_reason = _rich_text(action.reason or 'The agent needs your input to continue.')
        t_reason.stylize(CLR_QUESTION_TEXT)

        panel = format_callout_panel(
            'Need Your Input',
            t_reason,
            accent_style=DECISION_PANEL_ACCENT_STYLE
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
                    from rich.text import Text
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

            if self._controller is not None:
                mark = getattr(self._controller, 'mark_user_interrupt_stop', None)
                if callable(mark):
                    mark()
                with contextlib.suppress(Exception):
                    await self._controller.stop()

            if self._renderer is not None:
                self._renderer.add_system_message(
                    'Interrupted. Ready for input.', title='grinta'
                )

            self.finalize_thinking()
            spinner = self.query_one('#spinner', Static)
            spinner.add_class('-hidden')
            self.query_one('#input-bar', InputBar).remove_class('processing')

        asyncio.create_task(_do_interrupt())

    def action_scroll_up(self) -> None:
        """Scroll transcript up by one page."""
        transcript = self.query_one('#transcript-container', Transcript)
        transcript.scroll_page_up(animate=True)

    def action_scroll_down(self) -> None:
        """Scroll transcript down by one page."""
        transcript = self.query_one('#transcript-container', Transcript)
        transcript.scroll_page_down(animate=True)

    def action_scroll_home(self) -> None:
        """Scroll transcript to top."""
        transcript = self.query_one('#transcript-container', Transcript)
        transcript.scroll_home(animate=True)

    def action_scroll_end(self) -> None:
        """Scroll transcript to bottom."""
        self._scroll_to_bottom()

    def action_toggle_sidebar(self) -> None:
        """Toggle sidebar visibility."""
        sidebar = self.query_one('#sidebar-container', InfoSidebar)
        if sidebar.has_class('-hidden'):
            sidebar.remove_class('-hidden')
            transcript = self.query_one('#transcript-container', Transcript)
            transcript.styles.width = '70%'
        else:
            sidebar.add_class('-hidden')
            transcript = self.query_one('#transcript-container', Transcript)
            transcript.styles.width = '100%'

    def action_show_help(self) -> None:
        """Show help information."""
        self.show_help()

    def _scroll_to_bottom(self) -> None:
        self.query_one('#transcript-container', Transcript).scroll_end(animate=False)

    # ── Input handling ──────────────────────────────────────────────────────

    def action_submit_input(self) -> None:
        _tui_logger.debug(f'action_submit_input: lock_locked={self._input_lock.locked()}')
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
                    _tui_logger.debug(f'_handle_input task FAILED: {type(exc).__name__}: {exc}')
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
            _tui_logger.debug(f'_handle_input: _trace FAILED: {type(exc).__name__}: {exc}')
        async with self._input_lock:
            # Drain any stale events from previous turn before starting new one
            if self._renderer:
                self._renderer.drain_events()

            ta = self.query_one('#input', TextArea)
            ta.clear()
            ta.focus()
            self._scroll_to_bottom()

            if text.startswith('/'):
                await self._handle_slash_command(text)
                return

            self.add_user_message(text)
            self._render_hud_bar()
            self.query_one('#input-bar', InputBar).add_class('processing')

            try:
                _tui_logger.debug(f'_handle_input: controller={self._controller is not None}')
                if self._controller is None:
                    if self._bootstrapping is not None and not self._bootstrapping.is_set():
                        _tui_logger.debug('_handle_input: waiting for background bootstrap')
                        logger.info('[TUI] _handle_input: waiting for background bootstrap')
                        await self._bootstrapping.wait()
                    if self._controller is None:
                        _tui_logger.debug('_handle_input: calling _bootstrap()')
                        logger.info('[TUI] _handle_input: bootstrapping (no controller)')
                    # Internal bootstrap - no user-facing message
                    await self._bootstrap()
                    if self._controller is None:
                        raise RuntimeError('Bootstrap failed to initialize controller')
                    _tui_logger.debug(
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
                assert self._controller is not None, 'Controller must be initialized after agent task setup'
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
                actual_state = str(self._controller.get_agent_state()) if self._controller else ''
                self._hud.update_agent_state(actual_state or 'Ready')
                self._render_hud_bar()
                self._render_hud_bar()

    def update_hud(self) -> None:
        self._hud.update_agent_state(self._hud.state.agent_state_label or 'Ready')
        self._render_hud_bar()

    async def _handle_slash_command(self, text: str) -> None:
        cmd = text.lower().strip()
        if cmd in ('/help', '/h', '/?'):
            self.show_help()
        elif cmd in ('/clear', '/c'):
            self.clear_transcript()
        elif cmd in ('/quit', '/q', '/exit'):
            self._agent_running = False
            self.app.exit()
        elif cmd == '/settings':
            self.add_system_message('/settings opens settings TUI (coming soon)')
        elif cmd == '/sessions':
            self.add_system_message('/sessions opens sessions manager (coming soon)')
        else:
            self.add_error(f'Unknown command: {text}')

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
            f'  [{NAVY_TEXT_SECONDARY}]/quit[/]      [{NAVY_TEXT_TERTIARY}]Exit Grinta[/]\n'
            f'  [{NAVY_TEXT_SECONDARY}]Ctrl+C[/]     [{NAVY_TEXT_TERTIARY}]Stop agent[/]\n'
            f'  [{NAVY_TEXT_SECONDARY}]Tab[/]        [{NAVY_TEXT_TERTIARY}]Newline in input[/]'
        )
        self._write_log(help_text)
        self.add_divider()
        self._scroll_to_bottom()

    # ── Bootstrap (preserved agent logic) ───────────────────────────────────

    async def _bootstrap(self) -> None:
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
            try:
                agent, event_stream, runtime = await asyncio.to_thread(
                    self._bootstrap_sync_phase1, config
                )
            except Exception as exc:
                _tui_logger.debug(f'_bootstrap: EXCEPTION phase1 {type(exc).__name__}: {exc}')
                logger.exception('TUI _bootstrap: failed in phase1')
                raise

            _tui_logger.debug(f'_bootstrap: runtime created, type={type(runtime).__name__}')

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
                    self._bootstrap_sync_phase2, agent, runtime, event_stream, config
                )
            except Exception as exc:
                _tui_logger.debug(f'_bootstrap: EXCEPTION phase2 {type(exc).__name__}: {exc}')
                logger.exception('TUI _bootstrap: failed in phase2')
                raise

            _tui_logger.debug(f'_bootstrap: controller created, state={controller.get_agent_state()}')
            logger.info(
                'TUI _bootstrap: controller created, initial state=%s (type=%s)',
                controller.get_agent_state(),
                type(controller.get_agent_state()),
            )

            self._event_stream = event_stream
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
            raise
        finally:
            _bootstrapping.set()

    def _bootstrap_sync_phase1(
        self,
        config: Any,
    ) -> tuple[Any, Any, Any]:
        _tui_logger.debug('_bootstrap_sync_phase1: get_file_store')
        file_store = get_file_store(config)
        _tui_logger.debug('_bootstrap_sync_phase1: EventStream')
        event_stream = EventStream(sid='grinta-tui', file_store=file_store)
        _tui_logger.debug('_bootstrap_sync_phase1: create_registry_and_conversation_stats')
        llm_registry, _conv_stats, _app_cfg = create_registry_and_conversation_stats(
            config,
            sid=event_stream.sid,
            user_id='tui',
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
        return agent, event_stream, runtime

    def _bootstrap_sync_phase2(
        self,
        agent: Any,
        runtime: Any,
        event_stream: Any,
        config: Any,
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
    ) -> Any:
        return SessionOrchestrator(
            config=OrchestrationConfig(
                agent=agent,
                event_stream=event_stream,
                conversation_stats=ConversationStats(
                    file_store=event_stream.file_store,
                    conversation_id=event_stream.sid,
                    user_id=None,
                ),
                iteration_delta=config.max_iterations,
                headless_mode=True,
            )
        )

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
                exc = t.exception()
                if exc:
                    _tui_logger.debug(f'_agent_task FAILED: {type(exc).__name__}: {exc}')
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
            _tui_logger.debug('_dispatch_to_agent: missing controller or event_stream, returning')
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
                await asyncio.sleep(0.1)
                loop_count += 1
                state = self._controller.get_agent_state()
                if loop_count == 1 or loop_count % 20 == 0:
                    _tui_logger.debug(f'_dispatch_to_agent: poll #{loop_count}, state={state}')
                    logger.info(
                        '[TUI] _dispatch_to_agent: poll #%d, state=%s',
                        loop_count,
                        state,
                    )
                if self._renderer:
                    self._renderer.drain_events()
                if state in end_states:
                    _tui_logger.debug(f'_dispatch_to_agent: reached end state {state}')
                    logger.info('[TUI] _dispatch_to_agent: reached end state %s', state)
                    break
                if self._agent_task and self._agent_task.done():
                    _tui_logger.debug(f'_dispatch_to_agent: agent task done, state={state}')
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

        # History & Live state
        self._history: list[Any] = []
        self._live_thinking: str = ''
        self._task_list: list[dict[str, Any]] = []
        self._last_sidebar_state: Any = None

        # Turn tracking for grouping tool calls by agent turn
        self._turn_count: int = 0
        self._in_agent_turn: bool = False
        self._tools_in_turn: int = 0
        self._turn_start_time: float = 0.0

    def subscribe(self, event_stream: Any, sid: str) -> None:
        self._event_stream = event_stream
        event_stream.subscribe(EventStreamSubscriber.MAIN, self._on_event, sid)

    def add_to_history(self, renderable: Any) -> None:
        """Add a finalized renderable to history and refresh display."""
        if isinstance(renderable, str):
            renderable = Text.from_markup(renderable)
        self._history.append(renderable)
        # Add margin after tool result
        self._history.append(Text(''))
        self._refresh_display()

    def update_live_thinking(self, text: str) -> None:
        """Update the real-time reasoning buffer."""
        is_first_chunk = not self._live_thinking
        self._live_thinking = text

        if is_first_chunk:
            # First thinking chunk - append to history at its correct position
            body = _rich_text(text)
            body.stylize(NAVY_TEXT_MUTED)
            self._history.append(Text.assemble(body, '\n'))
        else:
            # Subsequent chunks - replace the last item (which is the thinking text)
            if self._history:
                body = _rich_text(text)
                body.stylize(NAVY_TEXT_MUTED)
                self._history[-1] = Text.assemble(body, '\n')

        self._refresh_display()

    def commit_live_thinking(self) -> None:
        """Commit live thinking to history and clear buffer."""
        # Thinking is already in history at the correct position - just clear the buffer
        self._live_thinking = ''
        self._refresh_display()

    def clear_history(self) -> None:
        self._history = []
        self._live_thinking = ''
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Build the full Rich Group and update the Textual Static widgets."""
        from rich.console import Group

        from backend.cli._event_renderer.sidebar import build_sidebar

        # 1. Main Display
        # Thinking is now stored directly in _history - just render it as-is
        items = list(self._history)

        try:
            self._tui._get_display().update(Group(*items))
        except NoMatches:
            return
        self._tui._scroll_to_bottom()

        # 2. Sidebar (Optimized: only update if state changed)
        mcp_count = self._hud.state.mcp_servers
        skill_count = self._hud.bundled_skill_count

        # Build actual MCP server list from config
        mcp_servers = None
        if self._tui._config and getattr(self._tui._config, 'mcp', None) and getattr(self._tui._config.mcp, 'servers', None):
            mcp_servers = [{'name': s.name, 'type': s.type} for s in self._tui._config.mcp.servers if s.name != 'app-mcp']

        if not mcp_servers and mcp_count:
            mcp_servers = [{'name': f'MCP Server {i+1}', 'type': 'active'} for i in range(mcp_count)]

        current_state = (self._task_list, mcp_servers, skill_count)
        if current_state != self._last_sidebar_state:
            sidebar = build_sidebar(
                task_list=self._task_list,
                mcp_servers=mcp_servers,
                skill_count=skill_count,
                terminal_width=self._console.width
            )
            if sidebar:
                self._tui._get_sidebar().update(sidebar)
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
        self._tui._write_log(Group(*items))

    def _write_card(self, card: ActivityCard) -> None:
        """Write an activity card to the transcript using unified markup."""
        markup = card.to_tui_markup()
        self._tui._write_log(Text.from_markup(markup))

    def drain_events(self) -> None:
        if not self._pending_events:
            self._refresh_display() # Keep sidebar/HUD in sync
            return
        with self._pending_lock:
            while self._pending_events:
                event = self._pending_events.popleft()
                self._process_event(event)
        self._refresh_display()

    def _on_event(self, event: Any) -> None:
        with self._pending_lock:
            self._pending_events.append(event)
        try:
            self._loop.call_soon_threadsafe(self._state_event.set)
        except RuntimeError:
            pass

    def _process_event(self, event: Any) -> None:
        self._update_metrics(event)
        if isinstance(event, NullAction) or isinstance(event, NullObservation):
            return

        source = getattr(event, 'source', None)

        # Detect start of agent turn (first tool action after user input)
        if not self._in_agent_turn and not isinstance(event, (MessageAction, StreamingChunkAction, AgentStateChangedObservation)):
            self._in_agent_turn = True
            self._turn_count += 1
            self._tools_in_turn = 0
            self._turn_start_time = time.monotonic()


        # Count tools in current turn
        if self._in_agent_turn and isinstance(event, (FileReadAction, FileEditAction, FileWriteAction,
            CmdRunAction, MCPAction, BrowserToolAction, BrowseInteractiveAction,
            LspQueryAction, TerminalRunAction, TerminalInputAction, TerminalReadAction,
            RecallAction, DelegateTaskAction)):
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
                if edit_mode == 'range' and start_line is not None and end_line is not None:
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

            card = ActivityRenderer.file_edit(verb, path, line_range, added=added_lines, new_file=is_new_file)
            self._write_card(card)
        elif isinstance(event, FileWriteAction):
            content = getattr(event, 'content', '') or ''
            line_count = content.count('\n') + 1 if content else 0
            card = ActivityRenderer.file_create(event.path, line_count=line_count)
            self._write_card(card)
        elif isinstance(event, FileReadObservation):
            pass
        elif isinstance(event, FileEditObservation):
            diff = self._extract_file_edit_diff(event)
            added = event.added
            removed = event.removed
            if diff:
                diff_lines = diff.splitlines()
                card = ActivityRenderer.file_edit('Edited', event.path, diff_lines=diff_lines, added=added, removed=removed)
                self._write_card(card)
            else:
                summary = f'Edited {event.path}'
                if added or removed:
                    delta_parts = []
                    if added:
                        delta_parts.append(f'+{added} lines')
                    if removed:
                        delta_parts.append(f'-{removed} lines')
                    summary += f"  ({', '.join(delta_parts)})"
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
                card = ActivityRenderer.shell_command(cmd, output=output[:500], exit_code=exit_code)
                self._write_card(card)
        elif isinstance(event, ErrorObservation):
            self._tui.add_error(event.content or 'An unknown error occurred')
        elif isinstance(event, SuccessObservation):
            self._tui.add_success(event.content or 'Done')
        elif isinstance(event, StatusObservation):
            msg = (event.content or '').strip()
            if msg:
                self._tui._write_log(Text(f'  {msg}', style=NAVY_TEXT_DIM))
        elif isinstance(event, AgentThinkAction):
            thought = getattr(event, 'thought', '') or getattr(event, 'content', '')
            if thought and thought.strip() != 'Your thought has been logged.':
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
            summary = getattr(event, 'final_thought', '') or getattr(event, 'thought', '') or ''
            if summary:
                self._tui._write_log(Text(f'{summary}'))
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
            self._tui._write_log(Text(f'  [bold #91abec]Downloaded[/] {url}', style=NAVY_TEXT_PRIMARY))
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
        """Extract diff from a FileEditObservation for TUI display."""
        try:
            diff = event.visualize_diff()
            if diff and '(no changes detected' not in diff:
                return diff
        except Exception:
            pass
        return None

    def _handle_streaming_chunk(self, action: StreamingChunkAction) -> None:
        if action.is_tool_call:
            return

        thinking = (action.thinking_accumulated or '').strip()
        if thinking and thinking != 'Your thought has been logged.':
            self._tui.add_thinking(thinking)

        if action.is_final:
            # Add the actual response text to history (after thinking)
            content = (action.accumulated or '').strip()
            if content and self._tui._renderer:
                body = _rich_text(content)
                self._tui._renderer.add_to_history(body)
            self._tui.finalize_thinking()

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
        self._hud.update_agent_state(str(state))

        # End agent turn when reaching idle/terminal state
        if self._in_agent_turn and state in (AgentState.AWAITING_USER_INPUT, AgentState.FINISHED, AgentState.ERROR, AgentState.STOPPED):
            self._in_agent_turn = False
            if self._tools_in_turn > 0:
                elapsed = time.monotonic() - self._turn_start_time
                duration_str = f'{elapsed:.1f}s'
                self._tui._write_log(Text.from_markup(f'\n[dim #969aad]  ({self._tools_in_turn} tool{"s" if self._tools_in_turn != 1 else ""} executed · {duration_str})[/dim]\n'))

        # Ensure thinking UI is cleared on any idle/terminal state
        if state in (AgentState.AWAITING_USER_INPUT, AgentState.FINISHED, AgentState.ERROR, AgentState.STOPPED):
            self._tui.finalize_thinking()

        self._state_event.set()
        self._tui._render_hud_bar()
