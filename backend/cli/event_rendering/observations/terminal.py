"""Observation renderers — terminal domain."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.cli._typing import ObservationRenderersHost

    _ObservationRenderersBase = ObservationRenderersHost
else:
    _ObservationRenderersBase = object

from rich import box
from rich.padding import Padding
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from backend.cli._typing import ObservationRenderersHost
from backend.cli.display.transcript import (
    strip_tool_result_validation_annotations,
)
from backend.cli.event_rendering.observations.shell_helpers import (
    _terminal_output_lexer,
)
from backend.cli.event_rendering.text_utils import (
    strip_pty_echo as _strip_pty_echo,
)
from backend.cli.display.layout_tokens import ACTIVITY_BLOCK_BOTTOM_PAD
from backend.cli.theme import (
    CLR_OUTPUT_PANEL_BORDER,
    CLR_OUTPUT_PANEL_TITLE,
    NAVY_BG,
    get_grinta_pygments_style,
)
from backend.ledger.observation import (
    TerminalObservation,
)

logger = logging.getLogger(__name__)


class _ObsTerminalMixin(_ObservationRenderersBase):
    def _render_terminal_observation(self, obs: TerminalObservation) -> None:
        raw = getattr(obs, 'content', '') or ''
        display = strip_tool_result_validation_annotations(raw)
        content = display.strip()
        # Strip ANSI escape sequences from PTY/interactive terminal output
        if content:
            content = Text.from_ansi(content).plain
        has_new = getattr(obs, 'has_new_output', None)
        # Suppress entirely when there's nothing new — these are just polling
        # reads and the "no new text" caption is noise for the human user.
        if has_new is False and not content:
            self._last_terminal_input_sent = ''
            return
        self._stop_reasoning()
        self._flush_pending_tool_cards()
        # Strip PTY character-echo lines produced when the agent injects input.
        content = self._strip_pty_echo_if_pending(content)
        if not content and not raw.strip():
            return
        if content:
            self._render_terminal_panel(body=content)
            return

    def _strip_pty_echo_if_pending(self, content: str) -> str:
        if content and self._last_terminal_input_sent:
            content = _strip_pty_echo(content, self._last_terminal_input_sent)
            self._last_terminal_input_sent = ''
        return content

    TERMINAL_LINE_LIMIT = 12

    def _render_terminal_panel(self, *, body: str) -> None:
        lines = body.splitlines()
        if len(lines) > self.TERMINAL_LINE_LIMIT:
            body = '\n'.join(lines[: self.TERMINAL_LINE_LIMIT])
        panel_title = Text('$ ', style=CLR_OUTPUT_PANEL_TITLE)
        self._append_history(
            Padding(
                Panel(
                    Syntax(
                        body,
                        _terminal_output_lexer(body),
                        word_wrap=True,
                        theme=get_grinta_pygments_style(),
                        background_color=NAVY_BG,
                    ),
                    title=panel_title,
                    title_align='left',
                    border_style=CLR_OUTPUT_PANEL_BORDER,
                    box=box.ROUNDED,
                    padding=(0, 1),
                ),
                pad=ACTIVITY_BLOCK_BOTTOM_PAD,
            )
        )
