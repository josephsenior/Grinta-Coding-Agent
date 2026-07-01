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


class ScreenSlashMixin(SlashCommandsMixin):
    """Wire :class:`SlashCommandsMixin` into the Textual TUI screen."""

    def _init_slash_renderer(self) -> None:
        if getattr(self, '_slash_renderer', None) is None:
            self._slash_renderer = _TUIRendererAdapter(self)
        self._renderer = self._slash_renderer

    def _warn(self, msg: str) -> None:
        self._init_slash_renderer()
        self._renderer.add_system_message(msg, title='warning')

    def _usage(self, name: str) -> str:
        from backend.cli.repl.slash_registry_help import _find_command_spec

        spec = _find_command_spec(name)
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

    async def _handle_slash_command(self, text: str) -> None:
        self._init_slash_renderer()
        should_continue = handle_command(self, text)
        if not should_continue:
            self._agent_running = False
            self.app.exit()

    def _cmd_exit(self, parsed: Any) -> bool:
        self._init_slash_renderer()
        from backend.cli.repl.slash_command_actions import cmd_exit

        return cmd_exit(self, parsed)

    def _cmd_settings(self, parsed: Any) -> bool:
        del parsed
        self.run_worker(self._open_settings_tui(), exclusive=True)
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
        self.run_worker(self._run_sessions_tui(args), exclusive=True)
        return True

    def _cmd_resume(self, parsed: Any) -> bool:
        args = list(parsed.args)
        self.run_worker(self._run_resume_tui(args), exclusive=True)
        return True

    def _cmd_help(self, parsed: Any) -> bool:
        del parsed
        self.show_help()
        return True
