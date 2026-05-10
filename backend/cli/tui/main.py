"""Grinta TUI — main runner that boots the Textual app.

This is the TUI equivalent of the CLI's Repl.run(). It creates the event loop,
bootstraps the agent, and runs the Textual application.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.app import App
from rich.console import Console as RichConsole

from backend.cli.hud import HUDBar
from backend.cli.reasoning_display import ReasoningDisplay

if TYPE_CHECKING:
    from backend.cli.config_manager import AppConfig


logger = logging.getLogger('grinta.tui')


class GrintaTUIApp(App):
    """Top-level Textual application shell."""

    TITLE = 'GRINTA'
    SUB_TITLE = 'AI-Powered Development Platform'

    def __init__(
        self,
        config: AppConfig,
        console: RichConsole,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        super().__init__()
        self._config = config
        self._console = console
        self._loop = loop
        self._hud = HUDBar()
        self._reasoning = ReasoningDisplay()
        self._session_running = True
        self._pending_confirm: asyncio.Event | None = None
        self._confirm_result: str | None = None
        self._event_stream: Any | None = None
        self._controller: Any | None = None
        self._agent_task: asyncio.Task[Any] | None = None
        self._renderer: Any | None = None
        self._input_lock = asyncio.Lock()

    def compose(self):
        """Layout is handled by the pushed screen."""
        return iter([])

    async def on_mount(self) -> None:
        from backend.cli.tui.app import GrintaScreen
        await self.push_screen(GrintaScreen(
            config=self._config,
            console=self._console,
            loop=self._loop,
            hud=self._hud,
            reasoning=self._reasoning,
            app=self,
        ))

    def update_hud(self) -> None:
        screen = self.screen
        if hasattr(screen, 'update_hud'):
            screen.update_hud()


async def run_tui(
    config: AppConfig,
    console: RichConsole,
    *,
    verbose: bool = False,
) -> None:
    """Run the Grinta TUI. This is the TUI equivalent of Repl.run()."""
    from backend.core.config import load_app_config

    loop = asyncio.get_running_loop()

    app = GrintaTUIApp(config=config, console=console, loop=loop)
    app._hud.update_model(config.get_llm_config().model or '(not set)')
    app._hud.update_workspace(
        str(Path(os.getcwd()).resolve())
        if not getattr(config, 'project_root', None)
        else str(getattr(config, 'project_root'))
    )
    app._hud.update_ledger('Starting')
    app._hud.update_agent_state('Starting')

    try:
        await app.run_async()
    except KeyboardInterrupt:
        pass
    finally:
        if app._agent_task and not app._agent_task.done():
            app._agent_task.cancel()
            try:
                await asyncio.wait_for(app._agent_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass


async def _async_main_tui(
    config: AppConfig,
    console: RichConsole,
    *,
    model: str | None = None,
    show_splash: bool = False,
    minimal: bool = False,
    accessible: bool = False,
    verbose: bool = False,
) -> None:
    if model:
        from backend.cli.config_manager import update_model
        update_model(model)

    await run_tui(config, console, verbose=verbose)
