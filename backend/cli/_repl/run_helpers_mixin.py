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
from typing import Any

from backend.cli.event_renderer import CLIEventRenderer
from backend.core.config import AppConfig
from backend.core.enums import AgentState, EventSource
from backend.ledger.action import MessageAction

logger = logging.getLogger(__name__)


class RunHelpersMixin:
    """Mixin providing the async run() pipeline helpers."""

    def _build_prompt_session(self) -> Any | None:
        import sys

        from backend.cli.repl import (
            _attach_prompt_buffer_csi_sanitizer,
            _supports_prompt_session,
        )

        session: Any | None = None
        if _supports_prompt_session(sys.stdin, sys.stdout):
            session = self._create_prompt_session()
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
        if 'AuthenticationError' in exc_name or 'api_key' in str(exc).lower():
            renderer.add_system_message(
                'No API key or model configured.\n'
                'Run grinta again and complete onboarding, '
                'or edit settings.json directly.\n'
                f'{exc}',
                title='error',
            )
        else:
            renderer.add_system_message(
                f'Initialization failed: {exc}', title='error'
            )
        self._running = False
        self._invalidate_prompt_session(session)

    async def _engine_bootstrap(
        self,
        session: Any | None,
        renderer: Any,
        chat_ready_done: asyncio.Event,
        engine_init_done: asyncio.Event,
        engine_init_exc: list[BaseException | None],
    ) -> None:
        """Prepare chat first, then finish optional tool warmup in the background."""
        from backend.core.bootstrap.main import _setup_mcp_tools

        try:
            init_ok = await self._bootstrap_init_session(
                renderer, session, engine_init_exc,
            )
            if not init_ok:
                return
            runtime_ok = await self._bootstrap_setup_runtime(
                renderer, session, chat_ready_done, engine_init_exc,
            )
            if not runtime_ok:
                return
            agent = self._agent
            if agent is None or not agent.config.enable_mcp:
                return
            try:
                await _setup_mcp_tools(agent, self._runtime, self._memory)
            except Exception as exc:
                logger.warning(
                    'MCP warmup failed after chat became ready', exc_info=True
                )
                self._hud.update_mcp_servers(0)
                msg = f'MCP warmup failed: {exc}'
                if session is not None:
                    self._set_footer_system_line(msg, kind='warning')
                else:
                    renderer.add_system_message(msg, title='warning')
            else:
                self._update_mcp_count_from_agent(agent)
                if session is not None:
                    self._set_footer_system_line('MCP tools loaded.')
                else:
                    renderer.add_system_message(
                        'MCP tools loaded.', title='system'
                    )
        finally:
            chat_ready_done.set()
            engine_init_done.set()

    async def _bootstrap_init_session(
        self,
        renderer: Any,
        session: Any | None,
        engine_init_exc: list[BaseException | None],
    ) -> bool:
        from backend.core.bootstrap.main import _initialize_session_components

        try:
            bootstrap_state = await asyncio.to_thread(
                _initialize_session_components, self._config, None,
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
        session_id = getattr(self, '_bootstrap_session_id', None)
        try:
            runtime_state = await asyncio.to_thread(
                _setup_runtime_for_controller,
                config_, llm_registry, session_id, True, agent, None,
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
                config_, runtime, session_id, repo_directory, None, None, agent,
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
        self, agent: Any, session: Any | None, renderer: Any,
    ) -> None:
        if agent.config.enable_mcp:
            msg = 'Chat ready. MCP tools warming in background.'
        else:
            self._hud.update_mcp_servers(0)
            msg = 'Ready.'
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
                    '[dim]Ctrl+C at the prompt does not exit the REPL; '
                    'type /quit or exit. While the agent is running, '
                    'Ctrl+C cancels the run (on some terminals you may need '
                    'to press it more than once).[/dim]'
                )
                self._prompt_ctrl_c_hint_shown = True
            return ''
        except EOFError:
            self._console.print('EOF Error received in prompt loop.')
            return None
        except Exception as e:
            self._console.print(f'CRASH: {e}')
            import traceback

            traceback.print_exc()
            return None

        if not self._running:
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

        try:
            parsed_command = _parse_slash_command(text)
        except SlashCommandParseError as exc:
            self._warn(str(exc))
            return True, controller, agent_task
        if parsed_command.name in ('/resume', '/compact', '/retry'):
            await engine_init_done.wait()
            if engine_init_exc[0] is not None:
                return True, controller, agent_task
        should_continue = self._handle_parsed_command(parsed_command)
        if not should_continue:
            return None
        if self._pending_resume is not None:
            target = self._pending_resume
            self._pending_resume = None
            await self._cancel_agent(agent_task)
            controller = None
            agent_task = None
            result = await self._resume_session(
                target, self._config, create_controller,
                create_status_callback, run_agent_until_done, end_states,
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

        event_stream.add_event(initial_action, EventSource.USER)
        try:
            controller.step()
        except Exception:
            logger.debug(
                'controller.step() failed, agent loop will retry',
                exc_info=True,
            )

        try:
            await self._wait_for_agent_idle(controller, agent_task)
        except (KeyboardInterrupt, asyncio.CancelledError):
            renderer.stop_live()
            await self._cancel_agent(agent_task)
        finally:
            renderer.stop_live()
            self._sync_terminal_after_agent_turn(session)
            self._invalidate_prompt_session(session)
            self._invalidate_pt()
        return controller, agent_task

    async def _prepare_initial_action(
        self, text: str, renderer: Any,
    ) -> Any:
        if self._next_action is not None:
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
        self._pt_session = None
        await self._cancel_task_silently(bootstrap_task)
        controller = self._controller
        if controller is not None:
            with contextlib.suppress(Exception):
                controller.save_state()
        self._reasoning.stop()
        if self._renderer is not None:
            self._renderer.stop_live()
        await self._cancel_task_silently(agent_task)
        if self._acquire_result is not None:
            from backend.execution import runtime_orchestrator

            runtime_orchestrator.release(self._acquire_result)
        self._close_event_stream()

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
