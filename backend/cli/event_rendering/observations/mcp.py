"""Observation renderers — mcp domain."""

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

class _ObsMcpMixin(_ObservationRenderersBase):
    def _render_mcp_observation(self, obs: MCPObservation) -> None:
        self._stop_reasoning()
        content = getattr(obs, 'content', '')
        name = getattr(obs, 'name', '')
        if name in ORIENT_MCP_TOOL_NAMES:
            pending = getattr(self, '_pending_orient_line', None)
            pending_model = pending if isinstance(pending, OrientLineModel) else None
            model = mcp_observation_model(obs, pending_model)
            if model is not None:
                self._pending_orient_line = None
                self._append_orient_line(model)
            return
        friendly = mcp_result_user_preview(content)
        extras = mcp_result_syntax_extras(content)
        pending = cast(Any, self._take_pending_activity_card('mcp'))
        if pending is not None:
            self._render_pending_activity_card(
                pending,
                result_message=friendly or None,
                result_kind='neutral',
                extra_lines=extras,
            )
        elif friendly:
            self._append_history(
                format_activity_result_secondary(friendly, kind='neutral')
            )

    @staticmethod
    def _orient_mcp_result(name: str, content: str) -> str | None:
        """Extract result metric from orient MCP tool responses."""
        s = (content or '').strip()
        if not s:
            return None
        try:
            data = json.loads(s)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
        if isinstance(data, dict):
            # Check for error payload
            error = data.get('error') or data.get('isError')
            if error:
                return 'failed'
            # Try to extract count from various payload shapes
            for key in ('total_count', 'count', 'matches', 'total'):
                v = data.get(key)
                if isinstance(v, int):
                    if v == 0:
                        return 'no results' if name in ('web_search',) else 'no results'
                    return f'{v} results'
            # Check items/results array
            for key in ('items', 'results', 'entries', 'documents', 'content'):
                items = data.get(key)
                if isinstance(items, list):
                    count = len(items)
                    if count == 0:
                        return 'no results'
                    return f'{count} results'
        if isinstance(data, list):
            count = len(data)
            if count == 0:
                return 'no results'
            return f'{count} results'
        return None

