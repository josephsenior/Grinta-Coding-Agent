"""Non-interactive REPL fallback — Rich-based line-by-line reader.

Used when stdin is not a TTY (piped input, CI, etc.). No prompt_toolkit,
no Textual — just simple Rich prints and blocking reads.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

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

    host = _NonInteractiveHost(
        config=config, console=console, hud=hud, renderer=renderer
    )

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
                _handle_slash_command(text, host)
                continue

            console.print(f'[bold #2dd4bf]>[+] [dim]you[/dim][/] {text}')

            start_time = time.time()
            renderer.add_system_message('Starting agent...', title='system')

            initial_action = MessageAction(content=text)
            host._last_user_message = text

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
            elif state.agent_state in (
                AgentState.FINISHED,
                AgentState.AWAITING_USER_INPUT,
            ):
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


def _handle_slash_command(text: str, host: '_NonInteractiveHost') -> None:
    """Dispatch a slash command in non-interactive mode.

    Routes through the central ``COMMAND_DISPATCH`` table. Read-only-safe
    commands (``/status``, ``/cost``, ``/health``, ``/model``, ``/diff``,
    ``/clear``, ``/copy``, ``/help``) are supported. Commands that
    require a TTY (``/settings``, ``/sessions``, ``/resume``) and any
    playbook / mutating command print a not-available message. Unknown
    commands are reported with a compact suggestion.
    """
    from backend.cli.repl.slash_command_actions import (
        cmd_clear,
        cmd_copy,
        cmd_help,
        cmd_model,
    )
    from backend.cli.repl.slash_command_diff import cmd_diff
    from backend.cli.repl.slash_command_dispatch import (
        COMMAND_DISPATCH,
        _render_unknown_noninteractive,
    )
    from backend.cli.repl.slash_command_status import cmd_cost, cmd_health, cmd_status
    from backend.cli.repl.slash_registry_models import SlashCommandParseError
    from backend.cli.repl.slash_registry_parsing import parse_slash_command

    cmd = text.lower().strip()
    if cmd in ('/quit', '/q', '/exit'):
        sys.exit(0)

    try:
        parsed = parse_slash_command(text)
    except SlashCommandParseError as exc:
        host._warn(str(exc))
        return

    if parsed.name in ('/settings', '/sessions', '/resume'):
        host._warn(
            f'`{parsed.name.lstrip("/")}` is not available in piped '
            '(non-interactive) mode. Run `grinta` in a TTY for the full '
            'slash surface.'
        )
        return

    method_name = COMMAND_DISPATCH.get(parsed.name)
    if method_name is None:
        _render_unknown_noninteractive(host, parsed.raw_name)
        return

    PIPED_MODE_COMMANDS = {
        '_cmd_status': cmd_status,
        '_cmd_cost': cmd_cost,
        '_cmd_health': cmd_health,
        '_cmd_model': cmd_model,
        '_cmd_diff': cmd_diff,
        '_cmd_copy': cmd_copy,
        '_cmd_clear': cmd_clear,
        '_cmd_help': cmd_help,
    }
    func = PIPED_MODE_COMMANDS.get(method_name)
    if func is None:
        host._warn(
            f'`{parsed.name}` requires an interactive TTY session. '
            'Run `grinta` (no pipe) to use it.'
        )
        return
    _invoke(func, host, parsed)


def _invoke(func: Any, host: Any, parsed: Any) -> bool:
    try:
        return func(host, parsed)
    except Exception as exc:
        host._warn(f'Command failed: {type(exc).__name__}: {exc}')
        return True


class _NonInteractiveHost:
    """Minimal host adapter for slash commands in piped mode.

    Satisfies the attribute subset of :class:`SlashCommandsMixin` that
    the read-only-safe commands (``/status``, ``/cost``, ``/health``,
    ``/model``, ``/diff``, ``/clear``, ``/copy``, ``/help``) touch.
    Anything that requires a controller/event-stream is left as ``None``
    and a ``_warn`` message is shown instead.
    """

    def __init__(
        self,
        *,
        config: Any,
        console: Console,
        hud: HUDBar,
        renderer: Any,
    ) -> None:
        self._config = config
        self._console = console
        self._hud = hud
        self._renderer = renderer
        self._controller = None
        self._event_stream = None
        self._next_action = None
        self._pending_resume = None
        self._last_user_message = None

    def _warn(self, msg: str) -> None:
        self._renderer.add_system_message(msg, title='warning')

    def _usage(self, name: str) -> str:
        from backend.cli.repl.slash_registry_commands import (
            _SLASH_COMMANDS,
        )

        for spec in _SLASH_COMMANDS:
            if spec.name == name:
                return spec.usage
        return name

    def _reject_extra_args(self, parsed: Any) -> bool:
        if parsed.args:
            self._warn(f'Usage: {self._usage(parsed.name)}')
            return True
        return False

    def _command_project_root(self) -> Path:
        return Path.cwd()
