"""User-turn dispatch, input reading, and finalization for :class:`RunHelpersMixin`.

Owns:
- :func:`_read_repl_input` — the prompt-toolkit (or stdin) input loop,
  with a Ctrl-C hint and a 10-failure soft-exit guard.
- :func:`_discard_terminal_noise` — drops control-sequence noise from
  selection/copy events.
- :func:`_process_slash_command` — handles ``/command`` parsing, hooks
  into the engine-init barrier, and triggers session resume when a
  pending resume target is set.
- :func:`_dispatch_user_turn` — the main agent-turn coordinator (start
  live, ensure controller loop, dispatch event, wait for idle, cleanup).
- :func:`_validate_engine_components_ready` and
  :func:`_prepare_initial_action` — the validation and event-construction
  helpers called by :func:`_dispatch_user_turn`.
- :func:`_ensure_runtime_connected` and
  :func:`_ensure_controller_loop` — restore the execution backend after
  a hard-kill and lazily create the controller / agent-loop task.
- :func:`_finalize_repl_run` and friends — graceful shutdown of the
  REPL, including the cancel-task-silently helper and event-stream
  cleanup.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from backend.cli._typing import RunHelpersHost
from backend.cli.theme import CLR_STATUS_ERR, STYLE_DIM
from backend.core.enums import AgentState, EventSource
from backend.ledger.action import MessageAction

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _validate_engine_components_ready(host: RunHelpersHost) -> bool:
    if (
        host._agent is None
        or host._llm_registry is None
        or host._conversation_stats is None
        or host._runtime is None
        or host._memory is None
        or host._event_stream is None
    ):
        if host._renderer is not None:
            host._renderer.add_system_message(
                'Initialization failed: engine components were not created.',
                title='error',
            )
        return False
    return True


async def _read_repl_input(host: RunHelpersHost, session: Any | None) -> str | None:
    """Read one line of input. Returns None to break the loop, '' to continue."""
    _MAX_CONSECUTIVE_FAILURES = 10
    try:
        if session is None:
            user_input = await host._read_non_interactive_input()
            if user_input == '':
                raise EOFError
        else:
            user_input = await session.prompt_async()
    except KeyboardInterrupt:
        if not host._prompt_ctrl_c_hint_shown:
            host._console.print(
                f'[{STYLE_DIM}]At the prompt, type /quit to exit. During a run, '
                'Ctrl+C asks the agent to stop; some terminals may need '
                'a second press.[/]'
            )
            host._prompt_ctrl_c_hint_shown = True
        host._consecutive_input_failures = 0
        return ''
    except EOFError:
        host._consecutive_input_failures = 0
        host._console.print(f'[{STYLE_DIM}]Input closed. Exiting.[/{STYLE_DIM}]')
        return None
    except asyncio.CancelledError:
        # CancelledError inherits from BaseException, not Exception,
        # but we handle it explicitly to prevent silent termination.
        logger.debug('REPL: prompt input cancelled')
        return ''
    except Exception as e:
        host._consecutive_input_failures += 1
        logger.exception('Prompt input failed')
        try:
            host._console.print(
                f'[{CLR_STATUS_ERR}]Prompt input failed ({host._consecutive_input_failures}/{_MAX_CONSECUTIVE_FAILURES}):[/] {e}',
            )
        except Exception:
            pass
        if host._consecutive_input_failures >= _MAX_CONSECUTIVE_FAILURES:
            logger.error(
                'Too many consecutive prompt failures (%d), forcing exit',
                host._consecutive_input_failures,
            )
            try:
                host._console.print(
                    f'[{CLR_STATUS_ERR}]Too many consecutive input failures. Exiting.[/]'
                )
            except Exception:
                pass
            return None
        return ''

    host._consecutive_input_failures = 0
    if not host._running:
        logger.debug('REPL: _read_repl_input: _running is False, returning None')
        return None
    return user_input


def _discard_terminal_noise(host: RunHelpersHost, text: str) -> bool:
    from backend.cli.repl.slash_command_registry import _looks_like_terminal_selection_noise

    if not _looks_like_terminal_selection_noise(text):
        return False
    if host._renderer is not None:
        host._renderer.add_system_message(
            'Ignored terminal control sequence noise from selection/copy input.',
            title='warning',
        )
    return True


async def _process_slash_command(
    host: RunHelpersHost,
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
    from backend.cli.repl.slash_command_registry import (
        SlashCommandParseError,
        _parse_slash_command,
    )

    try:
        parsed_command = _parse_slash_command(text)
    except SlashCommandParseError as exc:
        host._warn(str(exc))
        return True, controller, agent_task
    if parsed_command.name in ('/resume', '/compact', '/retry'):
        await engine_init_done.wait()
        if engine_init_exc[0] is not None:
            return True, controller, agent_task
    should_continue = bool(host._handle_parsed_command(parsed_command))
    if not should_continue:
        return None
    if host._pending_resume is not None:
        target = host._pending_resume
        host._pending_resume = None
        await host._cancel_agent(agent_task)
        controller = None
        agent_task = None
        result = await host._resume_session(
            target,
            host._config,
            create_controller,
            create_status_callback,
            run_agent_until_done,
            end_states,
        )
        if result is not None:
            controller, agent_task = result
        return True, controller, agent_task
    if host._next_action is not None:
        # /compact or /retry: fall through to agent dispatch below
        return False, controller, agent_task
    return True, controller, agent_task


async def _dispatch_user_turn(
    host: RunHelpersHost,
    text: str,
    controller: Any,
    agent_task: asyncio.Task[Any] | None,
    create_controller: Any,
    create_status_callback: Any,
    run_agent_until_done: Any,
    end_states: list[AgentState],
    session: Any | None,
) -> tuple[Any, asyncio.Task[Any] | None]:
    config = host._config
    agent = host._agent
    runtime = host._runtime
    memory = host._memory
    event_stream = host._event_stream
    conversation_stats = host._conversation_stats
    renderer = host._renderer
    assert renderer is not None
    logger.debug('REPL: _dispatch_user_turn ENTER for text=%r', text[:80])

    # -- user message: start Live for agent turn
    host._set_footer_system_line('')
    initial_action = await _prepare_initial_action(host, text, renderer)
    renderer.begin_turn()

    controller, agent_task = await host._ensure_controller_loop(
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

    logger.debug('REPL: _dispatch_user_turn: controller_loop done, dispatching event')
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
        host._sync_terminal_after_agent_turn(session)
        host._invalidate_prompt_session(session)
        host._invalidate_pt()
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
        await host._wait_for_agent_idle(controller, agent_task)
        logger.debug('REPL: _dispatch_user_turn: agent idle OK')
    except asyncio.CancelledError:
        logger.debug('REPL: _dispatch_user_turn: CancelledError')
        renderer.stop_live()
        await host._cancel_agent(agent_task)
    except KeyboardInterrupt:
        logger.debug('REPL: _dispatch_user_turn: KeyboardInterrupt')
        renderer.stop_live()
        await host._cancel_agent(agent_task)
    except Exception:
        logger.exception('Unhandled exception during agent turn')
        renderer.stop_live()
        renderer.add_system_message(
            'Agent run failed with an unexpected error. Check the logs or try again.',
            title='error',
        )
        await host._cancel_agent(agent_task)
    finally:
        renderer.stop_live()
        host._sync_terminal_after_agent_turn(session)
        host._invalidate_prompt_session(session)
        host._invalidate_pt()
        logger.debug('REPL: _dispatch_user_turn: finally done')
    return controller, agent_task


async def _prepare_initial_action(
    host: RunHelpersHost,
    text: str,
    renderer: Any,
) -> Any:
    if host._next_action is not None:
        next_content = getattr(host._next_action, 'content', None)
        if next_content is not None and text.strip() != str(next_content).strip():
            logger.warning('Discarding stale _next_action in favor of new user message')
            host._next_action = None
        else:
            initial_action = host._next_action
            host._next_action = None
            msg_content = getattr(initial_action, 'content', None)
            if msg_content is not None:
                renderer.start_live()
                await renderer.add_user_message(str(msg_content))
            else:
                renderer.add_system_message('Condensing context\u2026', title='grinta')
                renderer.start_live()
            return initial_action
    host._last_user_message = text
    renderer.start_live()
    await renderer.add_user_message(text)
    return MessageAction(content=text)


async def _ensure_runtime_connected(host: RunHelpersHost, runtime: Any) -> None:
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
    host: RunHelpersHost,
    *,
    controller: Any,
    agent_task: asyncio.Task[Any] | None,
    create_controller: Any,
    create_status_callback: Any,
    run_agent_until_done: Any,
    agent: Any,
    runtime: Any,
    config: Any,
    conversation_stats: Any,
    memory: Any,
    end_states: list[AgentState],
) -> tuple[Any, asyncio.Task[Any] | None]:
    await _ensure_runtime_connected(host, runtime)

    if controller is None:
        controller, _ = create_controller(agent, runtime, config, conversation_stats)
        runtime.controller = controller
        early_cb = create_status_callback(controller)
        try:
            memory.status_callback = early_cb
        except Exception:
            logger.debug('Could not set memory status callback', exc_info=True)
        host._controller = controller

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


async def _finalize_repl_run(
    host: RunHelpersHost,
    bootstrap_task: asyncio.Task[None] | None,
    agent_task: asyncio.Task[Any] | None,
) -> None:
    logger.debug('REPL: _finalize_repl_run ENTER')
    host._pt_session = None
    await _cancel_task_silently(bootstrap_task)
    controller = host._controller
    if controller is not None:
        with contextlib.suppress(Exception):
            controller.save_state()
            logger.debug('REPL: _finalize_repl_run: saved controller state')
    host._reasoning.stop()
    if host._renderer is not None:
        host._renderer.stop_live()
    await _cancel_task_silently(agent_task)
    if host._memory is not None:
        close_mcp = getattr(host._memory, 'close_mcp_clients', None)
        if callable(close_mcp):
            with contextlib.suppress(Exception):
                await close_mcp()
                logger.debug('REPL: _finalize_repl_run: closed MCP clients')
    if host._acquire_result is not None:
        from backend.execution import runtime_orchestrator

        runtime = host._acquire_result.runtime
        try:
            runtime.close()
            logger.debug('REPL: _finalize_repl_run: closed runtime')
        except Exception as exc:
            logger.warning('REPL: _finalize_repl_run: runtime.close() failed: %s', exc)
        logger.debug('REPL: _finalize_repl_run: releasing acquire result')
        runtime_orchestrator.release(host._acquire_result)
    _close_event_stream(host)
    logger.debug('REPL: _finalize_repl_run DONE')


async def _cancel_task_silently(task: asyncio.Task[Any] | None) -> None:
    if task is None or task.done():
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task


def _close_event_stream(host: RunHelpersHost) -> None:
    event_stream = host._event_stream
    if event_stream is None:
        return
    close = getattr(event_stream, 'close', None)
    if callable(close):
        with contextlib.suppress(Exception):
            close()
