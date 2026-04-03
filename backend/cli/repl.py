"""Async REPL — prompt_toolkit input loop integrated with the agent engine."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

logger = logging.getLogger(__name__)

from rich.console import Console
from rich.live import Live

from backend.cli.config_manager import get_current_model
from backend.cli.confirmation import build_confirmation_action, render_confirmation
from backend.cli.event_renderer import CLIEventRenderer
from backend.cli.hud import HUDBar
from backend.cli.reasoning_display import ReasoningDisplay
from backend.cli.settings_tui import open_settings
from backend.core.config import AppConfig, load_app_config
from backend.core.enums import AgentState, EventSource
from backend.ledger.action import MessageAction

if TYPE_CHECKING:
    from backend.ledger.stream import EventStream
    from prompt_toolkit import PromptSession
    from prompt_toolkit.key_binding import KeyBindings


def _prompt_toolkit_available() -> bool:
    try:
        import prompt_toolkit  # noqa: F401
    except ImportError:
        return False
    return True

# ---------------------------------------------------------------------------
# History file
# ---------------------------------------------------------------------------
_HISTORY_DIR = Path.home() / '.grinta'
_HISTORY_FILE = _HISTORY_DIR / 'history.txt'


def _ensure_history() -> Path:
    _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    if not _HISTORY_FILE.exists():
        _HISTORY_FILE.touch()
    return _HISTORY_FILE


# ---------------------------------------------------------------------------
# Key bindings for prompt_toolkit
# ---------------------------------------------------------------------------


def _build_bindings() -> Any:
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys

    kb = KeyBindings()

    @kb.add(Keys.Escape, Keys.Enter)
    def _newline(event):
        """Alt+Enter inserts a newline (multi-line input)."""
        event.current_buffer.insert_text('\n')

    return kb


def _supports_prompt_session(input_stream: Any, output_stream: Any) -> bool:
    """Use prompt_toolkit only when both streams are attached to a TTY."""
    input_is_tty = bool(getattr(input_stream, 'isatty', lambda: False)())
    output_is_tty = bool(getattr(output_stream, 'isatty', lambda: False)())
    return input_is_tty and output_is_tty and _prompt_toolkit_available()


# ---------------------------------------------------------------------------
# REPL class
# ---------------------------------------------------------------------------


class Repl:
    """Interactive REPL that drives an in-process agent session."""

    def __init__(self, config: AppConfig, console: Console) -> None:
        self._config = config
        self._console = console
        self._hud = HUDBar()
        self._reasoning = ReasoningDisplay()
        self._renderer: Any | None = None
        self._event_stream: EventStream | None = None
        self._controller: Any | None = None
        self._running = True
        # Bootstrap components (stored for session resume).
        self._agent: Any | None = None
        self._runtime: Any | None = None
        self._memory: Any | None = None
        self._llm_registry: Any | None = None
        self._conversation_stats: Any | None = None
        self._acquire_result: Any | None = None
        self._pending_resume: str | None = None
        self._queued_input: list[str] = []

    @property
    def pending_resume(self) -> str | None:
        return self._pending_resume

    def set_renderer(self, renderer: Any) -> None:
        self._renderer = renderer

    def set_controller(self, controller: Any) -> None:
        self._controller = controller

    def set_bootstrap_state(
        self,
        *,
        agent: Any | None = None,
        runtime: Any | None = None,
        memory: Any | None = None,
        llm_registry: Any | None = None,
        conversation_stats: Any | None = None,
        event_stream: Any | None = None,
        acquire_result: Any | None = None,
    ) -> None:
        if agent is not None:
            self._agent = agent
        if runtime is not None:
            self._runtime = runtime
        if memory is not None:
            self._memory = memory
        if llm_registry is not None:
            self._llm_registry = llm_registry
        if conversation_stats is not None:
            self._conversation_stats = conversation_stats
        if event_stream is not None:
            self._event_stream = event_stream
        if acquire_result is not None:
            self._acquire_result = acquire_result

    def queue_initial_input(self, text: str) -> None:
        if text:
            self._queued_input.append(text)

    async def ensure_controller_loop(
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
        ensure_controller_loop = cast(Any, self._ensure_controller_loop)
        return await ensure_controller_loop(
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

    async def cancel_agent(self, agent_task: asyncio.Task[Any] | None) -> None:
        await self._cancel_agent(agent_task)

    async def resume_session(
        self,
        target: str,
        config: AppConfig,
        create_controller: Any,
        create_status_callback: Any,
        run_agent_until_done: Any,
        end_states: list[AgentState],
    ) -> tuple[Any, asyncio.Task[Any]] | None:
        resume_session = cast(Any, self._resume_session)
        return await resume_session(
            target,
            config,
            create_controller,
            create_status_callback,
            run_agent_until_done,
            end_states,
        )

    def handle_autonomy_command(self, text: str) -> None:
        self._handle_autonomy_command(text)

    def handle_command(self, text: str) -> bool:
        return self._handle_command(text)

    async def _read_non_interactive_input(self) -> str:
        if self._queued_input:
            return self._queued_input.pop(0)
        if self._renderer is not None:
            with self._renderer.suspend_live():
                self._console.print('>>> ', end='')
        else:
            self._console.print('>>> ', end='')
        return await asyncio.to_thread(sys.stdin.readline)

    # -- public entry point ------------------------------------------------

    async def run(self) -> None:
        """Boot the engine, subscribe to events, and loop on user input."""
        loop = asyncio.get_running_loop()
        agent_task: asyncio.Task | None = None
        init_task: asyncio.Task[None] | None = None

        # -- imports (always needed) ----------------------------------------
        from backend.core.bootstrap.agent_control_loop import run_agent_until_done
        from backend.core.bootstrap.main import (
            _create_early_status_callback,
            _initialize_session_components,
            _setup_memory_and_mcp,
            _setup_runtime_for_controller,
        )
        from backend.core.bootstrap.setup import create_controller

        try:
            config = self._config
            self._hud.update_model(get_current_model(config))

            # -- prompt session (fast, no I/O) --------------------------------
            session: Any | None = None
            if _supports_prompt_session(sys.stdin, sys.stdout):
                from prompt_toolkit import PromptSession
                from prompt_toolkit.history import FileHistory

                session = PromptSession(
                    history=FileHistory(str(_ensure_history())),
                    key_bindings=_build_bindings(),
                    multiline=False,
                )

            # -- renderer (no event-stream subscription yet) ------------------
            self._renderer = CLIEventRenderer(
                self._console,
                self._hud,
                self._reasoning,
                loop=loop,
                max_budget=config.max_budget_per_task,
            )

            # -- heavy init runs in background while user sees the prompt -----
            async def _heavy_init() -> None:
                """Session bootstrap + runtime + memory + MCP in the background."""
                bootstrap_state = await asyncio.to_thread(
                    _initialize_session_components,
                    config,
                    None,
                )
                session_id = bootstrap_state[0]
                llm_registry = bootstrap_state[1]
                conversation_stats = bootstrap_state[2]
                config_ = bootstrap_state[3]
                agent = bootstrap_state[4]

                self._agent = agent
                self._llm_registry = llm_registry
                self._conversation_stats = conversation_stats
                self._config = config_

                runtime_state = await asyncio.to_thread(
                    _setup_runtime_for_controller,
                    config_,
                    llm_registry,
                    session_id,
                    True,
                    agent,
                    None,
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

                memory = await _setup_memory_and_mcp(
                    config_,
                    runtime,
                    session_id,
                    repo_directory,
                    None,
                    None,
                    agent,
                )
                self._memory = memory

                # Subscribe renderer now that the stream exists.
                self._renderer.subscribe(event_stream, event_stream.sid)

            # -- enter Live + input loop IMMEDIATELY --------------------------
            controller = None
            end_states = [
                AgentState.AWAITING_USER_INPUT,
                AgentState.FINISHED,
                AgentState.REJECTED,
                AgentState.ERROR,
                AgentState.PAUSED,
                AgentState.STOPPED,
            ]

            with Live(
                self._renderer,
                console=self._console,
                auto_refresh=False,
                transient=False,
            ) as live:
                self._renderer.attach_live(live)
                self._renderer.add_system_message(
                    'grinta ready. Type a task or /help for commands.',
                    title='grinta',
                )
                init_task = asyncio.create_task(_heavy_init(), name='grinta-init')

                while self._running:
                    try:
                        if session is None:
                            user_input = await self._read_non_interactive_input()
                            if user_input == '':
                                raise EOFError
                        else:
                            # Suspend the Live display so it stops auto-refreshing
                            # while prompt_toolkit owns the terminal for input.
                            # patch_stdout() alone can't intercept Rich's direct
                            # console writes, causing the display to redraw over
                            # the user's cursor indefinitely.
                            renderer = cast(Any, self._renderer)
                            with renderer.suspend_live():
                                user_input = await session.prompt_async('>>> ')
                    except KeyboardInterrupt:
                        continue
                    except EOFError:
                        break

                    text = user_input.strip()
                    if not text:
                        continue

                    if text.startswith('/'):
                        should_continue = self._handle_command(text)
                        if not should_continue:
                            break
                        if self._pending_resume is not None:
                            target = self._pending_resume
                            self._pending_resume = None
                            await self._cancel_agent(agent_task)
                            controller = None
                            agent_task = None
                            result = await self._resume_session(
                                target,
                                config,
                                create_controller,
                                _create_early_status_callback,
                                run_agent_until_done,
                                end_states,
                            )
                            if result is not None:
                                controller, agent_task = result
                        continue

                    # -- ensure heavy init is done before first message --------
                    if not init_task.done():
                        self._renderer.add_system_message(
                            'Initializing engine…', title='grinta'
                        )
                        try:
                            await init_task
                        except Exception as exc:
                            exc_name = type(exc).__name__
                            if (
                                'AuthenticationError' in exc_name
                                or 'api_key' in str(exc).lower()
                            ):
                                self._renderer.add_system_message(
                                    'No API key or model configured.\n'
                                    'Run grinta again and complete onboarding, '
                                    'or edit settings.json directly.\n'
                                    f'{exc}',
                                    title='error',
                                )
                            else:
                                self._renderer.add_system_message(
                                    f'Initialization failed: {exc}', title='error'
                                )
                            break
                    elif init_task.cancelled():
                        break
                    elif init_task.exception():
                        self._renderer.add_system_message(
                            f'Initialization failed: {init_task.exception()}',
                            title='error',
                        )
                        break

                    agent = self._agent
                    llm_registry = self._llm_registry
                    conversation_stats = self._conversation_stats
                    runtime = self._runtime
                    memory = self._memory
                    event_stream = self._event_stream

                    if (
                        agent is None
                        or llm_registry is None
                        or conversation_stats is None
                        or runtime is None
                        or memory is None
                        or event_stream is None
                    ):
                        self._renderer.add_system_message(
                            'Initialization failed: engine components were not created.',
                            title='error',
                        )
                        break

                    initial_action = MessageAction(content=text)
                    self._renderer.add_user_message(text)
                    self._renderer.begin_turn()

                    controller, agent_task = await self._ensure_controller_loop(
                        controller=controller,
                        agent_task=agent_task,
                        create_controller=create_controller,
                        create_status_callback=_create_early_status_callback,
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
                        await self._cancel_agent(agent_task)
                        continue
        finally:
            # Cancel background init if it never completed.
            if init_task is not None:
                if not init_task.done():
                    init_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await init_task
                else:
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        init_task.exception()
            controller = self._controller
            if controller is not None:
                with contextlib.suppress(Exception):
                    controller.save_state()
            self._reasoning.stop()
            if agent_task and not agent_task.done():
                agent_task.cancel()
                try:
                    await agent_task
                except (asyncio.CancelledError, Exception):
                    pass
            if self._acquire_result is not None:
                from backend.execution import runtime_orchestrator

                runtime_orchestrator.release(self._acquire_result)
            event_stream = self._event_stream
            if event_stream is not None:
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
            setattr(runtime, 'controller', controller)
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
            AgentState.PAUSED,
        }:
            await controller.set_agent_state_to(AgentState.RUNNING)

        if agent_task is None or agent_task.done():
            agent_task = asyncio.create_task(
                run_agent_until_done(controller, runtime, memory, end_states),
                name='grinta-agent-loop',
            )

        return controller, agent_task

    # -- wait for agent to be idle -----------------------------------------

    async def _wait_for_agent_idle(
        self, controller: Any, agent_task: asyncio.Task[Any] | None
    ) -> None:
        """Wait until agent is idle, handling confirmation prompts inline.

        Events are now processed directly in the EventStream delivery thread
        (no 3rd hop to the main loop), so the renderer state stays nearly in
        sync with the agent.  A brief yield after task completion is enough to
        let any in-flight deliveries finish.
        """
        idle_states = {
            AgentState.AWAITING_USER_INPUT,
            AgentState.FINISHED,
            AgentState.ERROR,
            AgentState.STOPPED,
            AgentState.PAUSED,
            AgentState.REJECTED,
        }

        _HARD_TIMEOUT = 120  # 2 minutes absolute ceiling
        _start = time.monotonic()

        while True:
            renderer = cast(Any, self._renderer)

            # Drain queued events and render — this is the ONLY place
            # where Live.update() happens during agent execution.
            if renderer is not None:
                renderer.drain_events()
                state = renderer.current_state or controller.get_agent_state()
            else:
                state = controller.get_agent_state()

            if state in idle_states:
                break

            if state == AgentState.AWAITING_USER_CONFIRMATION:
                await self._handle_confirmation(controller)
                continue

            # Agent task finished — drain any remaining events, then break.
            if agent_task and agent_task.done():
                if renderer is not None:
                    await asyncio.sleep(0.05)
                    renderer.drain_events()
                break

            # Yield to the event loop.  wait_for_state_change will return
            # early when the delivery thread sets _state_event.
            if renderer is None:
                await asyncio.sleep(0.1)
            else:
                await renderer.wait_for_state_change(wait_timeout_sec=0.1)

            # Hard timeout — surface error and return to prompt instead of
            # hanging forever (e.g. LLM API unresponsive).
            if time.monotonic() - _start > _HARD_TIMEOUT:
                logger.warning('Agent wait exceeded %ds hard timeout', _HARD_TIMEOUT)
                if renderer is not None:
                    renderer.add_system_message(
                        'Agent timed out after 5 minutes. Returning to prompt.',
                        title='⏱ Timeout',
                    )
                    renderer.drain_events()
                break

    # -- interrupt handler -------------------------------------------------

    async def _cancel_agent(self, agent_task: asyncio.Task[Any] | None) -> None:
        """Cancel a running agent task and return to the prompt."""
        if agent_task and not agent_task.done():
            agent_task.cancel()
            try:
                await agent_task
            except (asyncio.CancelledError, Exception):
                pass
        self._reasoning.stop()
        if self._renderer is not None:
            self._renderer.add_system_message(
                'Interrupted. Ready for input.', title='grinta'
            )

    # -- session resume ----------------------------------------------------

    async def _resume_session(
        self,
        target: str,
        config: AppConfig,
        create_controller,
        create_status_callback,
        run_agent_until_done,
        end_states: list[AgentState],
    ) -> tuple[Any, asyncio.Task[Any]] | None:
        """Resume a previous session by index or ID.

        Returns (controller, agent_task) on success, or None on failure.
        """
        from backend.cli.session_manager import get_session_id_by_index
        from backend.core.bootstrap.main import (
            _setup_memory_and_mcp,
            _setup_runtime_for_controller,
        )

        llm_registry = self._llm_registry
        agent = self._agent
        conversation_stats = self._conversation_stats
        if llm_registry is None or agent is None or conversation_stats is None:
            if self._renderer is not None:
                self._renderer.add_system_message(
                    'Resume failed: session bootstrap state is incomplete.',
                    title='error',
                )
            return None

        # Resolve target to a session ID.
        if target.isdigit():
            resolved_id = get_session_id_by_index(int(target))
            if resolved_id is None:
                if self._renderer is not None:
                    self._renderer.add_system_message(
                        f'No session at index {target}.', title='warning'
                    )
                return None
        else:
            resolved_id = target

        if self._renderer is not None:
            self._renderer.add_system_message(
                f'Resuming session: {resolved_id}', title='grinta'
            )

        try:
            runtime_state = _setup_runtime_for_controller(
                config,
                llm_registry,
                resolved_id,
                True,
                agent,
                None,
            )
            runtime = runtime_state[0]
            repo_directory = runtime_state[1]
            acquire_result = runtime_state[2]
        except Exception as exc:
            if self._renderer is not None:
                self._renderer.add_system_message(
                    f'Resume failed: {exc}', title='error'
                )
            return None

        if self._acquire_result is not None:
            from backend.execution import runtime_orchestrator

            runtime_orchestrator.release(self._acquire_result)

        event_stream = runtime.event_stream
        if event_stream is None:
            if self._renderer is not None:
                self._renderer.add_system_message(
                    'Resume failed: no event stream.', title='error'
                )
            return None

        self._event_stream = event_stream
        self._runtime = runtime
        self._acquire_result = acquire_result

        memory = await _setup_memory_and_mcp(
            config,
            runtime,
            resolved_id,
            repo_directory,
            None,
            None,
            agent,
        )
        self._memory = memory

        # Subscribe renderer to the new event stream.
        if self._renderer is not None:
            renderer = cast(Any, self._renderer)
            renderer.reset_subscription()
            renderer.subscribe(event_stream, event_stream.sid)

        controller, _ = create_controller(
            agent,
            runtime,
            config,
            conversation_stats,
        )
        setattr(runtime, 'controller', controller)
        self._controller = controller

        early_cb = create_status_callback(controller)
        try:
            memory.status_callback = early_cb
        except Exception:
            logger.debug('Could not set memory status callback', exc_info=True)

        agent_task = asyncio.create_task(
            run_agent_until_done(controller, runtime, memory, end_states),
            name='grinta-agent-loop',
        )

        if self._renderer is not None:
            self._renderer.add_system_message(
                f'Session {resolved_id} resumed. Send a message to continue.',
                title='grinta',
            )

        return controller, agent_task

    # -- confirmation handler ----------------------------------------------

    async def _handle_confirmation(self, controller) -> None:
        """Prompt user for Y/N on a pending action, then resume the engine."""
        pending = None
        try:
            pending = controller.get_pending_action()
        except Exception:
            logger.debug('get_pending_action() failed, trying fallback', exc_info=True)
            pending = getattr(controller, '_pending_action', None)

        if pending is not None:
            if self._renderer is not None:
                with self._renderer.suspend_live():
                    approved = render_confirmation(self._console, pending)
            else:
                approved = render_confirmation(self._console, pending)
        else:
            # Fallback: generic prompt if we can't get the pending action.
            from rich.prompt import Confirm

            if self._renderer is not None:
                with self._renderer.suspend_live():
                    approved = Confirm.ask(
                        '[bold yellow]The agent wants to execute an action. Approve?[/bold yellow]',
                        console=self._console,
                    )
            else:
                approved = Confirm.ask(
                    '[bold yellow]The agent wants to execute an action. Approve?[/bold yellow]',
                    console=self._console,
                )

        action = build_confirmation_action(approved)
        if self._event_stream:
            self._event_stream.add_event(action, EventSource.USER)

    # -- autonomy control --------------------------------------------------

    def _handle_autonomy_command(self, text: str) -> None:
        """View or change the autonomy level."""
        parts = text.strip().split()
        valid_levels = ('supervised', 'balanced', 'full')

        if len(parts) < 2:
            # Show current level
            level = self._get_current_autonomy()
            if self._renderer is not None:
                self._renderer.add_system_message(
                    f'Autonomy: {level}\n'
                    '  supervised — always ask for confirmation\n'
                    '  balanced   — ask for high-risk actions only\n'
                    '  full       — never ask for confirmation\n'
                    f'Change with: /autonomy <{"|".join(valid_levels)}>',
                    title='autonomy',
                )
            return

        new_level = parts[1].lower()
        if new_level not in valid_levels:
            if self._renderer is not None:
                self._renderer.add_system_message(
                    f"Invalid level '{new_level}'. Use: {', '.join(valid_levels)}",
                    title='warning',
                )
            return

        controller = self._controller
        if controller is not None:
            ac = getattr(controller, 'autonomy_controller', None)
            if ac is not None:
                ac.autonomy_level = new_level
                if self._renderer is not None:
                    self._renderer.add_system_message(
                        f'Autonomy set to: {new_level}', title='autonomy'
                    )
                return

        if self._renderer is not None:
            self._renderer.add_system_message(
                'No active controller. Send a message first to initialize, then set autonomy.',
                title='warning',
            )

    def _get_current_autonomy(self) -> str:
        controller = self._controller
        if controller is not None:
            ac = getattr(controller, 'autonomy_controller', None)
            if ac is not None:
                return str(getattr(ac, 'autonomy_level', 'balanced'))
        return 'balanced (default)'

    # -- slash commands ----------------------------------------------------

    def _handle_command(self, text: str) -> bool:
        """Handle a /command. Returns True to continue REPL, False to exit."""
        cmd = text.lower().split()[0]

        if cmd in ('/exit', '/quit'):
            if self._renderer is not None:
                self._renderer.add_system_message('Goodbye.', title='grinta')
            return False

        if cmd == '/settings':
            if self._renderer is not None:
                with self._renderer.suspend_live():
                    open_settings(self._console)
            else:
                open_settings(self._console)
            self._config = load_app_config()
            self._hud.update_model(get_current_model(self._config))
            if self._renderer is not None:
                self._renderer.add_system_message('Settings updated.', title='settings')
            return True

        if cmd == '/clear':
            if self._renderer is not None:
                self._renderer.clear_history()
                self._renderer.add_system_message(
                    'Screen cleared. Type a task or /help for commands.',
                    title='grinta',
                )
            return True

        if cmd == '/status':
            if self._renderer is not None:
                self._renderer.add_system_message(
                    self._hud.plain_text(), title='status'
                )
            return True

        if cmd == '/sessions':
            from backend.cli.session_manager import list_sessions

            if self._renderer is not None:
                with self._renderer.suspend_live():
                    list_sessions(self._console)
            else:
                list_sessions(self._console)
            return True

        if cmd == '/resume':
            parts = text.strip().split()
            if len(parts) < 2:
                if self._renderer is not None:
                    self._renderer.add_system_message(
                        'Usage: /resume <N> or /resume <session_id>',
                        title='warning',
                    )
                return True
            self._pending_resume = parts[1]
            return True

        if cmd.startswith('/autonomy'):
            self._handle_autonomy_command(text)
            return True

        if cmd == '/help':
            if self._renderer is not None:
                self._renderer.add_markdown_block(
                    'Help',
                    """
**Commands**

- `/settings` Open settings (model, API key, MCP)
- `/sessions` List past sessions
- `/resume <N|id>` Resume a past session by index or ID
- `/autonomy [level]` View or set autonomy (supervised/balanced/full)
- `/status` Show current HUD snapshot
- `/clear` Clear the visible transcript
- `/exit` Quit grinta

Alt+Enter inserts a newline.
""".strip(),
                )
            return True

        if self._renderer is not None:
            self._renderer.add_system_message(
                f'Unknown command: {cmd}', title='warning'
            )
        return True
