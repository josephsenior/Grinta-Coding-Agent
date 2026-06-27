from __future__ import annotations

import asyncio
from pathlib import Path

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

from backend.app.setup import (
    generate_sid,
)
from backend.cli.theme import (
    NAVY_BRAND,
    NAVY_DOMAIN_MCP,
    NAVY_DOMAIN_SKILLS,
    NAVY_FOCUS_ACCENT,
    NAVY_RUNNING,
)
from backend.cli.tui.constants import _tui_logger
from backend.cli.tui.dialogs import ConfirmWidget, GrintaHelpDialog
from backend.cli.tui.screen.lifecycle_bootstrap import ScreenLifecycleBootstrapMixin
from backend.cli.tui.screen.lifecycle_dispatch import ScreenLifecycleDispatchMixin
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
from backend.core.logging.logger import app_logger as logger
from backend.ledger import EventStream, EventStreamSubscriber
from backend.persistence import get_file_store
from backend.persistence.locations import get_local_data_root


class ScreenLifecycleMixin(ScreenLifecycleBootstrapMixin, ScreenLifecycleDispatchMixin):
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
                        accent_color=NAVY_BRAND,
                        section_icon='▣',
                        id='sidebar-tasks',
                    )
                    yield CollapsibleSection(
                        title='MCP Servers',
                        content='No servers configured',
                        collapsed=False,
                        accent_color=NAVY_DOMAIN_MCP,
                        section_icon='⬡',
                        action_label='Edit',
                        action_button_class='-mcp',
                        id='sidebar-mcp',
                    )
                    yield CollapsibleSection(
                        title='LSP Servers',
                        content='Scanning local PATH...',
                        collapsed=False,
                        accent_color=NAVY_FOCUS_ACCENT,
                        section_icon='◈',
                        id='sidebar-lsp',
                    )
                    yield CollapsibleSection(
                        title='Debug Adapters',
                        content='Scanning local PATH...',
                        collapsed=False,
                        accent_color=NAVY_RUNNING,
                        section_icon='◆',
                        id='sidebar-dap',
                    )
                    yield CollapsibleSection(
                        title='Skills',
                        content='No custom skills',
                        collapsed=False,
                        accent_color=NAVY_DOMAIN_SKILLS,
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
                self._hud.update_agent_state('error')
                self._render_hud_bar()
                try:
                    from backend.core.logging.logger import format_active_session_log_path

                    log_path = format_active_session_log_path()
                    detail = f'{type(exc).__name__}: {exc}'
                    if log_path:
                        detail = f'{detail}\nLog: {log_path}'
                    self.notify_error(f'Startup failed — {detail}', timeout=12.0)
                except Exception:
                    pass

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
            renderer_stream = getattr(self._renderer, '_event_stream', None)
            if renderer_stream is not None:
                renderer_stream.unsubscribe(
                    EventStreamSubscriber.CLI, renderer_stream.sid
                )
            if hasattr(self._renderer, '_event_stream'):
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

            asyncio.create_task(
                asyncio.to_thread(
                    controller._create_phase_boundary_checkpoint,
                    'init_to_active',
                ),
                name='grinta-init-checkpoint',
            )

            from backend.cli.settings.bootstrap_sync import (
                sync_controller_persisted_settings,
            )

            sync_controller_persisted_settings(
                controller,
                self._active_agent_name(),
                config=config,
                hud=self._hud,
            )
            self._render_hud_bar()

            from backend.utils.async_helpers.async_utils import set_main_event_loop

            set_main_event_loop(self._loop)
            _tui_logger.debug(f'_bootstrap: set_main_event_loop to {self._loop}')
            retry_service = getattr(controller, 'retry_service', None)
            ensure_worker = getattr(retry_service, 'ensure_worker_started', None)
            if callable(ensure_worker):
                ensure_worker()

            await self._bootstrap_setup_renderer(event_stream, controller)
            self._show_wsl_startup_warnings()
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

    def _show_wsl_startup_warnings(self) -> None:
        """One-shot WSL2 layout warnings after bootstrap (official supported tier)."""
        if getattr(self, '_wsl_startup_warnings_shown', False):
            return
        from backend.cli.doctor.checks import check_wsl_layout
        from backend.core.wsl import WslLayout, classify_wsl_layout, is_wsl_runtime

        if not is_wsl_runtime():
            return
        self._wsl_startup_warnings_shown = True
        layout = classify_wsl_layout(workspace=Path.cwd())
        if layout in {WslLayout.REPO_ON_DRVFS, WslLayout.BOTH_ON_DRVFS}:
            check = check_wsl_layout(workspace=Path.cwd())
            self.notify_error(check.detail, timeout=12.0)
            return
        if layout == WslLayout.SUPPORTED_SPLIT:
            self.notify_warning(
                'Project on Windows drive (/mnt/c) — file tools may be slower. '
                'Run /health to verify WSL layout.',
                timeout=8.0,
            )
