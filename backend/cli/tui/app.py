"""Grinta TUI — Textual Application screen and widgets."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Label, RichLog, Static, TextArea

from backend.cli.hud import HUDBar
from backend.cli.reasoning_display import ReasoningDisplay
from backend.cli.theme import (
    NAVY_BORDER,
    NAVY_BRAND,
    NAVY_BRAND_DIM,
    NAVY_ERROR,
    NAVY_READY,
    NAVY_TEXT_MUTED,
    NAVY_TEXT_PRIMARY,
    NAVY_TEXT_SECONDARY,
    NAVY_WAITING,
)

if TYPE_CHECKING:
    from backend.cli.config_manager import AppConfig
    from backend.core.enums import AgentState


from backend.core.logger import app_logger as logger


class GrintaHeader(Static):
    """Top status bar — always docked at top."""


class Transcript(VerticalScroll):
    """Scrollable transcript area — main content region."""


class InputArea(Horizontal):
    """Bottom input row — prompt + text entry."""


class GrintaFooter(Static):
    """Context-sensitive hint bar at the very bottom."""


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


class GrintaScreen(Screen):
    """Main TUI screen — agent interaction layout."""

    CSS_PATH = 'styles.tcss'

    BINDINGS = [
        Binding('ctrl+c', 'app.quit', 'Quit', show=True, priority=True),
        Binding('ctrl+l', 'clear_transcript', 'Clear', show=False),
        Binding('ctrl+z', 'suspend', 'Suspend', show=False),
        Binding('enter', 'submit_input', 'Send', show=False, priority=True),
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
        yield GrintaHeader(id='header-bar')
        with Transcript(id='transcript-scroll'):
            yield RichLog(id='transcript-log', markup=True, auto_scroll=True)
        with InputArea(id='input-row'):
            yield Static('❯ ', id='input-prompt')
            yield TextArea(id='input')
        yield GrintaFooter(id='footer-hint')

    def on_mount(self) -> None:
        self._render_header()
        ta = self.query_one('#input', TextArea)
        ta.focus()
        ta.cursor_blink = True
        self._update_footer('Ready. Type a task or /help')
        self.query_one('#transcript-scroll', Transcript).scroll_home(animate=False)

    def _render_header(self) -> None:
        header = self.query_one('#header-bar', GrintaHeader)
        hud = self._hud
        model = hud.state.model or '(not set)'
        workspace = hud.state.workspace_path or Path(os.getcwd()).name
        raw_state = hud.state.agent_state_label or 'Ready'
        display_state = self._STATE_LABELS.get(raw_state.lower(), raw_state)
        state_color = self._STATE_COLORS.get(raw_state.lower(), NAVY_TEXT_SECONDARY)
        header.update(
            f'[bold {NAVY_BRAND}]GRINTA[/]'
            f'  [{NAVY_BORDER}]|[/]'
            f'  [{NAVY_TEXT_SECONDARY}]model[/] [{NAVY_TEXT_PRIMARY}]{model}[/]'
            f'  [{NAVY_BORDER}]|[/]'
            f'  [{NAVY_TEXT_SECONDARY}]ws[/] [{NAVY_TEXT_PRIMARY}]{workspace}[/]'
            f'  [{NAVY_BORDER}]|[/]'
            f'  [{state_color}]{display_state}[/]'
        )

    def action_submit_input(self) -> None:
        if self._input_lock.locked():
            return
        ta = self.query_one('#input', TextArea)
        text = ta.text.strip()
        if not text:
            return
        asyncio.get_running_loop().create_task(self._handle_input(text))

    async def _handle_input(self, text: str) -> None:
        async with self._input_lock:
            ta = self.query_one('#input', TextArea)
            ta.clear()
            ta.focus()
            self._scroll_to_bottom()

            if text.startswith('/'):
                await self._handle_slash_command(text)
                return

            self.add_user_message(text)
            self._update_footer('Working...')
            self.query_one('#input-row', InputArea).add_class('processing')

            try:
                if self._controller is None:
                    await self._bootstrap()
                else:
                    await self._ensure_agent_task()
                await self._dispatch_to_agent(text)
            except Exception:
                logger.exception('Error during agent turn')
                self.add_error('Agent error — check logs')
                self._update_footer('Ready. Type a task or /help')
            finally:
                self._update_footer('Ready. Type a task or /help')
                self.query_one('#input-row', InputArea).remove_class('processing')
                if self._renderer:
                    self._renderer.drain_events()
                    self._update_header_state(
                        self._hud.state.agent_state_label or 'Ready'
                    )

    def _update_header_state(self, state: str) -> None:
        self._hud.update_agent_state(state)
        self._render_header()

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
        self.add_system_message('GRINTA — AI-Powered Development Platform')
        self.add_divider()
        help_text = (
            '  /help      Show this help\n'
            '  /clear     Clear transcript\n'
            '  /settings  Open settings\n'
            '  /sessions  Manage sessions\n'
            '  /quit      Exit Grinta\n'
            '  Ctrl+C     Stop agent\n'
            '  Tab        Newline in input'
        )
        self._get_log().write(help_text)
        self.add_divider()
        self._scroll_to_bottom()

    # ── transcript helpers ──────────────────────────────────────────────────

    @staticmethod
    def _fmt_ts() -> str:
        return datetime.now().strftime(f'[{NAVY_TEXT_SECONDARY}]%H:%M:%S[/]')

    def _get_log(self) -> RichLog:
        return self.query_one('#transcript-log', RichLog)

    def add_user_message(self, text: str) -> None:
        self._get_log().write(
            f'[bold {NAVY_BRAND}]❯[/]'
            f'  {self._fmt_ts()}'
            f'  [{NAVY_TEXT_MUTED}]you[/]'
            f'  [{NAVY_TEXT_PRIMARY}]{text}[/]'
        )

    def add_agent_message(self, text: str) -> None:
        self._get_log().write(
            f'[bold {NAVY_BRAND_DIM}]❯[/]'
            f'  {self._fmt_ts()}'
            f'  [{NAVY_TEXT_MUTED}]grinta[/]'
            f'  [{NAVY_TEXT_PRIMARY}]{text}[/]'
        )

    def add_system_message(self, text: str) -> None:
        self._get_log().write(f'[{NAVY_TEXT_SECONDARY}]{text}[/]')

    def add_error(self, text: str) -> None:
        self._get_log().write(f'[bold {NAVY_ERROR}]✗ {text}[/]')

    def add_success(self, text: str) -> None:
        self._get_log().write(f'[bold {NAVY_READY}]✓ {text}[/]')

    def add_tool_start(self, tool_name: str) -> None:
        self._get_log().write(
            f'  [bold {NAVY_BRAND_DIM}]▸[/]'
            f'  [bold {NAVY_TEXT_PRIMARY}]{tool_name}[/]'
        )

    def add_tool_result(self, text: str) -> None:
        self._get_log().write(f'    [{NAVY_TEXT_MUTED}]{text}[/]')

    def add_divider(self) -> None:
        self._get_log().write(f'[{NAVY_BORDER}]' + '─' * 70 + '[/]')

    def clear_transcript(self) -> None:
        self._get_log().clear()

    def action_clear_transcript(self) -> None:
        self.clear_transcript()

    def action_suspend(self) -> None:
        self._agent_running = False
        self.app.exit()

    def _scroll_to_bottom(self) -> None:
        self.query_one('#transcript-scroll', Transcript).scroll_end(animate=False)

    # ── footer ─────────────────────────────────────────────────────────────

    def _update_footer(self, hint: str) -> None:
        self.query_one('#footer-hint', GrintaFooter).update(
            f'[{NAVY_TEXT_SECONDARY}]{hint}[/]'
        )

    # ── HUD sync ─────────────────────────────────────────────────────────────

    def update_hud(self) -> None:
        self._hud.update_agent_state(self._hud.state.agent_state_label or 'Ready')
        self._render_header()

    # ── bootstrap (synchronous — all core factory calls are sync) ──────────

    async def _bootstrap(self) -> None:
        """Bootstrap the agent engine asynchronously.

        The synchronous factory calls (create_runtime, create_agent, etc.) are
        run in a thread so they don't block the Textual message pump. HUD is
        updated at each phase so the UI stays responsive.
        """
        logger.info('TUI _bootstrap: starting')
        self._hud.update_agent_state('Initializing')
        self._render_header()
        self.add_system_message('Initializing engine...')

        config = self._config

        try:
            agent, memory, event_stream, runtime, controller = await asyncio.to_thread(
                self._bootstrap_sync, config
            )
        except Exception:
            logger.exception('TUI _bootstrap: failed in thread')
            raise

        logger.info(
            'TUI _bootstrap: controller created, initial state=%s (type=%s)',
            controller.get_agent_state(),
            type(controller.get_agent_state()),
        )

        self._event_stream = event_stream
        self._runtime_stub = runtime
        self._memory_stub = memory
        self._controller = controller

        if self._renderer is None:
            self._renderer = TUIRenderer(
                console=self._rich_console,
                hud=self._hud,
                reasoning=self._reasoning,
                tui=self,
                loop=self._loop,
            )
        self._renderer.subscribe(event_stream, event_stream.sid)

        state_after_create = controller.get_agent_state()
        logger.info('TUI _bootstrap: state after renderer subscribe=%s', state_after_create)
        self._hud.update_agent_state(str(state_after_create))
        self._render_header()
        self._renderer.drain_events()
        self.add_system_message('Engine ready.')

    def _bootstrap_sync(
        self, config: Any,
    ) -> tuple[Any, Any, Any, Any, Any]:
        """Synchronous bootstrap — runs in a thread. Returns components tuple."""
        agent, memory, event_stream, runtime = self._create_session(config)
        controller = self._get_or_create_controller(
            agent, runtime, memory, config,
        )
        return agent, memory, event_stream, runtime, controller

    def _create_session(
        self, config: Any,
    ) -> tuple[Any, Any, Any, Any]:
        """Create agent, memory, event stream, and runtime.

        All bootstrap factory calls are synchronous. This mirrors the
        established bootstrap pattern from ``backend.core.bootstrap``.
        """
        from backend.core.bootstrap.main import (
            create_agent,
            create_registry_and_conversation_stats,
        )
        from backend.core.bootstrap.setup import (
            create_memory,
            create_runtime,
        )
        from backend.ledger import EventStream
        from backend.persistence import get_file_store

        file_store = get_file_store(config)
        event_stream = EventStream(sid='grinta-tui', file_store=file_store)

        llm_registry, _conv_stats, _app_cfg = (
            create_registry_and_conversation_stats(
                config,
                sid=event_stream.sid,
                user_id='tui',
            )
        )
        runtime = create_runtime(
            config,
            llm_registry=llm_registry,
            sid=event_stream.sid,
            event_stream=event_stream,
        )
        agent = create_agent(config, llm_registry)
        memory = create_memory(runtime, event_stream, sid=event_stream.sid)
        return agent, memory, event_stream, runtime

    def _get_or_create_controller(
        self, agent: Any, runtime: Any, memory: Any, config: Any,
    ) -> Any:
        from backend.orchestration.conversation_stats import ConversationStats
        from backend.orchestration.orchestration_config import OrchestrationConfig
        from backend.orchestration.session_orchestrator import SessionOrchestrator

        return SessionOrchestrator(
            config=OrchestrationConfig(
                agent=agent,
                event_stream=self._event_stream,
                conversation_stats=ConversationStats(
                    file_store=self._event_stream.file_store,
                    conversation_id=self._event_stream.sid,
                    user_id=None,
                ),
                iteration_delta=config.max_iterations,
                headless_mode=True,
            )
        )

    async def _run_agent_loop(self) -> None:
        """Background agent loop — mirrors REPL's run_agent_until_done pattern."""
        from backend.core.bootstrap.agent_control_loop import run_agent_until_done
        from backend.core.schemas import AgentState

        end_states = [
            AgentState.AWAITING_USER_INPUT,
            AgentState.FINISHED,
            AgentState.ERROR,
            AgentState.STOPPED,
        ]
        try:
            await run_agent_until_done(
                self._controller,
                self._runtime_stub,
                self._memory_stub,
                end_states,
            )
        except Exception:
            logger.exception('Agent loop exited with error')

    async def _ensure_agent_task(self) -> None:
        from backend.core.bootstrap.agent_control_loop import run_agent_until_done
        from backend.core.schemas import AgentState

        if self._controller is None:
            return

        state = self._controller.get_agent_state()
        logger.info('TUI _ensure_agent_task: current state=%s', state)
        if state in {
            AgentState.LOADING,
            AgentState.AWAITING_USER_INPUT,
            AgentState.FINISHED,
            AgentState.ERROR,
            AgentState.REJECTED,
            AgentState.STOPPED,
        }:
            logger.info('TUI _ensure_agent_task: transitioning %s -> RUNNING', state)
            await self._controller.set_agent_state_to(AgentState.RUNNING)
        elif state == AgentState.RUNNING:
            logger.info('TUI _ensure_agent_task: already RUNNING')

        state_after = self._controller.get_agent_state()
        logger.info('TUI _ensure_agent_task: state after transition=%s', state_after)

        if self._agent_task is None or self._agent_task.done():
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
        else:
            logger.info('TUI _ensure_agent_task: agent task already running (task=%s)', self._agent_task)

    async def _dispatch_to_agent(self, text: str) -> None:
        from backend.core.enums import EventSource
        from backend.ledger.action import MessageAction

        if self._controller is None or self._event_stream is None:
            return

        await self._ensure_agent_task()

        action = MessageAction(content=text)
        self._event_stream.add_event(action, EventSource.USER)
        self._controller.step()

        end_states = {
            AgentState.AWAITING_USER_INPUT,
            AgentState.FINISHED,
            AgentState.ERROR,
            AgentState.STOPPED,
            AgentState.AWAITING_USER_CONFIRMATION,
        }
        while True:
            await asyncio.sleep(0.1)
            state = self._controller.get_agent_state()
            if state in end_states:
                break
            if self._agent_task and self._agent_task.done():
                break
            if self._renderer:
                self._renderer.drain_events()

    # ── confirmation ────────────────────────────────────────────────────────

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


