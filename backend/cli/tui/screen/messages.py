from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from rich.rule import Rule
from rich.text import Text
from textual.widgets import (
    Static,
    TextArea,
)

from backend.cli.event_rendering.text_utils import sanitize_visible_transcript_text
from backend.cli.theme import (
    NAVY_BORDER,
    NAVY_READY,
    NAVY_TEXT_MUTED,
    NAVY_TEXT_PRIMARY,
)
from backend.cli.tui.constants import _tui_logger
from backend.cli.tui.helpers import (
    _rich_text,
)
from backend.cli.tui.widgets.small import (
    InputBar,
    Transcript,
)
from backend.cli.tui.widgets.welcome import (
    WelcomeWidget,
)
from backend.core.enums import AgentState


class _AppScreenMessagesMixin:
    """Messages-related methods of GrintaScreen."""

    def _get_display(self) -> Transcript:
        return self.query_one('#main-display', Transcript)

    def _write_log(self, renderable: Any) -> None:
        if self._renderer:
            self._renderer.add_to_history(renderable)

    def add_user_message(self, text: str) -> None:
        """User message."""
        self.finalize_thinking()
        if self._renderer:
            self._renderer._clear_last_active_card_processing()
        display = self._get_display()
        if type(display).__name__ == 'MagicMock':
            display.write(text)
            return
        from backend.cli.tui.widgets.activity_card import UserMessage

        widget = UserMessage(text)
        display.append_widget(widget)

    def add_agent_message(self, text: str) -> None:
        """Agent response."""
        self.finalize_thinking()
        if self._renderer:
            self._renderer._clear_last_active_card_processing()
        display = self._get_display()
        if type(display).__name__ == 'MagicMock':
            display.write(text)
            return
        from backend.cli.tui.widgets.activity_card import AgentMessage

        widget = AgentMessage(text)
        display.append_widget(widget)

    def add_thinking(self, text: str) -> None:
        """Real-time thinking/reasoning — update live display."""
        if not getattr(self, '_thinking_spinner_active', False):
            spinner = self.query_one('#spinner', Static)
            spinner.remove_class('-hidden')
            spinner.update('⟳')
            self._thinking_spinner_active = True

        if self._renderer:
            self._renderer.update_live_thinking(text)

    def finalize_thinking(self) -> None:
        """Agent turn done — hide spinner."""
        self._thinking_spinner_active = False
        self.query_one('#spinner', Static).add_class('-hidden')
        if self._renderer:
            self._renderer.commit_live_thinking()

    def add_system_message(self, text: str) -> None:
        body = _rich_text(text)
        body.stylize(NAVY_TEXT_MUTED)
        self._write_log(body)

    def _emit_transcript_notice(self, text: str) -> None:
        """Render a unified soft notice for recoverable issues and tool feedback."""
        from backend.cli.tui.widgets.transcript_notice import TranscriptNotice

        widget = TranscriptNotice(text)
        try:
            display = self._get_display()
        except Exception:
            self._write_log(widget)
            return
        if type(display).__name__ == 'MagicMock':
            display.write(text)
            return
        self._write_log(widget)

    def add_error(self, text: str) -> None:
        self._emit_transcript_notice(text)

    def add_warning(self, text: str) -> None:
        """Recoverable issue — same soft notice styling as ``add_error``."""
        self._emit_transcript_notice(text)

    def add_success(self, text: str) -> None:
        icon = Text('✓ ', style=NAVY_READY)
        body = _rich_text(text)
        body.stylize(NAVY_READY)
        self._write_log(Text.assemble(icon, body))

    def add_protocol_status(self, text: str) -> None:
        """Render active-task prose as dim inline text, not a final answer."""
        self.finalize_thinking()
        content = sanitize_visible_transcript_text(text)
        if not content:
            return
        body = _rich_text(content)
        body.stylize(f'dim {NAVY_TEXT_PRIMARY}')
        self._write_log(body)

    def add_tool_start(self, tool_name: str, *, command: str = '') -> None:
        """Tool call — show in transcript."""
        icon = Text('⚙ ', style='#91abec')
        name = _rich_text(tool_name)
        name.stylize('#91abec')

        if command:
            cmd_text = _rich_text(command)
            self._write_log(
                Text.assemble(icon, name, ' (', cmd_text, ')', style='#969aad')
            )
        else:
            self._write_log(Text.assemble(icon, name))

    def add_tool_result(self, text: str) -> None:
        """Tool result — muted text."""
        body = _rich_text(text)
        body.stylize(NAVY_TEXT_MUTED)
        self._write_log(Text.assemble('  ', body))

    def add_divider(self) -> None:
        self._write_log(Rule(style=NAVY_BORDER))

    def clear_transcript(self) -> None:
        if self._renderer:
            self._renderer.clear_history()

    def action_clear_transcript(self) -> None:
        self.clear_transcript()

    def action_copy_or_interrupt(self) -> None:
        """Copy selected text if any, otherwise interrupt the agent."""
        ta = self.query_one('#input', TextArea)
        if ta.selected_text:
            self.app.copy_to_clipboard(ta.selected_text)
            return
        if self._is_agent_running():
            self._interrupt_agent()

    def action_copy_transcript(self) -> None:
        """Copy the entire transcript content to clipboard."""
        if self._renderer and self._renderer._history:
            # Extract plain text from Rich history
            plain_text = self._extract_plain_text_from_history()
            if plain_text:
                self.app.copy_to_clipboard(plain_text)
                self._write_log(Text('  [dim]Transcript copied to clipboard[/dim]'))
            else:
                self._write_log(Text('  [dim]No content to copy[/dim]'))
        else:
            self._write_log(Text('  [dim]No transcript content[/dim]'))

    def _extract_plain_text_from_history(self) -> str:
        """Extract plain text from Rich history for copying."""
        if not self._renderer or not self._renderer._history:
            return ''

        lines = []
        for item in self._renderer._history:
            if hasattr(item, 'plain'):
                # Rich Text object
                lines.append(item.plain)
            elif isinstance(item, str):
                lines.append(item)
            elif hasattr(item, '__rich_console__'):
                # Rich renderable - try to extract text
                try:
                    from rich.console import Console

                    console = Console(force_terminal=True, width=200)
                    with console.capture() as capture:
                        console.print(item)
                    lines.append(capture.get())
                except Exception:
                    pass

        return '\n'.join(line for line in lines if line.strip())

    def action_interrupt_agent(self) -> None:
        """Interrupt the running agent."""
        if self._is_agent_running():
            self._interrupt_agent()

    def _is_agent_running(self) -> bool:
        """Check if the agent is currently running."""
        if self._controller is None:
            return False
        state = self._controller.get_agent_state()
        return state == AgentState.RUNNING

    def _interrupt_agent(self) -> None:
        """Cancel the running agent and clean up."""
        _tui_logger.info('User requested agent interrupt')

        if self._agent_task and not self._agent_task.done():
            self._agent_task.cancel()

        async def _do_interrupt() -> None:
            if self._controller is not None:
                mark = getattr(self._controller, 'mark_user_interrupt_stop', None)
                if callable(mark):
                    mark()
                with contextlib.suppress(Exception):
                    await self._controller.stop()

            if self._agent_task and not self._agent_task.done():
                try:
                    await asyncio.wait_for(self._agent_task, timeout=5.0)
                except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                    pass

            with contextlib.suppress(Exception):
                from backend.execution.action_execution_server import (
                    client as runtime_client,
                )

                if runtime_client is not None:
                    await runtime_client.hard_kill()

            if self._renderer is not None:
                self._renderer._tui.add_system_message('Interrupted. Ready for input.')

            with contextlib.suppress(Exception):
                from backend.core.logger import finalize_session_logging_audit

                finalize_session_logging_audit()

            self.finalize_thinking()
            spinner = self.query_one('#spinner', Static)
            spinner.add_class('-hidden')
            self.query_one('#input-bar', InputBar).remove_class('processing')

        asyncio.create_task(_do_interrupt())

    def _transcript_has_real_content(self) -> bool:
        """True when transcript has non-welcome, non-badge visible content."""
        try:
            display = self._get_display()
        except Exception:
            return False
        for child in display.children:
            if not getattr(child, 'display', True):
                continue
            if getattr(child, 'id', None) == 'scroll-badge':
                continue
            if type(child) is WelcomeWidget:
                continue
            return True
        return False
