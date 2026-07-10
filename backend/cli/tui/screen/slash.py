"""TUI slash-command host: shared dispatch with Rich/REPL handlers."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

from backend.cli.repl.slash_command_dispatch import handle_command
from backend.cli.repl.slash_commands_mixin import SlashCommandsMixin


class _TUIRendererAdapter:
    """Maps slash-handler renderer calls to TUI notifications and transcript."""

    def __init__(self, screen: Any) -> None:
        self._screen = screen

    def add_system_message(self, msg: str, *, title: str = '') -> None:
        severity = 'information'
        if title in {'warning', 'error'}:
            severity = title
        timeout = 8.0 if len(msg) > 200 else 6.0
        prefix = (
            f'[{title}] ' if title and title not in {'grinta', 'mode', 'status'} else ''
        )
        self._screen.notify(f'{prefix}{msg}', severity=severity, timeout=timeout)

    def add_markdown_block(self, title: str, body: str) -> None:
        header = f'{title}\n' if title else ''
        self._screen.notify(f'{header}{body}', severity='information', timeout=10.0)

    def clear_history(self) -> None:
        self._screen.clear_transcript()

    def set_cli_tool_icons(self, value: Any) -> None:
        del value

    def stop_live(self) -> None:
        pass

    def subscribe(self, event_stream: Any, sid: str) -> None:
        pass

    @contextmanager
    def suspend_live(self):
        yield

    async def drain_events_async(self) -> None:
        return


class ScreenSlashMixin(SlashCommandsMixin):
    """Wire :class:`SlashCommandsMixin` into the Textual TUI screen."""

    _slash_followup: Any | None = None

    def _init_slash_renderer(self) -> None:
        if getattr(self, '_slash_renderer', None) is None:
            self._slash_renderer = _TUIRendererAdapter(self)

    @contextmanager
    def _slash_command_renderer_scope(self):
        """Temporarily point slash handlers at the lightweight adapter."""
        self._init_slash_renderer()
        real_renderer = self._renderer
        self._renderer = self._slash_renderer
        try:
            yield
        finally:
            self._renderer = real_renderer

    def _queue_slash_followup(self, followup: Any) -> None:
        """Queue async work to run after the input lock is released."""
        self._slash_followup = followup

    def _warn(self, msg: str) -> None:
        with self._slash_command_renderer_scope():
            self._renderer.add_system_message(msg, title='warning')

    def _usage(self, name: str) -> str:
        from backend.cli.repl.slash_registry_help import find_command_spec

        spec = find_command_spec(name)
        if spec is not None:
            return spec.syntax
        return f'{name} [args]'

    def _reject_extra_args(self, parsed: Any) -> bool:
        if parsed.args:
            self._warn(f'Usage: {self._usage(parsed.name)}')
            return True
        return False

    def _command_project_root(self) -> Path:
        config = getattr(self, '_config', None)
        if config is not None:
            root = getattr(config, 'project_root', None)
            if root:
                return Path(root)
        return Path.cwd()

    async def _handle_slash_command(self, text: str) -> Any:
        """Handle a slash command.

        Returns an optional awaitable to run after ``_input_lock`` is released.
        """
        self._slash_followup = None
        with self._slash_command_renderer_scope():
            should_continue = handle_command(self, text)
            if not should_continue:
                self._agent_running = False
                self.app.exit()
                return None

            next_action = getattr(self, '_next_action', None)
            if next_action is not None:
                self._next_action = None

                async def _dispatch_next() -> None:
                    await self._dispatch_slash_queued_action(next_action)

                if self._slash_followup is None:
                    self._slash_followup = _dispatch_next()

        return self._slash_followup

    async def _dispatch_slash_queued_action(self, action: Any) -> None:
        """Run slash commands that queue an agent action (/compact, /retry, playbooks)."""
        from backend.cli.tui.widgets.small import InputBar
        from backend.core.enums import EventSource

        msg_content = getattr(action, 'content', None)
        if msg_content is not None:
            self.add_user_message(str(msg_content))
        elif self._renderer is not None:
            with self._slash_command_renderer_scope():
                self._renderer.add_system_message('Condensing context…', title='grinta')

        if getattr(self, '_turn_in_flight', False):
            if self._event_stream is not None:
                self._event_stream.add_event(action, EventSource.USER)
                await self._ensure_agent_task()
            return

        await self._ensure_controller_ready()
        if self._controller is None or self._event_stream is None:
            self.notify_warning('Agent is not ready for that command yet.')
            return

        self.query_one('#input-bar', InputBar).add_class('processing')
        self._turn_in_flight = True
        try:
            await self._handle_input_dispatch_action(action)
        except Exception:
            self._turn_in_flight = False
            self.query_one('#input-bar', InputBar).remove_class('processing')
            raise

    def _cmd_exit(self, parsed: Any) -> bool:
        with self._slash_command_renderer_scope():
            from backend.cli.repl.slash_command_actions import cmd_exit

            return cmd_exit(self, parsed)

    def _cmd_settings(self, parsed: Any) -> bool:
        del parsed
        self._queue_slash_followup(self._open_settings_tui())
        return True

    def _cmd_clear(self, parsed: Any) -> bool:
        if self._reject_extra_args(parsed):
            return True
        self.clear_transcript()
        self.notify(
            'Transcript cleared. Send a message, or type `/help` for commands.',
            severity='information',
            timeout=4.0,
        )
        return True

    def _cmd_sessions(self, parsed: Any) -> bool:
        args = list(parsed.args)

        async def _run() -> None:
            await self._run_sessions_tui(args)

        self._queue_slash_followup(_run())
        return True

    def _cmd_resume(self, parsed: Any) -> bool:
        args = list(parsed.args)

        async def _run() -> None:
            await self._run_resume_tui(args)

        self._queue_slash_followup(_run())
        return True

    def _cmd_help(self, parsed: Any) -> bool:
        del parsed
        self.show_help()
        return True
