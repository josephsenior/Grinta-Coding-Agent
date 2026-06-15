"""Observation renderers — file domain."""

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

class _ObsFileMixin(_ObservationRenderersBase):
    def _render_file_edit_observation(self, obs: FileEditObservation) -> None:
        self._stop_reasoning()
        from backend.cli.display.diff_renderer import DiffPanel
        from backend.cli.display.transcript import strip_indentation_warnings

        # Strip agent-facing indentation warnings from user-visible content
        if hasattr(obs, 'content') and obs.content:
            obs.content = strip_indentation_warnings(obs.content)

        path = getattr(obs, 'path', '')
        pending = cast(Any, self._take_pending_activity_card('file_edit'))
        self._emit_activity_turn_header()
        self._print_or_buffer(
            Padding(
                DiffPanel(
                    obs,
                    verb=pending.verb if pending else None,
                    detail=pending.detail if pending else path,
                    secondary=pending.secondary if pending else None,
                    title=pending.title if pending else None,
                    badge_label=pending.badge_label if pending else 'file_edit',
                ),
                pad=ACTIVITY_BLOCK_BOTTOM_PAD,
            )
        )

    def _render_file_write_observation(self, obs: FileWriteObservation) -> None:
        del obs
        self._stop_reasoning()
        pending = cast(Any, self._take_pending_activity_card('file_write'))
        line_count = 0
        if pending and pending.payload:
            raw_line_count = pending.payload.get('line_count', 0)
            if isinstance(raw_line_count, int):
                line_count = raw_line_count
        delta = format_activity_delta_secondary(added=line_count)
        extra_lines: list[Any] = []
        if delta is not None:
            extra_lines.append(delta)
        if pending is not None:
            self._render_pending_activity_card(pending, extra_lines=extra_lines)

    def _render_file_read_observation(self, obs: FileReadObservation) -> None:
        self._stop_reasoning()
        pending = getattr(self, '_pending_orient_line', None)
        if pending is not None and getattr(pending, 'tool', '') == 'read_file':
            self._pending_orient_line = None
            self._append_orient_line(pending)
            return
        self._append_orient_line(file_read_observation_model(obs))

    @staticmethod
    def _file_read_result_message(content: str, n_lines: int) -> str:
        return ''

