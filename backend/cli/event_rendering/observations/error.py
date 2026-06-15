"""Observation renderers — error domain."""

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

_SUPPRESS_FROM_HISTORY_CATEGORIES: frozenset[str] = frozenset(
    {
        ERROR_CATEGORY_TIMEOUT,
        ERROR_CATEGORY_NETWORK,
        ERROR_CATEGORY_RATE_LIMIT,
    }
)


class _ObsErrorMixin(_ObservationRenderersBase):
    def _render_error_observation(self, obs: ErrorObservation) -> None:
        if getattr(obs, 'agent_only', False):
            return
        # Skip transient provider/network/timeout notices from history — the
        # HUD bar already reflects the agent state (Backoff/Rate Limited/etc.)
        # and these panels pollute the transcript with redundant information.
        error_category = getattr(obs, 'error_category', None)
        if error_category in _SUPPRESS_FROM_HISTORY_CATEGORIES:
            return
        # notify_ui_only errors are user-facing toasts only — they should not
        # appear in the transcript history either.
        if getattr(obs, 'notify_ui_only', False):
            return
        self._stop_reasoning()
        self._flush_pending_tool_cards()
        self._clear_streaming_preview()
        error_content = getattr(obs, 'content', str(obs))
        # Use the structured category set by RecoveryService at the exception
        # site — no text matching needed for typed provider/runtime errors.
        use_notice = _use_recoverable_notice_style(
            error_content, error_category=error_category
        )
        if use_notice:
            last_notice_content = getattr(self, '_last_notice_error_content', None)
            if (
                isinstance(last_notice_content, str)
                and last_notice_content == error_content
            ):
                return
            setattr(self, '_last_notice_error_content', error_content)
        else:
            setattr(self, '_last_notice_error_content', None)
        self._append_history(
            _build_error_panel(
                error_content,
                force_notice=use_notice,
                error_category=error_category,
                content_width=self._console.width,
            ),
        )
        # Do not force HUD to Ready/Idle for recoverable notices — the agent
        # may still be RUNNING (e.g. before RecoveryService transitions
        # state).  Ledger HUD is driven by AgentStateChangedObservation.
        if not use_notice:
            self._hud.update_ledger('Error')

    def _render_user_reject_observation(self, obs: UserRejectObservation) -> None:
        self._flush_pending_tool_cards()
        content = getattr(obs, 'content', '')
        self._append_history(
            format_callout_panel(
                'Rejected',
                Text(content or 'Action rejected.', style=CLR_QUESTION_TEXT),
                accent_style=CLR_STATUS_WARN,
            )
        )

    def _render_recall_observation(self, obs: RecallObservation) -> None:
        self._flush_pending_tool_cards()
        recall_type = getattr(obs, 'recall_type', None)
        label = str(recall_type.value) if recall_type else 'context'
        # Next agent step calls the LLM — show activity indicator.
        self._ensure_reasoning()
        self._reasoning.update_action(f'Recalled {label}…')
        self.refresh()

