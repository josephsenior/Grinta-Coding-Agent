from __future__ import annotations

import asyncio
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

from backend.cli.tui._app_constants import _tui_logger
from backend.cli.tui._app_dialogs import ConfirmWidget, GrintaHelpDialog
from backend.cli.tui._app_small_widgets import (
    HUD,
    InfoSidebar,
    InputBar,
    PromptTextArea,
    RendererDrainRequested,
    Transcript,
)
from backend.cli.tui.widgets.collapsible import CollapsibleSection
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
from backend.core.logger import app_logger as logger
from backend.ledger import EventStream, EventStreamSubscriber
from backend.ledger.action import (
    MessageAction,
)
from backend.ledger.observation import (
    StatusObservation,
)
from backend.persistence import get_file_store


class _AppScreenLifecycleMixin:
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

    def show_help(self) -> None:
        self.app.push_screen(GrintaHelpDialog())

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
