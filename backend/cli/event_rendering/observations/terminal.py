"""Observation renderers — terminal domain."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

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

from backend.cli.event_rendering.constants import (
    BROWSER_TOOL_COMMANDS as _BROWSER_TOOL_COMMANDS,
)
from backend.cli.event_rendering.delegate import (
    summarize_delegate_observation as _summarize_delegate_observation,
)
from backend.cli.event_rendering.error_panel import (
    build_error_panel as _build_error_panel,
)
from backend.cli.event_rendering.error_panel import (
    build_llm_stream_fallback_panel as _build_llm_stream_fallback_panel,
)
from backend.cli.event_rendering.error_panel import (
    use_recoverable_notice_style as _use_recoverable_notice_style,
)
from backend.cli.event_rendering.text_utils import (
    sanitize_visible_transcript_text as _sanitize_visible_transcript_text,
)
from backend.cli.event_rendering.text_utils import (
    strip_pty_echo as _strip_pty_echo,
)
from backend.cli.event_rendering.text_utils import (
    summarize_cmd_failure as _summarize_cmd_failure,
)
from backend.cli._typing import ObservationRenderersHost
from backend.cli.layout_tokens import ACTIVITY_BLOCK_BOTTOM_PAD
from backend.cli.orient_tools import (
    ORIENT_MCP_TOOL_NAMES,
    OrientLineModel,
    analyze_observation_model,
    file_read_observation_model,
    find_symbols_observation_model,
    glob_observation_model,
    grep_observation_model,
    lsp_observation_model,
    mcp_observation_model,
    read_symbols_observation_model,
)
from backend.cli.theme import (
    CLR_OUTPUT_PANEL_BORDER,
    CLR_OUTPUT_PANEL_TITLE,
    CLR_QUESTION_TEXT,
    CLR_STATUS_WARN,
    NAVY_BG,
    get_grinta_pygments_style,
)
from backend.cli.display.tool_call_display import (
    mcp_result_syntax_extras,
    mcp_result_user_preview,
)
from backend.cli.display.transcript import (
    format_activity_delta_secondary,
    format_activity_result_secondary,
    format_activity_shell_block,
    format_callout_panel,
    strip_tool_result_validation_annotations,
)
from backend.cli.event_rendering.observations.shell_helpers import _terminal_output_lexer
from backend.ledger.observation import (
    AgentCondensationObservation,
    AgentStateChangedObservation,
    AgentThinkObservation,
    AnalyzeProjectStructureObservation,
    BrowserScreenshotObservation,
    CmdOutputObservation,
    DelegateTaskObservation,
    ErrorObservation,
    FileDownloadObservation,
    FileEditObservation,
    FileReadObservation,
    FileWriteObservation,
    FindSymbolsObservation,
    GlobObservation,
    GrepObservation,
    LspQueryObservation,
    MCPObservation,
    Observation,
    ReadSymbolsObservation,
    RecallFailureObservation,
    RecallObservation,
    ServerReadyObservation,
    StatusObservation,
    SuccessObservation,
    TaskTrackingObservation,
    TerminalObservation,
    UserRejectObservation,
)
from backend.ledger.observation.error import (
    ERROR_CATEGORY_NETWORK,
    ERROR_CATEGORY_RATE_LIMIT,
    ERROR_CATEGORY_TIMEOUT,
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

