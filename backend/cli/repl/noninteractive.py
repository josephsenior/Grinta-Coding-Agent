"""Non-interactive REPL fallback — Rich-based line-by-line reader.

Used when stdin is not a TTY (piped input, CI, etc.). No prompt_toolkit,
no Textual — just simple Rich prints and blocking reads.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

from rich.console import Console

from backend.cli.display.hud import HUDBar
from backend.cli.display.reasoning_display import ReasoningDisplay

if TYPE_CHECKING:
    from backend.core.config import AppConfig

logger = logging.getLogger(__name__)


async def _run_controller_with_renderer(
    config: AppConfig,
    *,
    initial_action: object,
    renderer: object,
) -> object | None:
    """Bootstrap runtime and subscribe *renderer* before the controller loop."""
    from backend.app.main import (
        _RUNTIME_ORCHESTRATOR,
        _execute_controller_lifecycle,
        _initialize_session_components,
        _setup_runtime_for_controller,
    )

    session_id, llm_registry, conversation_stats, config_, agent = (
        _initialize_session_components(config, None)
    )
    runtime, repo_directory, acquire_result = _setup_runtime_for_controller(
        config_,
        llm_registry,
        session_id,
        True,
        agent,
        None,
    )
    event_stream = runtime.event_stream
    if event_stream is None:
        raise RuntimeError('Runtime does not have an event stream')
    subscribe = getattr(renderer, 'subscribe', None)
    if callable(subscribe):
        subscribe(event_stream, event_stream.sid)
    try:
        return await _execute_controller_lifecycle(
            config_=config_,
            runtime=runtime,
            session_id=session_id,
            repo_directory=repo_directory,
            agent=agent,
            conversation_stats=conversation_stats,
            initial_action=initial_action,
            exit_on_message=False,
            fake_user_response_fn=None,
            memory=None,
            conversation_instructions=None,
        )
    finally:
        if acquire_result is not None:
            _RUNTIME_ORCHESTRATOR.release(acquire_result)


async def run_noninteractive(
    config: AppConfig,
    console: Console,
    *,
    initial_input: str | None = None,
    verbose: bool = False,
) -> None:
    """Run non-interactive REPL: bootstrap agent, read lines, dispatch, print."""
    import time

    from backend.cli.event_renderer import CLIEventRenderer
    from backend.core.enums import AgentState
    from backend.ledger.action import MessageAction

    hud = HUDBar()
    reasoning = ReasoningDisplay()
    renderer = CLIEventRenderer(console=console, hud=hud, reasoning=reasoning)

    renderer.add_system_message('Initializing engine...', title='system')

    try:
        if initial_input:
            lines = [initial_input]
        else:
            lines = sys.stdin.readlines()

        if not lines:
            renderer.add_system_message(
                'No input provided. Use: echo "task" | grinta',
                title='system',
            )
            return

        for line in lines:
            text = line.strip()
            if not text:
                continue
            if text.startswith('/'):
                _handle_slash_command(text, console, renderer)
                continue

            console.print(f'[bold #2dd4bf]>[+] [dim]you[/dim][/] {text}')

            start_time = time.time()
            renderer.add_system_message('Starting agent...', title='system')

            initial_action = MessageAction(content=text)

            state = await _run_controller_with_renderer(
                config,
                initial_action=initial_action,
                renderer=renderer,
            )

            elapsed = time.time() - start_time
            if state is None:
                renderer.add_system_message(
                    'Agent did not produce a final state',
                    title='warning',
                )
            elif state.agent_state == AgentState.FINISHED:
                renderer.add_system_message(
                    f'Agent completed in {elapsed:.1f}s',
                    title='success',
                )
            elif state.agent_state == AgentState.ERROR:
                renderer.add_system_message(
                    f'Agent ended with error in {elapsed:.1f}s',
                    title='error',
                )
            else:
                renderer.add_system_message(
                    f'Agent stopped at {state.agent_state} after {elapsed:.1f}s',
                    title='warning',
                )

    except KeyboardInterrupt:
        renderer.add_system_message('Interrupted by user', title='warning')
    except Exception as e:
        renderer.add_system_message(
            f'Error: {type(e).__name__}: {e}',
            title='error',
        )
        import traceback

        traceback.print_exc()
    finally:
        from backend.inference.clients import aclose_shared_http_clients

        await aclose_shared_http_clients()


def _handle_slash_command(text: str, console: Console, renderer: object) -> None:
    cmd = text.lower().strip()
    if cmd in ('/quit', '/q', '/exit'):
        sys.exit(0)
    elif cmd in ('/help', '/h', '/?'):
        add = getattr(renderer, 'add_system_message', None)
        if callable(add):
            add('Available commands: /help, /clear, /quit', title='help')
        else:
            console.print('[dim]Available commands: /help, /clear, /quit[/dim]')
    elif cmd in ('/clear', '/c'):
        add = getattr(renderer, 'add_system_message', None)
        if callable(add):
            add('(clear not available in non-interactive mode)', title='system')
    else:
        console.print(f'[bold #f87171]Unknown command: {text}[/]')
