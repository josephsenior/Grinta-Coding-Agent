"""TUI session bootstrap helpers (extracted from lifecycle)."""

from __future__ import annotations

import asyncio
from typing import Any

from backend.app.main import (
    create_agent,
    create_registry_and_conversation_stats,
)
from backend.app.setup import (
    create_controller,
    create_memory,
    create_runtime,
)
from backend.cli.tui.constants import _tui_logger
from backend.core.enums import EventSource
from backend.core.logging.logger import app_logger as logger
from backend.ledger.observation import StatusObservation


class ScreenLifecycleBootstrapMixin:
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
        finally:
            # Always start the live-reload plumbing, even if warmup
            # raised, so the bus is wired and the file watcher runs.
            self._install_mcp_reload_bridge(agent, runtime, memory)
            await self._start_settings_watcher()

    def _install_mcp_reload_bridge(self, agent: Any, runtime: Any, memory: Any) -> None:
        """Subscribe the running runtime to MCP bus events.

        Idempotent: calling twice replaces the previous adapter
        (the old one is closed, so it stops receiving callbacks).
        """
        from backend.cli.tui.services.mcp_reload_adapter import MCPReloadAdapter

        existing = getattr(self, '_mcp_reload_adapter', None)
        if existing is not None:
            try:
                existing.close()
            except Exception:
                logger.debug('MCP reload adapter close failed', exc_info=True)

        event_stream = getattr(self, '_event_stream', None)
        es_add = getattr(event_stream, 'add_event', None) if event_stream else None

        def _emit_status(status_type: str, extras: dict[str, Any]) -> None:
            if not callable(es_add):
                return
            try:
                es_add(
                    StatusObservation(
                        content='',
                        status_type=status_type,
                        extras=extras,
                    ),
                    EventSource.ENVIRONMENT,
                )
            except Exception:
                logger.debug('MCP reload status emit failed', exc_info=True)

        adapter = MCPReloadAdapter(
            runtime=runtime,
            agent=agent,
            memory=memory,
            emit_status=_emit_status if callable(es_add) else None,
        )
        try:
            adapter.install()
        except Exception:
            logger.debug('MCP reload adapter install failed', exc_info=True)
            return
        self._mcp_reload_adapter = adapter

    async def _start_settings_watcher(self) -> None:
        """Start the polling-based ``settings.json`` watcher.

        Skips startup when the watcher is already running or when the
        settings file cannot be resolved.
        """
        watcher = getattr(self, '_settings_watcher', None)
        if watcher is not None:
            return
        try:
            from backend.cli.settings.storage import _settings_path
            from backend.cli.tui.services.settings_watcher import (
                SettingsFileWatcher,
            )
        except Exception:
            logger.debug('Settings watcher imports failed', exc_info=True)
            return
        try:
            path = _settings_path()
        except Exception:
            return
        watcher = SettingsFileWatcher(path)
        try:
            watcher.install()
            await watcher.start()
        except Exception:
            logger.debug('Settings watcher start failed', exc_info=True)
            return
        self._settings_watcher = watcher

    async def _stop_settings_watcher(self) -> None:
        watcher = getattr(self, '_settings_watcher', None)
        if watcher is None:
            return
        try:
            await watcher.stop()
        except Exception:
            logger.debug('Settings watcher stop failed', exc_info=True)
        self._settings_watcher = None

        adapter = getattr(self, '_mcp_reload_adapter', None)
        if adapter is not None:
            try:
                adapter.close()
            except Exception:
                logger.debug('MCP reload adapter close failed', exc_info=True)
            self._mcp_reload_adapter = None

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
        if renderer is not None and (
            renderer._sidebar_lsp_enabled()
            or renderer._sidebar_debugger_enabled()
        ):
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
        controller = create_controller(
            agent=agent,
            runtime=runtime,
            config=config,
            conversation_stats=conversation_stats,
            headless_mode=True,
            defer_init_checkpoint=True,
        )[0]
        return controller
