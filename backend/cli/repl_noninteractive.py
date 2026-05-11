"""Non-interactive REPL fallback — Rich-based line-by-line reader.

Used when stdin is not a TTY (piped input, CI, etc.). No prompt_toolkit,
no Textual — just simple Rich prints and blocking reads.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import TYPE_CHECKING

from rich.console import Console
from rich.prompt import Prompt

from backend.cli.hud import HUDBar
from backend.cli.reasoning_display import ReasoningDisplay
from backend.cli.theme import mark_prompt
from backend.core.enums import AgentState

if TYPE_CHECKING:
    from backend.cli.config_manager import AppConfig

logger = logging.getLogger(__name__)


async def run_noninteractive(
    config: AppConfig,
    console: Console,
    *,
    initial_input: str | None = None,
    verbose: bool = False,
) -> None:
    """Run non-interactive REPL: bootstrap agent, read lines, dispatch, print."""
    from backend.cli.event_renderer import CLIEventRenderer
    from backend.core.config import load_app_config

    hud = HUDBar()
    reasoning = ReasoningDisplay()
    renderer = CLIEventRenderer(console=console, hud=hud, reasoning=reasoning)

    from backend.core.bootstrap.agent_control_loop import run_agent_until_done
    from backend.core.bootstrap.setup import create_agent, create_memory, create_runtime
    from backend.inference.llm_registry import LLMRegistry
    from backend.orchestration.conversation_stats import ConversationStats
    from backend.orchestration.orchestration_config import OrchestrationConfig
    from backend.orchestration.session_orchestrator import SessionOrchestrator

    console.print('[dim]Initializing engine...[/dim]')

    app_config = load_app_config()
    llm_registry = LLMRegistry(app_config)
    runtime = create_runtime(app_config, llm_registry)

    event_stream = runtime.event_stream
    if event_stream is None:
        console.print('[red]Runtime has no event stream[/red]')
        return

    agent = create_agent(app_config, llm_registry)
    memory = create_memory(runtime, event_stream, event_stream.sid)
    conversation_stats = ConversationStats(
            file_store=event_stream.file_store,
            conversation_id=event_stream.sid,
            user_id=None,
        )

    controller = SessionOrchestrator(
        config=OrchestrationConfig(
            agent=agent,
            event_stream=event_stream,
            conversation_stats=conversation_stats,
            iteration_delta=config.max_iterations,
            headless_mode=True,
        )
    )
    controller.runtime = runtime

    renderer.subscribe(event_stream, event_stream.sid)

    end_states: list[AgentState] = [AgentState.AWAITING_USER_INPUT, AgentState.FINISHED, AgentState.ERROR, AgentState.STOPPED]
    agent_task = asyncio.create_task(
        run_agent_until_done(controller, runtime, memory, end_states)
    )

    console.print('[dim]Engine ready.[/dim]')

    # -- input loop ----------------------------------------------------------
    from backend.core.enums import EventSource
    from backend.ledger.action import MessageAction

    try:
        if initial_input:
            lines = [initial_input]
        else:
            lines = sys.stdin.readlines() if not sys.stdin.isatty() else []

        if not lines:
            # Interactive fallback within non-TTY — one-shot Prompt
            prompt = mark_prompt()
            text = Prompt.ask(f'[bold #2dd4bf]{prompt}[/]')
            if text:
                lines = [text]

        for line in lines:
            text = line.strip()
            if not text:
                continue
            if text.startswith('/'):
                _handle_slash_command(text, console)
                continue

            console.print(f'[bold #2dd4bf]>[+] [dim]you[/dim][/] {text}')

            action = MessageAction(content=text)
            event_stream.add_event(action, EventSource.USER)
            controller.step()

            # Wait for agent to complete
            end_state_set = {'AWAITING_USER_INPUT', 'FINISHED', 'ERROR', 'STOPPED', 'AWAITING_USER_CONFIRMATION'}
            while True:
                await asyncio.sleep(0.1)
                state = controller.get_agent_state()
                if state in end_state_set:
                    break
                if agent_task.done():
                    break
                # Drain events so renderer processes them
                renderer.drain_events()

    except KeyboardInterrupt:
        pass
    finally:
        agent_task.cancel()
        try:
            await asyncio.wait_for(agent_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        from backend.inference.direct_clients import aclose_shared_http_clients
        await aclose_shared_http_clients()


def _handle_slash_command(text: str, console: Console) -> None:
    cmd = text.lower().strip()
    if cmd in ('/quit', '/q', '/exit'):
        sys.exit(0)
    elif cmd in ('/help', '/h', '/?'):
        console.print('[dim]Available commands: /help, /clear, /quit[/dim]')
    elif cmd in ('/clear', '/c'):
        console.print('[dim](clear not available in non-interactive mode)[/dim]')
    else:
        console.print(f'[bold #f87171]Unknown command: {text}[/]')
