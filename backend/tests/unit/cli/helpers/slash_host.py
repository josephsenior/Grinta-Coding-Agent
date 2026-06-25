"""Minimal slash-command host for unit tests (replaces legacy Repl)."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from rich.console import Console

from backend.cli.repl.slash_command_dispatch import handle_command
from backend.cli.repl.slash_commands_mixin import SlashCommandsMixin


class _FakeRenderer:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.markdown_blocks: list[tuple[str, str]] = []
        self.history_cleared = False

    def add_system_message(self, msg: str, *, title: str = '') -> None:
        self.messages.append((title, msg))

    def add_markdown_block(self, title: str, body: str) -> None:
        self.markdown_blocks.append((title, body))

    def clear_history(self) -> None:
        self.history_cleared = True

    def set_cli_tool_icons(self, value: Any) -> None:
        del value

    @contextmanager
    def suspend_live(self):
        yield


class _MockHudState:
    cost_usd = 0.0042
    context_tokens = 1024
    llm_calls = 3
    model = 'openai/gpt-4o'
    condensation_count = 0


class _MockHud:
    state = _MockHudState()

    def plain_text(self) -> str:
        return 'HUD text'

    def update_model(self, model: str) -> None:
        del model

    @staticmethod
    def describe_model(model_id: str) -> tuple[str, str]:
        parts = model_id.split('/', 1) if '/' in model_id else ('unknown', model_id)
        return parts[0], parts[1]


class SlashCommandHost(SlashCommandsMixin):
    """Test double implementing SlashCommandsMixin without the legacy Repl."""

    def __init__(self, project_root: Path | None = None) -> None:
        self._renderer: Any = _FakeRenderer()
        self._console = Console(quiet=True)
        self._config = MagicMock()
        self._config.cli_tool_icons = True
        self._hud = _MockHud()  # type: ignore[assignment]
        self._controller: MagicMock | None = None
        self._event_stream = None
        self._next_action = None
        self._pending_resume: str | None = None
        self._last_user_message = 'previous message'
        self._project_root = project_root or Path.cwd()

    @property
    def pending_resume(self) -> str | None:
        return self._pending_resume

    def set_renderer(self, renderer: Any) -> None:
        self._renderer = renderer

    def handle_command(self, text: str) -> bool:
        return handle_command(self, text)

    def _warn(self, msg: str) -> None:
        if self._renderer is not None:
            self._renderer.add_system_message(msg, title='warning')

    def _usage(self, cmd: str) -> str:
        return f'{cmd} [args]'

    def _reject_extra_args(self, parsed: Any) -> bool:
        if parsed.args:
            self._warn(f'Usage: {self._usage(parsed.name)}')
            return True
        return False

    def _command_project_root(self) -> Path:
        return self._project_root


def make_slash_host(project_root: Path | None = None) -> SlashCommandHost:
    return SlashCommandHost(project_root)
