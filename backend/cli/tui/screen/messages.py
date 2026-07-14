from __future__ import annotations

import asyncio
import contextlib
import re
from typing import Any

from rich.markup import escape as rich_escape
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


class ScreenMessagesMixin:
    """Messages-related methods of GrintaScreen."""

    def _get_display(self) -> Transcript:
        return self.query_one('#main-display', Transcript)

    def _write_log(self, renderable: Any) -> None:
        if self._renderer:
            self._renderer.add_to_history(renderable)

    def add_user_message(self, text: str, *, image_count: int = 0) -> None:
        """User message."""
        self.finalize_thinking()
        display = self._get_display()
        if type(display).__name__ == 'MagicMock':
            display.write(text)
            return
        from backend.cli.tui.widgets.activity_card import UserMessage

        widget = UserMessage(text, image_count=image_count)
        display.append_widget(widget)

    def _remove_last_user_message_widget(self) -> bool:
        """Drop the most recent user bubble when a turn aborts before the agent runs."""
        try:
            display = self._get_display()
        except Exception:
            return False
        if type(display).__name__ == 'MagicMock':
            return False
        from backend.cli.tui.widgets.activity_card.message_widgets import UserMessage

        for child in reversed(list(display.children)):
            if isinstance(child, UserMessage):
                child.remove()
                return True
        return False

    def add_agent_message(self, text: str) -> None:
        """Agent response."""
        self.finalize_thinking()
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
        """Render a system-level message using the unified soft-notice chrome.

        This gives system messages the same visual treatment as
        :meth:`_emit_transcript_notice` so the feed reads consistently.
        Toasts (which are ephemeral popups) remain separate — they're
        the right surface for transient feedback that doesn't belong in
        the transcript history.
        """
        self._emit_transcript_notice(text)

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

    def _emit_error_block(self, renderable: Any) -> None:
        """Render an inline error block matching thinking/exploration chrome."""
        from backend.cli.tui.widgets.error_block import ErrorBlock

        widget = ErrorBlock(renderable)
        try:
            display = self._get_display()
        except Exception:
            self._write_log(widget)
            return
        if type(display).__name__ == 'MagicMock':
            display.write(renderable)
            return
        self._write_log(widget)

    def add_error(self, text: str) -> None:
        from backend.cli.event_rendering.text_utils import (
            sanitize_visible_transcript_text,
        )
        from backend.cli.tui.widgets.error_block import ErrorBlock

        content = sanitize_visible_transcript_text(text)
        if not content:
            return
        self._emit_error_block(ErrorBlock.simple_message(content))

    def add_warning(self, text: str) -> None:
        """Recoverable issue — same soft notice styling as before."""
        self._emit_transcript_notice(text)

    def add_error_panel(
        self,
        text: str,
        *,
        error_category: str | None = None,
    ) -> None:
        """Render a persistent structured error block for context-bearing failures."""
        from backend.cli.event_rendering.error_panel import build_error_tui_renderable

        width = getattr(getattr(self, 'size', None), 'width', None)
        self._emit_error_block(
            build_error_tui_renderable(
                text,
                title='Error',
                error_category=error_category,
                content_width=width,
            )
        )

    def _notify_user(
        self,
        text: str,
        *,
        severity: str = 'information',
        timeout: float = 3.5,
    ) -> None:
        message = re.sub(r'\s+', ' ', str(text or '').strip())
        if not message:
            return
        if len(message) > 260:
            message = message[:257] + '...'
        notify = getattr(self, 'notify', None)
        if callable(notify):
            notify(rich_escape(message), severity=severity, timeout=timeout)
            return
        self._emit_transcript_notice(rich_escape(message))

    def notify_error(self, text: str, *, timeout: float = 4.5) -> None:
        self._notify_user(text, severity='error', timeout=timeout)

    def notify_warning(self, text: str, *, timeout: float = 3.5) -> None:
        self._notify_user(text, severity='warning', timeout=timeout)

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
            session_id = self._active_interactive_terminal_session_id()
            if session_id is not None:
                asyncio.create_task(self._forward_terminal_control(session_id, 'C-c'))
                return
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

    def _active_interactive_terminal_session_id(self) -> str | None:
        """Return the most recent PTY session awaiting interaction, if any."""
        runtime = getattr(self, '_runtime_stub', None)
        executor = getattr(runtime, '_executor', None)
        if executor is None:
            return None
        pending = getattr(executor, '_terminal_sessions_awaiting_interaction', None)
        if not isinstance(pending, list) or not pending:
            return None
        session_id = str(pending[-1]).strip()
        return session_id or None

    async def _forward_terminal_control(self, session_id: str, control: str) -> None:
        """Send a control sequence to an interactive terminal session."""
        runtime = getattr(self, '_runtime_stub', None)
        if runtime is None:
            return
        terminal_input = getattr(runtime, 'terminal_input', None)
        if not callable(terminal_input):
            return
        from backend.ledger.action.terminal import TerminalInputAction

        try:
            await asyncio.to_thread(
                terminal_input,
                TerminalInputAction(session_id=session_id, control=control),
            )
        except Exception:
            _tui_logger.debug(
                'Failed to forward %s to terminal %s',
                control,
                session_id,
                exc_info=True,
            )

    def _interrupt_agent(self) -> None:
        """Cancel the running agent and clean up."""
        _tui_logger.info('User requested agent interrupt')

        active_interrupt = getattr(self, '_interrupt_task', None)
        if active_interrupt is not None and not active_interrupt.done():
            return

        # Update the TUI immediately; cleanup may take seconds on WSL / slow disks.
        self.finalize_thinking()
        with contextlib.suppress(Exception):
            spinner = self.query_one('#spinner', Static)
            spinner.add_class('-hidden')
        if getattr(self, '_hud', None) is not None:
            self._finalize_turn_duration()
            self._hud.update_agent_state('Stopping')
            with contextlib.suppress(Exception):
                self._render_hud_bar()

        async def _do_interrupt() -> None:
            controller = self._controller
            agent_task = self._agent_task
            if controller is not None:
                mark = getattr(controller, 'mark_user_interrupt_stop', None)
                if callable(mark):
                    with contextlib.suppress(Exception):
                        mark()
                try:
                    await asyncio.wait_for(controller.stop(), timeout=10.0)
                except Exception:
                    _tui_logger.exception('Controller stop failed during user interrupt')

            # The poller should observe STOPPED and return.  Only cancel it after
            # backend shutdown has been requested; cancelling it first can leave
            # the in-flight LLM step detached and still writing session events.
            if agent_task and not agent_task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(agent_task), timeout=2.0)
                except asyncio.TimeoutError:
                    agent_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await agent_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    _tui_logger.exception('Agent poller failed while stopping')

            with contextlib.suppress(Exception):
                from backend.execution.server.action_execution_server import (
                    client as runtime_client,
                )

                if runtime_client is not None:
                    await runtime_client.hard_kill()

            if controller is not None:
                with contextlib.suppress(Exception):
                    if controller.get_agent_state() != AgentState.STOPPED:
                        await controller.set_agent_state_to(AgentState.STOPPED)

            with contextlib.suppress(Exception):
                from backend.core.logging.logger import finalize_session_logging_audit

                finalize_session_logging_audit()

            if getattr(self, '_hud', None) is not None:
                self._hud.update_agent_state('Ready')
                with contextlib.suppress(Exception):
                    self._render_hud_bar()
            with contextlib.suppress(Exception):
                self.query_one('#input-bar', InputBar).remove_class('processing')

        self._interrupt_task = asyncio.create_task(
            _do_interrupt(), name='grinta-tui-interrupt'
        )

        def _interrupt_done(task: asyncio.Task[Any]) -> None:
            if getattr(self, '_interrupt_task', None) is task:
                self._interrupt_task = None
            if task.cancelled():
                _tui_logger.warning('User interrupt cleanup task was cancelled')
                return
            if exc := task.exception():
                _tui_logger.error('User interrupt cleanup failed: %s', exc)

        self._interrupt_task.add_done_callback(_interrupt_done)

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
