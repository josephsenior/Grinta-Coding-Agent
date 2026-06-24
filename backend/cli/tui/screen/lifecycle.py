from __future__ import annotations

import asyncio
import time as _time
from typing import Any

from textual.app import ComposeResult
from textual.containers import (
    Horizontal,
    Vertical,
)
from textual.widgets import (
    Label,
    ListView,
    Static,
    TextArea,
)

from backend.app.agent_control_loop import run_agent_until_done
from backend.app.main import (
    create_agent,
    create_registry_and_conversation_stats,
)
from backend.app.setup import (
    create_controller,
    create_memory,
    create_runtime,
    generate_sid,
)
from backend.cli.tui.constants import _tui_logger
from backend.cli.tui.dialogs import ConfirmWidget, GrintaHelpDialog
from backend.cli.tui.widgets.collapsible import CollapsibleSection
from backend.cli.tui.widgets.small import (
    HUD,
    InfoSidebar,
    InputBar,
    LoadEarlierRequested,
    PromptTextArea,
    RendererDrainRequested,
    Transcript,
)
from backend.core.constants import DEFAULT_TUI_DISPATCH_TIMEOUT_SECONDS
from backend.core.enums import AgentState, EventSource
from backend.core.logging.logger import app_logger as logger
from backend.ledger import EventStream, EventStreamSubscriber
from backend.ledger.action import (
    MessageAction,
)
from backend.ledger.observation import (
    StatusObservation,
)
from backend.persistence import get_file_store
from backend.persistence.locations import get_local_data_root


