"""Async REPL — prompt_toolkit input loop integrated with the agent engine."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
import time
from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, cast

logger = logging.getLogger(__name__)

from rich.console import Console

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


@dataclass(frozen=True)
class SlashCommandSpec:
    """Metadata used by help text and prompt-toolkit completion."""

    name: str
    description: str
    usage: str
    aliases: tuple[str, ...] = ()


_AUTONOMY_LEVEL_HINTS = {
    'supervised': 'Always ask before actions',
    'balanced': 'Ask only for high-risk actions',
    'full': 'Run without confirmation prompts',
}
_SLASH_COMMANDS = (
    SlashCommandSpec('/help', 'Show commands and shortcuts', '/help'),
    SlashCommandSpec('/settings', 'Open settings (model, API key, MCP)', '/settings'),
    SlashCommandSpec('/sessions', 'List past sessions', '/sessions'),
    SlashCommandSpec('/resume', 'Resume a past session by index or ID', '/resume <N|id>'),
    SlashCommandSpec(
        '/autonomy',
        'View or set autonomy (supervised/balanced/full)',
        '/autonomy [supervised|balanced|full]',
    ),
    SlashCommandSpec('/status', 'Show the current HUD snapshot', '/status'),
    SlashCommandSpec('/clear', 'Clear the visible transcript', '/clear'),
    SlashCommandSpec('/exit', 'Quit grinta', '/exit', aliases=('/quit',)),
)
_COMMAND_ALIASES = {
    alias: spec.name
    for spec in _SLASH_COMMANDS
    for alias in spec.aliases
}
_COMMAND_NAMES = tuple(
    name for spec in _SLASH_COMMANDS for name in (spec.name, *spec.aliases)
)


def _ensure_history() -> Path:
    _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    if not _HISTORY_FILE.exists():
        _HISTORY_FILE.touch()
    return _HISTORY_FILE


def _canonical_command_name(command: str) -> str:
    """Normalize slash-command aliases to a single canonical name."""
    lowered = command.lower()
    return _COMMAND_ALIASES.get(lowered, lowered)


def _iter_command_completion_entries() -> list[tuple[str, str]]:
    """Return slash commands plus aliases for prompt-toolkit completion."""
    entries: list[tuple[str, str]] = []
    for spec in _SLASH_COMMANDS:
        entries.append((spec.name, spec.description))
        entries.extend((alias, f'Alias for {spec.name}') for alias in spec.aliases)
    return entries


def _build_help_markdown() -> str:
    """Build the slash-command help block from the shared command registry."""
    lines = ['**Commands**', '']
    for spec in _SLASH_COMMANDS:
        alias_text = (
            ' _(aliases: ' + ', '.join(f'`{alias}`' for alias in spec.aliases) + ')_'
            if spec.aliases
            else ''
        )
        lines.append(f'- `{spec.usage}` — {spec.description}{alias_text}')

    lines.extend(
        [
            '',
            '**Input tips**',
            '',
            '- `Tab` autocomplete slash commands and common arguments',
            '- `↑` / `↓` search prompt history',
            '- `Alt+Enter` insert a newline',
            '- `Ctrl+C` interrupt the current run',
        ]
    )
    return '\n'.join(lines)


def _closest_command_names(command: str, *, limit: int = 2) -> list[str]:
    """Suggest the closest matching slash commands for typos."""
    matches = get_close_matches(command, _COMMAND_NAMES, n=limit, cutoff=0.5)
    suggestions: list[str] = []
    for match in matches:
        if match not in suggestions:
            suggestions.append(match)
    return suggestions


def _build_command_completer(
    load_session_suggestions: Callable[[], list[tuple[str, str]]] | None = None,
) -> Any:
    """Create the prompt-toolkit completer used by the interactive REPL."""
    from prompt_toolkit.completion import Completer, Completion

    session_loader = load_session_suggestions or (lambda: [])

    class SlashCommandCompleter(Completer):
        def get_completions(self, document, complete_event):  # type: ignore[override]
            del complete_event
            text_before_cursor = document.text_before_cursor.lstrip()
            if not text_before_cursor.startswith('/'):
                return

            has_trailing_space = document.text_before_cursor.endswith(' ')
            parts = text_before_cursor.split()
            if not parts:
                return

            command_token = parts[0].lower()
            if len(parts) == 1 and not has_trailing_space:
                prefix = command_token
                for name, description in _iter_command_completion_entries():
                    if name.startswith(prefix):
                        yield Completion(
                            name,
                            start_position=-len(prefix),
                            display_meta=description,
                        )
                return

            canonical_command = _canonical_command_name(command_token)
            argument_prefix = '' if has_trailing_space or len(parts) < 2 else parts[1]

            if canonical_command == '/autonomy':
                lowered_prefix = argument_prefix.lower()
                for level, description in _AUTONOMY_LEVEL_HINTS.items():
                    if level.startswith(lowered_prefix):
                        yield Completion(
                            level,
                            start_position=-len(argument_prefix),
                            display_meta=description,
                        )
                return

            if canonical_command == '/resume':
                lowered_prefix = argument_prefix.lower()
                seen: set[str] = set()
                for candidate, description in session_loader():
                    if candidate in seen:
                        continue
                    if lowered_prefix and not candidate.lower().startswith(lowered_prefix):
                        continue
                    seen.add(candidate)
                    yield Completion(
                        candidate,
                        start_position=-len(argument_prefix),
                        display_meta=description,
                    )

    return SlashCommandCompleter()


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

    def _current_prompt_state(self) -> AgentState | None:
        renderer = self._renderer
        state = getattr(renderer, 'current_state', None) if renderer is not None else None
        if isinstance(state, AgentState):
            return state

        controller = self._controller
        if controller is not None:
            with contextlib.suppress(Exception):
                candidate = controller.get_agent_state()
                if isinstance(candidate, AgentState):
                    return candidate
        return None

    def _prompt_message(self) -> str:
        state = self._current_prompt_state()
        if state == AgentState.PAUSED:
            label = 'paused'
        elif state in {AgentState.ERROR, AgentState.REJECTED}:
            label = 'retry'
        else:
            label = ''
        if not label:
            return '❯ '
        return f'{label} ❯ '

    def _prompt_toolbar_text(self) -> str:
        state = self._current_prompt_state()
        status = {
            AgentState.RUNNING: 'Running',
            AgentState.AWAITING_USER_CONFIRMATION: 'Needs approval',
            AgentState.AWAITING_USER_INPUT: 'Ready',
            AgentState.PAUSED: 'Paused',
            AgentState.FINISHED: 'Done',
            AgentState.ERROR: 'Error',
            AgentState.REJECTED: 'Rejected',
            AgentState.STOPPED: 'Stopped',
        }.get(state, 'Ready')
        follow_up = {
            AgentState.PAUSED: 'Send guidance to continue',
            AgentState.ERROR: 'Send a retry instruction or /status',
            AgentState.REJECTED: 'Adjust the task and retry',
            AgentState.AWAITING_USER_CONFIRMATION: 'Approval prompt opens automatically',
            AgentState.AWAITING_USER_INPUT: 'Continue the task or ask a new question',
        }.get(state, 'Type a task or /help')
        autonomy = self._get_current_autonomy().replace(' (default)', '')
        return (
            f' {status} · {autonomy} autonomy │ Tab for commands │ '
            f'Alt+Enter newline │ {follow_up} '
        )

    def _create_prompt_session(self) -> Any:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
        from prompt_toolkit.history import FileHistory

        from backend.cli.session_manager import get_session_suggestions

        return PromptSession(
            message=self._prompt_message,
            history=FileHistory(str(_ensure_history())),
            key_bindings=_build_bindings(),
            completer=_build_command_completer(get_session_suggestions),
            auto_suggest=AutoSuggestFromHistory(),
            complete_while_typing=True,
            reserve_space_for_menu=8,
            bottom_toolbar=self._prompt_toolbar_text,
            enable_history_search=True,
            multiline=False,
        )

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
                session = self._create_prompt_session()

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

            # -- enter input loop IMMEDIATELY ----------------------------------
            controller = None
            end_states = [
                AgentState.AWAITING_USER_INPUT,
                AgentState.FINISHED,
                AgentState.REJECTED,
                AgentState.ERROR,
                AgentState.PAUSED,
                AgentState.STOPPED,
            ]

            init_task = asyncio.create_task(_heavy_init(), name='grinta-init')

            while self._running:
                try:
                    if session is None:
                        user_input = await self._read_non_interactive_input()
                        if user_input == '':
                            raise EOFError
                    else:
                        user_input = await session.prompt_async()
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

                # -- user message: print statically, then start Live for agent turn
                initial_action = MessageAction(content=text)
                self._renderer.add_user_message(text)
                self._renderer.start_live()
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
                finally:
                    self._renderer.stop_live()
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
            if self._renderer is not None:
                self._renderer.stop_live()
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
                if renderer is not None:
                    await self._drain_renderer_until_settled(renderer)
                    state = renderer.current_state or controller.get_agent_state()
                if state == AgentState.AWAITING_USER_CONFIRMATION:
                    await self._handle_confirmation(controller)
                    continue
                if state not in idle_states:
                    continue
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
                        f'Agent timed out after {_HARD_TIMEOUT} seconds. Returning to prompt.',
                        title='⏱ Timeout',
                    )
                    renderer.drain_events()
                break

    async def _drain_renderer_until_settled(
        self,
        renderer: Any,
        *,
        settle_delay: float = 0.03,
        max_passes: int = 3,
    ) -> None:
        """Drain queued CLI events until the delivery queue stays quiet briefly."""
        for _ in range(max_passes):
            renderer.drain_events()
            if getattr(renderer, 'pending_event_count', 0) == 0:
                await asyncio.sleep(settle_delay)
                renderer.drain_events()
                if getattr(renderer, 'pending_event_count', 0) == 0:
                    return
            else:
                await asyncio.sleep(settle_delay)

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
        valid_levels = tuple(_AUTONOMY_LEVEL_HINTS)

        if len(parts) < 2:
            # Show current level
            level = self._get_current_autonomy()
            if self._renderer is not None:
                level_lines = '\n'.join(
                    f'  {name:<10} — {_AUTONOMY_LEVEL_HINTS[name]}'
                    for name in valid_levels
                )
                self._renderer.add_system_message(
                    f'Autonomy: {level}\n'
                    f'{level_lines}\n'
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
        raw_cmd = text.lower().split()[0]
        cmd = _canonical_command_name(raw_cmd)

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
                    'Screen cleared. Type a task or press Tab after `/` for commands.',
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
                        'Usage: /resume <N> or /resume <session_id>. Press Tab to autocomplete recent sessions.',
                        title='warning',
                    )
                return True
            self._pending_resume = parts[1]
            return True

        if cmd == '/autonomy':
            self._handle_autonomy_command(text)
            return True

        if cmd == '/help':
            if self._renderer is not None:
                self._renderer.add_markdown_block(
                    'Help',
                    _build_help_markdown(),
                )
            return True

        if self._renderer is not None:
            suggestion_text = _closest_command_names(raw_cmd)
            suffix = ''
            if suggestion_text:
                rendered_suggestions = ' or '.join(f'`{item}`' for item in suggestion_text)
                suffix = f' Try {rendered_suggestions}.'
            self._renderer.add_system_message(
                f'Unknown command: {raw_cmd}.{suffix} Press Tab after `/` for autocomplete.',
                title='warning',
            )
        return True