class TUIRenderer:
    """Textual renderer — subscribes to event stream and updates TUI widgets."""

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
        self._pending_events: list[Any] = []

    def subscribe(self, event_stream: Any, sid: str) -> None:
        self._event_stream = event_stream
        event_stream.subscribe(self, self._on_event, sid)

    def drain_events(self) -> None:
        if not self._pending_events:
            return
        while self._pending_events:
            event = self._pending_events.pop(0)
            self._process_event(event)

    def _on_event(self, event: Any) -> None:
        self._pending_events.append(event)
        try:
            self._loop.call_soon_threadsafe(self._state_event.set)
        except RuntimeError:
            pass

    def wait_for_state_change(
        self, wait_timeout_sec: float = 0.1
    ) -> asyncio.Event:
        self._state_event.clear()
        return self._state_event

    def _process_event(self, event: Any) -> None:
        from backend.ledger.action import (
            CmdRunAction,
            MessageAction,
            NullAction,
            StreamingChunkAction,
        )
        from backend.ledger.observation import (
            AgentStateChangedObservation,
            CmdOutputObservation,
            NullObservation,
        )

        self._update_metrics(event)

        if isinstance(event, NullAction) or isinstance(event, NullObservation):
            return

        from backend.core.enums import EventSource

        source = getattr(event, 'source', None)

        if isinstance(event, MessageAction) and source == EventSource.AGENT:
            self._tui.add_agent_message(event.content or '')
        elif isinstance(event, CmdRunAction) and source == EventSource.AGENT:
            cmd = getattr(event, 'command', '') or ''
            self._tui.add_tool_start(cmd[:80])
        elif isinstance(event, CmdOutputObservation):
            output = (event.content or '').strip()
            if output:
                self._tui.add_tool_result(output[:500])
        elif isinstance(event, StreamingChunkAction):
            self._tui.add_agent_message(event.accumulated or '')
        elif isinstance(event, AgentStateChangedObservation):
            self._handle_state_change(event)

    def _update_metrics(self, event: Any) -> None:
        if hasattr(event, 'model') and event.model:
            self._hud.update_model(event.model)
        if hasattr(event, 'llm_metrics') and event.llm_metrics:
            self._hud.update_from_llm_metrics(event.llm_metrics)
        cost = getattr(event, 'cost_usd', None)
        if cost is not None and cost > 0:
            self._hud.update_cost(self._hud.state.cost_usd + cost)

    def _handle_state_change(self, obs: Any) -> None:
        from backend.core.enums import AgentState

        state = obs.agent_state
        try:
            state = AgentState(state)
        except (ValueError, TypeError):
            pass

        self._current_state = state
        self._hud.update_agent_state(str(state))
        self._state_event.set()
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._tui._render_header)
        else:
            self._tui._render_header()
