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

from backend.cli.hud import HUDBar
from backend.cli.reasoning_display import ReasoningDisplay
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
    import time
    from backend.cli.event_renderer import CLIEventRenderer
    from backend.core.bootstrap.main import (
        run_controller,
    )
    from backend.core.enums import AgentState, EventSource
    from backend.ledger.action import MessageAction

    hud = HUDBar()
    reasoning = ReasoningDisplay()
    renderer = CLIEventRenderer(console=console, hud=hud, reasoning=reasoning)

    console.print('[dim]Initializing engine...[/dim]')

    try:
        if initial_input:
            lines = [initial_input]
        else:
            lines = sys.stdin.readlines()

        if not lines:
            console.print('[dim]No input provided. Use: echo "task" | grinta[/dim]')
            return

        for line in lines:
            text = line.strip()
            if not text:
                continue
            if text.startswith('/'):
                _handle_slash_command(text, console)
                continue

            console.print(f'[bold #2dd4bf]>[+] [dim]you[/dim][/] {text}')

            start_time = time.time()
            console.print(f'[dim]Starting agent...[/dim]')

            initial_action = MessageAction(content=text)

            state = await run_controller(
                config_=config,
                initial_action=initial_action,
                headless_mode=True,
            )

            elapsed = time.time() - start_time
            if state is None:
                console.print('[yellow]Agent did not produce a final state[/yellow]')
            elif state.agent_state == AgentState.FINISHED:
                console.print(f'[green]Agent completed in {elapsed:.1f}s[/green]')
            elif state.agent_state == AgentState.ERROR:
                console.print(f'[red]Agent ended with error in {elapsed:.1f}s[/red]')
            else:
                console.print(f'[yellow]Agent stopped at {state.agent_state} after {elapsed:.1f}s[/yellow]')

    except KeyboardInterrupt:
        console.print('[yellow]Interrupted by user[/yellow]')
    except Exception as e:
        console.print(f'[red]Error: {type(e).__name__}: {e}[/red]')
        import traceback
        traceback.print_exc()
    finally:
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