class ScreenLifecycleMixin:
    """Lifecycle-related methods of GrintaScreen."""

    def compose(self) -> ComposeResult:
        with Horizontal(id='app-layout'):
            with Vertical(id='left-column'):
                yield Transcript(id='main-display')
                yield ConfirmWidget(id='confirm-widget')
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
                        section_icon='▣',
                        id='sidebar-tasks',
                    )
                    yield CollapsibleSection(
                        title='MCP Servers',
                        content='No servers configured',
                        collapsed=False,
                        accent_color='#eacb8a',
                        section_icon='⬡',
                        action_label='Edit',
                        action_button_class='-mcp',
                        id='sidebar-mcp',
                    )
                    yield CollapsibleSection(
                        title='LSP Servers',
                        content='Scanning local PATH...',
                        collapsed=False,
                        accent_color='#5eead4',
                        section_icon='◈',
                        id='sidebar-lsp',
                    )
                    yield CollapsibleSection(
                        title='Debug Adapters',
                        content='Scanning local PATH...',
                        collapsed=False,
                        accent_color='#f6a657',
                        section_icon='◆',
                        id='sidebar-dap',
                    )
                    yield CollapsibleSection(
                        title='Skills',
                        content='No custom skills',
                        collapsed=False,
                        accent_color='#c792ea',
                        section_icon='✦',
                        action_label='Edit',
                        action_button_class='-skill',
                        id='sidebar-skills',
                    )

    def on_mount(self) -> None:
        _tui_logger.debug('on_mount: GrintaScreen mounted')
        self._is_unmounted = False

        self._render_hud_bar()
        self.call_after_refresh(self._mark_hud_controls_ready)
        self._update_input_identity()
        self._hud_tick = self.set_interval(1.0, self._refresh_runtime_feedback)
        self._hud_pulse_tick = self.set_interval(0.5, self._tick_hud_running_pulse)
        self._scanline_refresh_tick = self.set_interval(
            0.25, self._refresh_scanline_cards
        )
        ta = self.query_one('#input', TextArea)
        ta.text = ''
        ta.focus()
        self._get_display().scroll_home(animate=False)
        _tui_logger.debug('on_mount: done')
        self._start_background_bootstrap()
        self.set_timer(0.5, self._show_welcome)

    def _mark_hud_controls_ready(self) -> None:
        self._hud_controls_ready = True

    async def on_renderer_drain_requested(
        self, _message: RendererDrainRequested
    ) -> None:
        if self._renderer is not None:
            await self._renderer.drain_events_async()
        if not self._welcome_visible:
            return
        if self._transcript_has_real_content():
            self._hide_welcome()

    async def on_load_earlier_requested(self, _message: LoadEarlierRequested) -> None:
        if self._renderer is None:
            return
        try:
            display = self._get_display()
            button = display._load_earlier_button
            if button is not None:
                button.update('Loading...')
        except Exception:
            pass
        loaded = await self._renderer.load_earlier_messages()
        try:
            display = self._get_display()
            if loaded == 0 or self._renderer._min_rendered_event_id <= 0:
                if display._load_earlier_button is not None:
                    display._load_earlier_button.remove()
                    display.set_load_earlier_button(None)
            else:
                display._load_earlier_button.update('Load earlier messages')
        except Exception:
            pass

    def _start_background_bootstrap(self) -> None:
        async def _bg():
            try:
                await self._bootstrap()
            except asyncio.CancelledError:
                _tui_logger.debug('background bootstrap cancelled')
            except Exception as exc:
                _tui_logger.debug(f'background bootstrap failed: {exc}')
                logger.exception('TUI background bootstrap failed')
                if self._controller is not None:
                    self._hud.update_agent_state('error')
                else:
                    self._hud.update_agent_state('error')
                self._render_hud_bar()

        self._bootstrap_task = asyncio.create_task(_bg(), name='grinta-tui-bootstrap')

    def on_unmount(self) -> None:
        _tui_logger.debug('on_unmount: GrintaScreen unmounting')
        self._is_unmounted = True
        if self._hud_tick is not None:
            self._hud_tick.stop()
            self._hud_tick = None
        if getattr(self, '_hud_pulse_tick', None) is not None:
            self._hud_pulse_tick.stop()
            self._hud_pulse_tick = None
        if self._bootstrap_task and not self._bootstrap_task.done():
            self._bootstrap_task.cancel()
        if self._environment_probe_task and not self._environment_probe_task.done():
            self._environment_probe_task.cancel()
            self._environment_probe_task = None
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
        try:
            from backend.core.logging.logger import finalize_session_logging_audit

            finalize_session_logging_audit()
        except Exception as exc:
            _tui_logger.debug('on_unmount: session audit generation failed: %s', exc)
        _tui_logger.debug('on_unmount: done')

    def show_help(self) -> None:
        def _on_help_dismiss(command: str | None) -> None:
            if command:
                self.apply_slash_command_from_palette(command)

        self.app.push_screen(GrintaHelpDialog(), _on_help_dismiss)

    async def _bootstrap(self, session_id: str | None = None) -> None:
        _tui_logger.debug('_bootstrap: start')
        logger.info('TUI _bootstrap: starting')

        _bootstrapping = asyncio.Event()
        self._bootstrapping = _bootstrapping
        self._reset_environment_probe()

        config = self._config

        event_stream = None
        try:
            file_store = get_file_store(
                file_store_type=config.file_store,
                local_data_root=get_local_data_root(config),
            )
            sid = session_id.strip() if session_id else generate_sid(config)
            try:
                from backend.core.logging.logger import (
                    bind_session_logging,
                    configure_file_logging,
                )

                configure_file_logging()
                bind_session_logging(sid)
            except Exception:
                logger.exception('TUI bootstrap: failed to bind session logging')
            try:
                from backend.context.memory.session_context import bind_session_context

                bind_session_context(session_id=sid)
            except Exception:
                logger.debug(
                    'Failed to bind session context at bootstrap', exc_info=True
                )
            event_stream = EventStream(sid=sid, file_store=file_store, user_id='tui')
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
            if self._bootstrap_check_unmounted(event_stream):
                return

            _tui_logger.debug(
                f'_bootstrap: runtime created, type={type(runtime).__name__}'
            )

            await self._bootstrap_connect_runtime(runtime)

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
            if self._bootstrap_check_unmounted(event_stream):
                return
            self._runtime_stub = runtime
            self._memory_stub = memory
            self._controller = controller

            from backend.cli.settings import sync_persisted_autonomy_to_controller

            autonomy_level = sync_persisted_autonomy_to_controller(
                controller,
                self._active_agent_name(),
                config=config,
            )
            self._hud.update_autonomy(autonomy_level)
            self._render_hud_bar()

            from backend.utils.async_helpers.async_utils import set_main_event_loop

            set_main_event_loop(self._loop)
            _tui_logger.debug(f'_bootstrap: set_main_event_loop to {self._loop}')
            retry_service = getattr(controller, 'retry_service', None)
            ensure_worker = getattr(retry_service, 'ensure_worker_started', None)
            if callable(ensure_worker):
                ensure_worker()

            await self._bootstrap_setup_renderer(event_stream, controller)
            self._start_environment_probe(agent, runtime, memory)
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
            ready = self._environment_ready
            if (
                ready is not None
                and not ready.is_set()
                and self._environment_probe_task is None
            ):
                ready.set()

    def _bootstrap_check_unmounted(self, event_stream: Any) -> bool:
        if not self._is_unmounted:
            return False
        _tui_logger.debug('_bootstrap: screen unmounted, aborting')
        if event_stream is not None:
            close_fn = getattr(event_stream, 'close', None)
            if callable(close_fn):
                close_fn()
        self._event_stream = None
        return True

    async def _bootstrap_connect_runtime(self, runtime: Any) -> None:
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

    async def _bootstrap_mcp_warmup(
        self, agent: Any, runtime: Any, memory: Any
    ) -> None:
        try:
            from backend.app.main import _setup_mcp_tools

            await _setup_mcp_tools(agent, runtime, memory)
            from backend.integrations.mcp.native_backends import (
                count_user_visible_mcp_servers,
            )

            self._hud.update_mcp_servers(count_user_visible_mcp_servers(self._config))
        except Exception:
            _tui_logger.debug('_bootstrap: MCP warmup failed (non-fatal)')
            self._hud.update_mcp_servers(0)

    def _reset_environment_probe(self) -> None:
        """Clear env-probe state so the next session can warm tools in background."""
        if self._environment_probe_task and not self._environment_probe_task.done():
            self._environment_probe_task.cancel()
        self._environment_probe_task = None
        self._environment_ready = asyncio.Event()

    def _start_environment_probe(self, agent: Any, runtime: Any, memory: Any) -> None:
        """Warm MCP tools and probe LSP/DAP off the critical bootstrap path."""

        async def _run() -> None:
            try:
                await self._probe_environment(agent, runtime, memory)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception('TUI environment probe failed')
            finally:
                ready = self._environment_ready
                if ready is not None:
                    ready.set()
                renderer = self._renderer
                if renderer is not None:
                    try:
                        renderer._refresh_display()
                    except Exception:
                        pass

        self._environment_probe_task = asyncio.create_task(
            _run(),
            name='grinta-tui-env-probe',
        )

    async def _probe_environment(self, agent: Any, runtime: Any, memory: Any) -> None:
        """Connect MCP servers and detect local language/debug runtimes."""
        probes: list[Any] = [self._bootstrap_mcp_warmup(agent, runtime, memory)]
        renderer = self._renderer
        if renderer is not None:
            probes.append(renderer._detect_lsp_servers_async())
        await asyncio.gather(*probes)

    async def _ensure_environment_ready(self) -> None:
        """Wait until MCP + runtime detection finished before the first agent turn."""
        ready = self._environment_ready
        if ready is None or ready.is_set():
            return
        prev_phase = self._phase_label
        self._phase_label = 'Preparing environment'
        self._render_hud_bar()
        try:
            await ready.wait()
        finally:
            if self._phase_label == 'Preparing environment':
                self._phase_label = prev_phase or 'Ready'
            self._render_hud_bar()

    async def _bootstrap_setup_renderer(
        self, event_stream: Any, controller: Any
    ) -> None:
        if self._renderer is None:
            import sys

            sys.stdin.isatty()
            from backend.cli.tui.app import TUIRenderer

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
        self._hud.update_agent_state('awaiting_user_input')
        self._render_hud_bar()

        asyncio.create_task(
            self._bootstrap_finalize_renderer(),
            name='grinta-tui-bootstrap-renderer',
        )

    async def _bootstrap_finalize_renderer(self) -> None:
        """Hydrate transcript and drain backlog without blocking launch readiness."""
        renderer = self._renderer
        if renderer is None:
            return
        try:
            await renderer.hydrate_recent_transcript()
            await renderer.drain_events_async()
        except Exception:
            _tui_logger.debug(
                '_bootstrap_finalize_renderer failed',
                exc_info=True,
            )

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

    async def _poll_wait(self):
        # Keep the poll loop lightweight; renderer drains are event-driven.
        # 250ms sleep balances responsiveness with reduced CPU wakeups (~4/sec).
        await asyncio.sleep(0.25)

    def _get_current_event_count(self) -> int:
        try:
            return self._event_stream.get_latest_event_id()
        except Exception:
            return 0

    def _update_progress_tracking(
        self,
        state,
        current_event_count: int,
        last_event_count: int,
        last_state,
        stale_poll_count: int,
        last_progress_at: float,
    ):
        progress_made = False
        if current_event_count != last_event_count:
            progress_made = True
            stale_poll_count = 0
            last_event_count = current_event_count
        else:
            stale_poll_count += 1

        if state != last_state:
            progress_made = True
            last_state = state

        if progress_made:
            last_progress_at = _time.monotonic()

        return last_event_count, last_state, stale_poll_count, last_progress_at

    def _maybe_log_stale_polls(self, stale_poll_count: int, state):
        STALE_POLL_THRESHOLD = 120
        if (
            stale_poll_count > 0
            and stale_poll_count % STALE_POLL_THRESHOLD == 0
            and state == AgentState.RUNNING
        ):
            _tui_logger.debug(
                '_dispatch_to_agent: %d consecutive polls with no new events '
                'in RUNNING state (LLM may be thinking silently; '
                'no-step-progress watchdog will recover true stalls)',
                stale_poll_count,
            )

    async def _check_stall_timeout(
        self,
        state,
        last_progress_at: float,
        started_at: float,
        loop_count: int,
    ):
        elapsed_since_progress = _time.monotonic() - last_progress_at
        if (
            DEFAULT_TUI_DISPATCH_TIMEOUT_SECONDS > 0
            and elapsed_since_progress > DEFAULT_TUI_DISPATCH_TIMEOUT_SECONDS
        ):
            total_elapsed = _time.monotonic() - started_at
            _tui_logger.error(
                '_dispatch_to_agent: TIMEOUT after %.0fs since last progress '
                '(%.0fs total, poll #%d, state=%s) — forcing ERROR to break stall',
                elapsed_since_progress,
                total_elapsed,
                loop_count,
                state,
            )
            logger.error(
                '[TUI] _dispatch_to_agent: STALL TIMEOUT after %.0fs since last progress '
                '(%.0fs total, poll #%d, state=%s). '
                'This usually indicates the _step_pending race condition. '
                'Forcing ERROR state.',
                elapsed_since_progress,
                total_elapsed,
                loop_count,
                state,
                extra={'msg_type': 'TUI_DISPATCH_STALL_TIMEOUT'},
            )
            try:
                await self._controller.set_agent_state_to(AgentState.ERROR)
            except Exception:
                pass
            return AgentState.ERROR, True
        return state, False

    def _maybe_log_periodic_status(self, loop_count: int, state):
        if loop_count == 1 or loop_count % 20 == 0:
            _tui_logger.debug(f'_dispatch_to_agent: poll #{loop_count}, state={state}')
            logger.info(
                '[TUI] _dispatch_to_agent: poll #%d, state=%s',
                loop_count,
                state,
            )

    def _check_completion(self, state, end_states: set[AgentState]) -> bool:
        if state in end_states:
            _tui_logger.debug(f'_dispatch_to_agent: reached end state {state}')
            logger.info('[TUI] _dispatch_to_agent: reached end state %s', state)
            return True
        if self._agent_task and self._agent_task.done():
            _tui_logger.debug(f'_dispatch_to_agent: agent task done, state={state}')
            logger.info('[TUI] _dispatch_to_agent: agent task done, state=%s', state)
            return True
        return False

    async def _poll_for_agent_completion(
        self,
        end_states: set[AgentState],
        started_at: float,
    ) -> AgentState:
        loop_count = 0
        last_progress_at = started_at
        last_event_count = 0
        last_state = None
        stale_poll_count = 0

        while True:
            try:
                await self._poll_wait()
                loop_count += 1
                state = self._controller.get_agent_state()
                current_event_count = self._get_current_event_count()

                last_event_count, last_state, stale_poll_count, last_progress_at = (
                    self._update_progress_tracking(
                        state,
                        current_event_count,
                        last_event_count,
                        last_state,
                        stale_poll_count,
                        last_progress_at,
                    )
                )

                self._maybe_log_stale_polls(stale_poll_count, state)

                state, timed_out = await self._check_stall_timeout(
                    state, last_progress_at, started_at, loop_count
                )
                if timed_out:
                    break

                self._maybe_log_periodic_status(loop_count, state)

                if self._check_completion(state, end_states):
                    break
            except Exception as exc:
                _tui_logger.debug(
                    f'_dispatch_to_agent: poll loop EXCEPTION {type(exc).__name__}: {exc}'
                )
                raise

        return state

    async def _dispatch_to_agent(
        self, text: str, *, image_urls: list[str] | None = None
    ) -> None:
        _tui_logger.debug('_dispatch_to_agent: ENTER')
        if self._controller is None or self._event_stream is None:
            _tui_logger.debug(
                '_dispatch_to_agent: missing controller or event_stream, returning'
            )
            return

        await self._ensure_environment_ready()

        action = MessageAction(
            content=text,
            image_urls=image_urls or None,
        )
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

        started_at = _time.monotonic()
        while True:
            state = await self._poll_for_agent_completion(end_states, started_at)
            if state == AgentState.AWAITING_USER_CONFIRMATION:
                await self._handle_confirmation_dialog()
                continue
            break

        _tui_logger.debug('_dispatch_to_agent: poll loop exited')
        if self._renderer:
            await self._renderer.drain_events_async()
