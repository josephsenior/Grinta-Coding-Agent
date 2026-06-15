"""Observation renderers — misc domain."""

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

class _ObsMiscMixin(_ObservationRenderersBase):
    def _render_server_ready_observation(self, obs: ServerReadyObservation) -> None:
        self._flush_pending_tool_cards()
        url = getattr(obs, 'url', '')
        port = getattr(obs, 'port', '')
        label = url or f'port {port}'
        self._append_history(
            format_activity_result_secondary(
                f'server ready · {label}',
                kind='ok',
            ),
        )

    def _render_success_observation(self, obs: SuccessObservation) -> None:
        self._flush_pending_tool_cards()
        content = getattr(obs, 'content', '')
        if content:
            self._append_history(
                format_activity_result_secondary(content, kind='ok'),
            )

    def _render_recall_failure_observation(
        self,
        obs: RecallFailureObservation,
    ) -> None:
        self._flush_pending_tool_cards()
        error_msg = getattr(obs, 'error_message', '')
        recall_type = getattr(obs, 'recall_type', None)
        label = str(recall_type.value) if recall_type else 'recall'
        if error_msg:
            self._append_history(
                format_activity_result_secondary(
                    f'{label} failed · {error_msg}',
                    kind='err',
                )
            )

    def _render_file_download_observation(
        self,
        obs: FileDownloadObservation,
    ) -> None:
        self._flush_pending_tool_cards()
        path = getattr(obs, 'file_path', '')
        self._append_history(
            format_activity_result_secondary(
                f'downloaded · {path}',
                kind='neutral',
            ),
        )

    def _render_delegate_task_observation(
        self,
        obs: DelegateTaskObservation,
    ) -> None:
        self._stop_reasoning()
        pending = cast(Any, self._take_pending_activity_card('delegate'))
        workers_data = getattr(self, '_delegate_workers', {}) or {}
        result_message, result_kind, extra_lines = _summarize_delegate_observation(
            obs,
            workers_data=workers_data,
        )
        if pending is not None:
            self._render_pending_activity_card(
                pending,
                result_message=result_message,
                result_kind=result_kind,
                extra_lines=extra_lines,
            )
            return
        if result_message is not None:
            self._append_history(
                format_activity_result_secondary(result_message, kind=result_kind),
            )
        for line in extra_lines:
            self._append_history(line)

    def _render_task_tracking_observation(
        self,
        obs: TaskTrackingObservation,
    ) -> None:
        task_list = getattr(obs, 'task_list', None)
        cmd = getattr(obs, 'command', '')
        if task_list is not None and cmd == 'update':
            self._set_task_panel(task_list)
        content = _sanitize_visible_transcript_text(
            strip_tool_result_validation_annotations(
                (getattr(obs, 'content', None) or '').strip()
            )
        )
        body = '' if (task_list is not None and cmd == 'update') else content
        if body:
            for line in body.splitlines():
                self._append_history(
                    format_activity_result_secondary(line, kind='neutral')
                )
        self.refresh()

    def _render_agent_condensation_observation(
        self,
        obs: AgentCondensationObservation,
    ) -> None:
        del obs
