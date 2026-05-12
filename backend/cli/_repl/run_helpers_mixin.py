"""Run-helpers mixin for :class:`backend.cli.repl.Repl`.

Contains the async bootstrap pipeline, prompt-session construction,
user-turn dispatch, and finalization helpers — extracted from
:mod:`backend.cli.repl` to keep the main module under the project's per-file
LOC budget.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any, cast

from backend.cli._typing import RunHelpersHost
from backend.cli.event_renderer import CLIEventRenderer
from backend.cli.theme import CLR_STATUS_ERR, STYLE_DIM
from backend.core.config import AppConfig
from backend.core.enums import AgentState, EventSource
from backend.ledger.action import MessageAction

logger = logging.getLogger(__name__)


def _create_prompt_session_from_host(host: RunHelpersHost) -> Any:
    return host._create_prompt_session()


def _handle_parsed_command_from_host(
    host: RunHelpersHost,
    parsed_command: Any,
) -> bool:
    return bool(host._handle_parsed_command(parsed_command))


async def _resume_session_from_host(
    host: RunHelpersHost,
    target: str,
    config: Any,
    create_controller: Any,
    create_status_callback: Any,
    run_agent_until_done: Any,
    end_states: list[AgentState],
) -> Any:
    return await host._resume_session(
        target,
        config,
        create_controller,
        create_status_callback,
        run_agent_until_done,
        end_states,
    )


class RunHelpersMixin:
    """Mixin providing the async run() pipeline helpers."""

    # Attributes & helpers provided by the concrete ``backend.cli.repl.Repl``
    # host class. Declared as ``Any`` so the mixin type-checks in isolation
    # without constraining the concrete attribute types in :class:`Repl`.
    if TYPE_CHECKING:
        _config: Any
        _memory: Any
        _runtime: Any
        _agent: Any
        _llm_registry: Any
        _conversation_stats: Any
        _pt_session: Any
        _renderer: Any
        _console: Any
        _hud: Any
        _reasoning: Any
        _pending_resume: str | None
        _next_action: Any
        _last_user_message: str | None
        _prompt_ctrl_c_hint_shown: bool
        _running: bool

        def _create_prompt_session(self) -> Any: ...
        def _set_footer_system_line(self, text: str, *, kind: str = ...) -> None: ...
        async def _read_non_interactive_input(self) -> Any: ...
        def _handle_parsed_command(self, *args: Any, **kwargs: Any) -> Any: ...
        def _cancel_agent(self, *args: Any, **kwargs: Any) -> Any: ...
        def _resume_session(self, *args: Any, **kwargs: Any) -> Any: ...
        def _wait_for_agent_idle(self, *args: Any, **kwargs: Any) -> Any: ...
        def _sync_terminal_after_agent_turn(self, *args: Any, **kwargs: Any) -> Any: ...
        def _invalidate_pt(self) -> None: ...
        def _warn(self, msg: str) -> None: ...

    def _build_prompt_session(self) -> Any | None:
        import sys

        from backend.cli.repl import (
            _attach_prompt_buffer_csi_sanitizer,
            _supports_prompt_session,
        )

        session: Any | None = None
        if _supports_prompt_session(sys.stdin, sys.stdout):
            host = cast(RunHelpersHost, self)
            session = _create_prompt_session_from_host(host)
            _attach_prompt_buffer_csi_sanitizer(session)
        self._pt_session = session
        return session

    def _build_renderer(self, session: Any | None, loop: Any) -> Any:
        config = self._config
        get_pt_session = (lambda: session) if session is not None else None
        self._renderer = CLIEventRenderer(
            self._console,
            self._hud,
            self._reasoning,
            loop=loop,
            max_budget=config.max_budget_per_task,
            get_prompt_session=get_pt_session,
            cli_tool_icons=config.cli_tool_icons,
        )
        renderer = self._renderer
        return renderer

    def _invalidate_prompt_session(self, session: Any | None) -> None:
        if session is not None:
            with contextlib.suppress(Exception):
                session.app.invalidate()

    def _handle_bootstrap_failure(
        self,
        exc: BaseException,
        renderer: Any,
        session: Any | None,
        engine_init_exc: list[BaseException | None],
    ) -> None:
        engine_init_exc[0] = exc
        self._set_footer_system_line('')
        exc_name = type(exc).__name__
        msg: str
        if 'AuthenticationError' in exc_name or 'api_key' in str(exc).lower():
            msg = (
                'No API key or model configured.\n'
                'Run `grinta init` to configure a provider, '
                'or edit `settings.json` directly.\n'
                f'{exc}'
            )
            renderer.add_system_message(msg, title='error')
        else:
            msg = f'Initialization failed: {exc}'
            renderer.add_system_message(msg, title='error')
        # Print directly to stderr so the user sees the error even as
        # the REPL shuts down — renderer messages may not flush in time.
        import sys

        print(f'\n[Grinta] {msg}\n', file=sys.stderr)
        # Do NOT set self._running = False here.  Setting it kills the REPL
        # loop silently — the user never sees the error in the prompt area.
        # Instead leave _running True so the REPL stays alive and the user
        # can read the error message and fix config or type /exit.

    async def _engine_bootstrap(
        self,
        session: Any | None,
        renderer: Any,
        chat_ready_done: asyncio.Event,
        engine_init_done: asyncio.Event,
        engine_init_exc: list[BaseException | None],
    ) -> None:
        """Prepare chat first, then finish optional tool warmup in the background."""
        try:
            self._hud.update_agent_state('Starting')
            self._bootstrap_status('Initializing session…', session, renderer)

            init_ok = await self._bootstrap_init_session(
                renderer,
                session,
                engine_init_exc,
            )
            if not init_ok:
                return

            self._bootstrap_status('Setting up runtime…', session, renderer)

            runtime_ok = await self._bootstrap_setup_runtime(
                renderer,
                session,
                chat_ready_done,
                engine_init_exc,
            )
            if not runtime_ok:
                return
            engine_init_done.set()

            agent = self._agent
            if agent is None or not agent.config.enable_mcp:
                self._bootstrap_status('Ready.', session, renderer, kind='system')
                return

            # MCP warmup — show per-server connection progress
            await self._bootstrap_mcp_warmup(agent, session, renderer)
        finally:
            chat_ready_done.set()
            engine_init_done.set()

    async def _bootstrap_mcp_warmup(
        self,
        agent: Any,
        session: Any | None,
        renderer: Any,
    ) -> None:
        """Warm up MCP tools with per-server progress reporting."""
        import os

        from backend.core.bootstrap.main import _setup_mcp_tools

        verbose = os.environ.get('GRINTA_VERBOSE') == '1'

        # Count configured MCP servers for progress reporting
        server_count = 0
        server_names: list[str] = []
        try:
            mcp_config = getattr(agent.config, 'mcp', None) or getattr(
                agent.config, 'mcp_config', None
            )
            if mcp_config is not None:
                servers = getattr(mcp_config, 'servers', []) or []
                server_count = len(servers)
                server_names = [getattr(s, 'name', '?') for s in servers]
        except Exception:
            pass

        if server_count > 0:
            msg = f'MCP: connecting to {server_count} server(s)…'
            if verbose and server_names:
                msg += f' ({", ".join(server_names[:5])})'
        else:
            msg = 'Loading MCP tools…'
        self._bootstrap_status(msg, session, renderer)

        try:
            await _setup_mcp_tools(agent, self._runtime, self._memory)
        except Exception as exc:
            logger.warning('MCP warmup failed after chat became ready', exc_info=True)
            self._hud.update_mcp_servers(0)
            self._handle_mcp_partial_state(agent)
            err_msg = f'MCP warmup failed: {exc}'
            self._bootstrap_status(err_msg, session, renderer, kind='warning')
            return

        self._update_mcp_count_from_agent(agent)
        from backend.integrations.mcp.mcp_bootstrap_status import (
            get_mcp_bootstrap_status,
        )

        status = get_mcp_bootstrap_status()
        client_count = int(status.get('connected_client_count', 0))
        errors = status.get('conversion_errors', []) or []

        if client_count > 0:
            if server_count > 0:
                detail = f'{client_count}/{server_count} MCP server(s) connected.'
            else:
                detail = f'{client_count} MCP server(s) connected.'
            if verbose and errors:
                detail += f' {len(errors)} conversion error(s).'
        else:
            detail = 'MCP tools loaded.'
            if verbose and errors:
                detail += f' ({len(errors)} conversion errors)'
        self._bootstrap_status(detail, session, renderer)

    def _bootstrap_status(
        self,
        text: str,
        session: Any | None,
        renderer: Any,
        *,
        kind: str = 'system',
    ) -> None:
        """Update bootstrap status in footer (PT) or renderer (non-PT)."""
        if session is not None:
            self._set_footer_system_line(text, kind=kind)
        else:
            renderer.add_system_message(text, title=kind)

    def _handle_mcp_partial_state(self, agent: Any) -> None:
        """Handle partial MCP state after warmup failure.

        When MCP warmup fails after tools have been registered but clients
        weren't fully initialized, we need to clear the partial state to
        prevent the agent from using incomplete MCP tools.
        """
        try:
            mcp_config = getattr(agent.config, 'mcp', None) or getattr(
                agent.config, 'mcp_config', None
            )
            if mcp_config is not None:
                mcp_config.servers = []
            agent.mcp_capability_status = {
                'connected_client_count': 0,
                'partial_initialization': True,
                'error': 'warmup failed before full initialization',
            }
            logger.debug('Cleared partial MCP state after warmup failure')
        except Exception as exc:
            logger.warning('Failed to clear partial MCP state: %s', exc)

    async def _bootstrap_init_session(
        self,
        renderer: Any,
        session: Any | None,
        engine_init_exc: list[BaseException | None],
    ) -> bool:
        from backend.core.bootstrap.main import _initialize_session_components

        try:
            bootstrap_state = await asyncio.to_thread(
                _initialize_session_components,
                self._config,
                None,
            )
        except Exception as exc:
            self._handle_bootstrap_failure(exc, renderer, session, engine_init_exc)
            return False
        session_id = bootstrap_state[0]
        llm_registry = bootstrap_state[1]
        conversation_stats = bootstrap_state[2]
        config_ = bootstrap_state[3]
        agent = bootstrap_state[4]

        self._agent = agent
        self._llm_registry = llm_registry
        self._conversation_stats = conversation_stats
        self._config = config_
        self._hud.update_workspace(getattr(config_, 'project_root', None))
        self._bootstrap_session_id = session_id
        return True

    async def _bootstrap_setup_runtime(
        self,
        renderer: Any,
        session: Any | None,
        chat_ready_done: asyncio.Event,
        engine_init_exc: list[BaseException | None],
    ) -> bool:
        from backend.core.bootstrap.main import (
            _setup_memory,
            _setup_runtime_for_controller,
        )

        config_ = self._config
        agent = self._agent
        llm_registry = self._llm_registry
        session_id: str | None = getattr(self, '_bootstrap_session_id', None)
        try:
            runtime_state = await asyncio.to_thread(
                _setup_runtime_for_controller,
                config_,
                llm_registry,
                session_id,  # type: ignore[arg-type]
                True,
                agent,
                None,  # type: ignore[arg-type]
                inline_event_delivery=True,
            )
            runtime = runtime_state[0]
            repo_directory = runtime_state[1]
            acquire_result = runtime_state[2]

            event_stream = runtime.event_stream
            if event_stream is None:
                raise RuntimeError('Runtime did not produce an event stream.')

            self._event_stream = event_stream
            self._runtime = runtime
            self._acquire_result = acquire_result

            memory = await _setup_memory(
                config_,
                runtime,
                session_id,  # type: ignore[arg-type]
                repo_directory,
                None,
                None,
                agent,  # type: ignore[arg-type]
            )
            self._memory = memory

            renderer.subscribe(event_stream, event_stream.sid)
            self._announce_chat_ready(agent, session, renderer)
            self._hud.update_ledger('Healthy')
            self._invalidate_prompt_session(session)
            chat_ready_done.set()
            return True
        except Exception as exc:
            self._handle_bootstrap_failure(exc, renderer, session, engine_init_exc)
            return False

    def _announce_chat_ready(
        self,
        agent: Any,
        session: Any | None,
        renderer: Any,
    ) -> None:
        tip = '/help · /settings · /sessions'
        self._hud.update_agent_state('Ready')
        if agent.config.enable_mcp:
            msg = f'Chat ready. MCP tools warming in background. {tip}'
        else:
            self._hud.update_mcp_servers(0)
            msg = f'Ready. Describe a task or type {tip}.'
        if session is not None:
            self._set_footer_system_line(msg)
        else:
            renderer.add_system_message(msg, title='system')

    def _update_mcp_count_from_agent(self, agent: Any) -> None:
        mcp_status = getattr(agent, 'mcp_capability_status', None) or {}
        try:
            mcp_n = int(mcp_status.get('connected_client_count') or 0)
        except (TypeError, ValueError):
            mcp_n = 0
        self._hud.update_mcp_servers(mcp_n)

    async def _read_repl_input(self, session: Any | None) -> str | None:
        """Read one line of input. Returns None to break the loop, '' to continue."""
        _MAX_CONSECUTIVE_FAILURES = 10
        try:
            if session is None:
                user_input = await self._read_non_interactive_input()
                if user_input == '':
                    raise EOFError
            else:
                user_input = await session.prompt_async()
        except KeyboardInterrupt:
            if not self._prompt_ctrl_c_hint_shown:
                self._console.print(
                    f'[{STYLE_DIM}]At the prompt, type /quit to exit. During a run, '
                    'Ctrl+C asks the agent to stop; some terminals may need '
                    'a second press.[/]'
                )
                self._prompt_ctrl_c_hint_shown = True
            self._consecutive_input_failures = 0
            return ''
        except EOFError:
            self._consecutive_input_failures = 0
            self._console.print(f'[{STYLE_DIM}]Input closed. Exiting.[/]')
            return None
        except asyncio.CancelledError:
            # CancelledError inherits from BaseException, not Exception,
            # but we handle it explicitly to prevent silent termination.
            logger.debug('REPL: prompt input cancelled')
            return ''
        except Exception as e:
            self._consecutive_input_failures += 1
            logger.exception('Prompt input failed')
            try:
                self._console.print(
                    f'[{CLR_STATUS_ERR}]Prompt input failed ({self._consecutive_input_failures}/{_MAX_CONSECUTIVE_FAILURES}):[/] {e}',
                )
            except Exception:
                pass
            if self._consecutive_input_failures >= _MAX_CONSECUTIVE_FAILURES:
                logger.error(
                    'Too many consecutive prompt failures (%d), forcing exit',
                    self._consecutive_input_failures,
                )
                try:
                    self._console.print(
                        f'[{CLR_STATUS_ERR}]Too many consecutive input failures. Exiting.[/]'
                    )
                except Exception:
                    pass
                return None
            return ''

        self._consecutive_input_failures = 0
        if not self._running:
            logger.debug('REPL: _read_repl_input: _running is False, returning None')
            return None
        return user_input

    def _discard_terminal_noise(self, text: str) -> bool:
        from backend.cli.repl import _looks_like_terminal_selection_noise

        if not _looks_like_terminal_selection_noise(text):
            return False
        if self._renderer is not None:
            self._renderer.add_system_message(
                'Ignored terminal control sequence noise from selection/copy input.',
                title='warning',
            )
        return True

    async def _process_slash_command(
        self,
        text: str,
        agent_task: asyncio.Task[Any] | None,
        controller: Any,
        engine_init_done: asyncio.Event,
        engine_init_exc: list[BaseException | None],
        create_controller: Any,
        create_status_callback: Any,
        run_agent_until_done: Any,
        end_states: list[AgentState],
    ) -> tuple[bool, Any, asyncio.Task[Any] | None] | None:
        """Handle /command. Returns (continue_loop, controller, agent_task) or None to break."""
        from backend.cli.repl import SlashCommandParseError, _parse_slash_command

        host = cast(RunHelpersHost, self)
        try:
            parsed_command = _parse_slash_command(text)
        except SlashCommandParseError as exc:
            self._warn(str(exc))
            return True, controller, agent_task
        if parsed_command.name in ('/resume', '/compact', '/retry'):
            await engine_init_done.wait()
            if engine_init_exc[0] is not None:
                return True, controller, agent_task
        should_continue = _handle_parsed_command_from_host(host, parsed_command)
        if not should_continue:
            return None
        if self._pending_resume is not None:
            target = self._pending_resume
            self._pending_resume = None
            await self._cancel_agent(agent_task)
            controller = None
            agent_task = None
            result = await _resume_session_from_host(
                host,
                target,
                self._config,
                create_controller,
                create_status_callback,
                run_agent_until_done,
                end_states,
            )
            if result is not None:
                controller, agent_task = result
            return True, controller, agent_task
        if self._next_action is not None:
            # /compact or /retry: fall through to agent dispatch below
            return False, controller, agent_task
        return True, controller, agent_task

    def _validate_engine_components_ready(self) -> bool:
        if (
            self._agent is None
            or self._llm_registry is None
            or self._conversation_stats is None
            or self._runtime is None
            or self._memory is None
            or self._event_stream is None
        ):
            if self._renderer is not None:
                self._renderer.add_system_message(
                    'Initialization failed: engine components were not created.',
                    title='error',
                )
            return False
        return True

    async def _dispatch_user_turn(
        self,
        text: str,
        controller: Any,
        agent_task: asyncio.Task[Any] | None,
        create_controller: Any,
        create_status_callback: Any,
        run_agent_until_done: Any,
        end_states: list[AgentState],
        session: Any | None,
    ) -> tuple[Any, asyncio.Task[Any] | None]:
        config = self._config
        agent = self._agent
        runtime = self._runtime
        memory = self._memory
        event_stream = self._event_stream
        conversation_stats = self._conversation_stats
        renderer = self._renderer
        assert renderer is not None
        logger.debug('REPL: _dispatch_user_turn ENTER for text=%r', text[:80])

        # -- user message: start Live for agent turn
        self._set_footer_system_line('')
        initial_action = await self._prepare_initial_action(text, renderer)
        renderer.begin_turn()

        controller, agent_task = await self._ensure_controller_loop(
            controller=controller,
            agent_task=agent_task,
            create_controller=create_controller,
            create_status_callback=create_status_callback,
            run_agent_until_done=run_agent_until_done,
            agent=agent,
            runtime=runtime,
            config=config,
            conversation_stats=conversation_stats,
            memory=memory,
            end_states=end_states,
        )

        logger.debug(
            'REPL: _dispatch_user_turn: controller_loop done, dispatching event'
        )
        # Wrap event dispatch so any failure doesn't silently terminate the REPL.
        try:
            event_stream.add_event(initial_action, EventSource.USER)
        except Exception:
            logger.exception('Failed to add user event to event stream')
            renderer.add_system_message(
                'Failed to dispatch user message. Returning to prompt.',
                title='error',
            )
            renderer.stop_live()
            self._sync_terminal_after_agent_turn(session)
            self._invalidate_prompt_session(session)
            self._invalidate_pt()
            return controller, agent_task

        logger.debug('REPL: _dispatch_user_turn: calling controller.step()')
        try:
            controller.step()
        except Exception:
            logger.debug(
                'controller.step() failed, agent loop will retry',
                exc_info=True,
            )

        logger.debug('REPL: _dispatch_user_turn: waiting for agent idle')
        try:
            await self._wait_for_agent_idle(controller, agent_task)
            logger.debug('REPL: _dispatch_user_turn: agent idle OK')
        except asyncio.CancelledError:
            logger.debug('REPL: _dispatch_user_turn: CancelledError')
            renderer.stop_live()
            await self._cancel_agent(agent_task)
        except KeyboardInterrupt:
            logger.debug('REPL: _dispatch_user_turn: KeyboardInterrupt')
            renderer.stop_live()
            await self._cancel_agent(agent_task)
        except Exception:
            logger.exception('Unhandled exception during agent turn')
            renderer.stop_live()
            renderer.add_system_message(
                'Agent run failed with an unexpected error. '
                'Check the logs or try again.',
                title='error',
            )
            await self._cancel_agent(agent_task)
        finally:
            renderer.stop_live()
            self._sync_terminal_after_agent_turn(session)
            self._invalidate_prompt_session(session)
            self._invalidate_pt()
            logger.debug('REPL: _dispatch_user_turn: finally done')
        return controller, agent_task

    async def _prepare_initial_action(
        self,
        text: str,
        renderer: Any,
    ) -> Any:
        if self._next_action is not None:
            next_content = getattr(self._next_action, 'content', None)
            if next_content is not None and text.strip() != str(next_content).strip():
                logger.warning(
                    'Discarding stale _next_action in favor of new user message'
                )
                self._next_action = None
            else:
                initial_action = self._next_action
                self._next_action = None
                msg_content = getattr(initial_action, 'content', None)
                if msg_content is not None:
                    renderer.start_live()
                    await renderer.add_user_message(str(msg_content))
                else:
                    renderer.add_system_message(
                        'Condensing context\u2026', title='grinta'
                    )
                    renderer.start_live()
                return initial_action
        self._last_user_message = text
        renderer.start_live()
        await renderer.add_user_message(text)
        return MessageAction(content=text)

    async def _finalize_repl_run(
        self,
        bootstrap_task: asyncio.Task[None] | None,
        agent_task: asyncio.Task[Any] | None,
    ) -> None:
        logger.debug('REPL: _finalize_repl_run ENTER')
        self._pt_session = None
        await self._cancel_task_silently(bootstrap_task)
        controller = self._controller
        if controller is not None:
            with contextlib.suppress(Exception):
                controller.save_state()
                logger.debug('REPL: _finalize_repl_run: saved controller state')
        self._reasoning.stop()
        if self._renderer is not None:
            self._renderer.stop_live()
        await self._cancel_task_silently(agent_task)
        if self._memory is not None:
            close_mcp = getattr(self._memory, 'close_mcp_clients', None)
            if callable(close_mcp):
                with contextlib.suppress(Exception):
                    await close_mcp()
                    logger.debug('REPL: _finalize_repl_run: closed MCP clients')
        if self._acquire_result is not None:
            from backend.execution import runtime_orchestrator

            runtime = self._acquire_result.runtime
            try:
                runtime.close()
                logger.debug('REPL: _finalize_repl_run: closed runtime')
            except Exception as exc:
                logger.warning('REPL: _finalize_repl_run: runtime.close() failed: %s', exc)
            logger.debug('REPL: _finalize_repl_run: releasing acquire result')
            runtime_orchestrator.release(self._acquire_result)
        self._close_event_stream()
        logger.debug('REPL: _finalize_repl_run DONE')

    @staticmethod
    async def _cancel_task_silently(task: asyncio.Task[Any] | None) -> None:
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    def _close_event_stream(self) -> None:
        event_stream = self._event_stream
        if event_stream is None:
            return
        close = getattr(event_stream, 'close', None)
        if callable(close):
            with contextlib.suppress(Exception):
                close()

    async def _ensure_runtime_connected(self, runtime: Any) -> None:
        """Restore execution backend after ``hard_kill`` (e.g. Ctrl+C during a run).

        Interrupt handling tears down the in-process executor; the next user turn
        must await :meth:`~backend.execution.base.Runtime.connect` again or tools
        raise :class:`~backend.core.errors.AgentRuntimeDisconnectedError`.
        """
        if runtime is None:
            return
        if not hasattr(runtime, 'runtime_initialized'):
            return
        try:
            if runtime.runtime_initialized:
                return
        except Exception:
            logger.debug('runtime_initialized check failed', exc_info=True)
            return
        connect_fn = getattr(runtime, 'connect', None)
        if not callable(connect_fn):
            return
        await connect_fn()

    async def _ensure_controller_loop(
        self,
        *,
        controller: Any,
        agent_task: asyncio.Task[Any] | None,
        create_controller: Any,
        create_status_callback: Any,
        run_agent_until_done: Any,
        agent: Any,
        runtime: Any,
        config: AppConfig,
        conversation_stats: Any,
        memory: Any,
        end_states: list[AgentState],
    ) -> tuple[Any, asyncio.Task[Any] | None]:
        await self._ensure_runtime_connected(runtime)

        if controller is None:
            controller, _ = create_controller(
                agent, runtime, config, conversation_stats
            )
            runtime.controller = controller
            early_cb = create_status_callback(controller)
            try:
                memory.status_callback = early_cb
            except Exception:
                logger.debug('Could not set memory status callback', exc_info=True)
            self._controller = controller

        current_state = controller.get_agent_state()
        if current_state in {
            AgentState.AWAITING_USER_INPUT,
            AgentState.FINISHED,
            AgentState.ERROR,
            AgentState.REJECTED,
            AgentState.STOPPED,
        }:
            await controller.set_agent_state_to(AgentState.RUNNING)

        if agent_task is None or agent_task.done():
            agent_task = asyncio.create_task(
                run_agent_until_done(controller, runtime, memory, end_states),
                name='grinta-agent-loop',
            )

        return controller, agent_task
