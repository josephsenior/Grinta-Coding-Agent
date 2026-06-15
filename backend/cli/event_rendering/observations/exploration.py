"""Observation renderers — exploration domain."""

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

class _ObsExplorationMixin(_ObservationRenderersBase):
    def _render_lsp_query_observation(self, obs: LspQueryObservation) -> None:
        self._stop_reasoning()
        pending = getattr(self, '_pending_orient_line', None)
        pending_model = pending if isinstance(pending, OrientLineModel) else None
        if pending_model is not None and pending_model.tool == 'lsp':
            self._pending_orient_line = None
        else:
            pending_model = None
        self._append_orient_line(lsp_observation_model(obs, pending_model))

    @staticmethod
    def _orient_lsp_result(*, available: bool, content: str) -> str | None:
        if not available:
            return 'unavailable'
        if not content.strip():
            return None
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError, ValueError):
            data = None
        if isinstance(data, dict):
            # definitions/references → N results
            for key in ('definitions', 'references'):
                items = data.get(key)
                if isinstance(items, list):
                    count = len(items)
                    if count == 0:
                        return None
                    noun = key.rstrip('s')
                    return f'{count} {noun}{"s" if count != 1 else ""}'
            # hover → completed
            if 'hover' in data or 'contents' in data:
                return 'completed'
            # list_symbols → N symbols
            symbols = data.get('symbols') or data.get('symbol_list')
            if isinstance(symbols, list):
                return f'{len(symbols)} symbols'
            # diagnostics → N issues / clean
            diagnostics = data.get('diagnostics') or data.get('issues')
            if isinstance(diagnostics, list):
                count = len(diagnostics)
                if count == 0:
                    return 'clean'
                return f'{count} issue{"s" if count != 1 else ""}'
            # code_action → N actions
            actions = data.get('actions')
            if isinstance(actions, list):
                return f'{len(actions)} actions'
        if isinstance(data, list):
            return f'{len(data)} results'
        lines = [line for line in content.split('\n') if line.strip()]
        if not lines:
            return None
        return f'{len(lines)} results'

    def _render_grep_observation(self, obs: GrepObservation) -> None:
        self._stop_reasoning()
        self._complete_or_append_orient('grep', grep_observation_model(obs))

    @staticmethod
    def _orient_grep_result(
        *,
        query: str,
        content: str,
        match_count: int,
        file_count: int,
        output_mode: str,
        error: str | None,
    ) -> str | None:
        if error:
            return f'failed · {error[:60]}'
        if output_mode == 'files_with_matches':
            if file_count == 0:
                return 'no matches'
            return f'{file_count} file{"s" if file_count != 1 else ""}'
        if output_mode == 'count':
            if match_count == 0:
                return 'no matches'
            return f'{match_count} match{"es" if match_count != 1 else ""}'
        if output_mode == 'content':
            if match_count == 0 and file_count == 0:
                return 'no matches'
            if file_count:
                return f'{match_count} match{"es" if match_count != 1 else ""} · {file_count} file{"s" if file_count != 1 else ""}'
            return f'{match_count} match{"es" if match_count != 1 else ""}'
        # Default
        if match_count == 0 and file_count == 0:
            return 'no matches'
        if file_count:
            return f'{file_count} file{"s" if file_count != 1 else ""}'
        return f'{match_count} match{"es" if match_count != 1 else ""}'

    def _render_glob_observation(self, obs: GlobObservation) -> None:
        self._stop_reasoning()
        self._complete_or_append_orient('glob', glob_observation_model(obs))

    @staticmethod
    def _orient_glob_result(
        *,
        content: str,
        file_count: int,
        error: str | None,
    ) -> str | None:
        if error:
            return f'failed · {error[:60]}'
        if file_count == 0:
            return 'no files'
        return f'{file_count} file{"s" if file_count != 1 else ""}'

    def _render_find_symbols_observation(self, obs: FindSymbolsObservation) -> None:
        self._stop_reasoning()
        self._complete_or_append_orient(
            'find_symbols',
            find_symbols_observation_model(obs),
        )

    @staticmethod
    def _orient_find_symbols_result(
        *,
        candidates: list[Any],
        error: str | None,
    ) -> str | None:
        if error:
            return f'failed · {error[:60]}'
        symbol_count = len(candidates)
        file_count = len({
            str(item.get('path') or '')
            for item in candidates
            if item.get('path')
        })
        if symbol_count == 0:
            return 'no symbols'
        if file_count <= 1:
            return f'{symbol_count} symbol{"s" if symbol_count != 1 else ""}'
        return f'{symbol_count} symbol{"s" if symbol_count != 1 else ""} · {file_count} file{"s" if file_count != 1 else ""}'

    def _render_read_symbols_observation(self, obs: ReadSymbolsObservation) -> None:
        self._stop_reasoning()
        self._complete_or_append_orient(
            'read_symbols',
            read_symbols_observation_model(obs),
        )

    def _render_analyze_project_structure_observation(
        self, obs: AnalyzeProjectStructureObservation
    ) -> None:
        self._stop_reasoning()
        self._complete_or_append_orient(
            'analyze_project_structure',
            analyze_observation_model(obs),
        )

    def _complete_or_append_orient(
        self,
        expected_tool: str,
        fallback: OrientLineModel,
    ) -> None:
        pending = getattr(self, '_pending_orient_line', None)
        if isinstance(pending, OrientLineModel) and pending.tool == expected_tool:
            self._pending_orient_line = None
            self._append_orient_line(pending.with_result(fallback.result))
            return
        self._append_orient_line(fallback)

    @staticmethod
    def _orient_read_symbols_result(*, available: bool, content: str) -> str | None:
        if not available:
            return 'unavailable'
        if not content.strip():
            return None
        # Parse summary from content
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        if not lines:
            return None
        # Try to count resolved vs ambiguous vs not_found
        resolved = sum(1 for line in lines if line.startswith('resolved') or '->' in line)
        ambiguous = sum(1 for line in lines if line.startswith('ambiguous') or '~>' in line)
        not_found = sum(1 for line in lines if line.startswith('not found') or line.startswith('not_found'))
        total = resolved + ambiguous + not_found
        if total == 0:
            return None
        parts = []
        if resolved:
            parts.append(f'{resolved} resolved')
        if ambiguous:
            parts.append(f'{ambiguous} ambiguous')
        if not_found:
            parts.append(f'{not_found} not found')
        return ' · '.join(parts) if parts else None

    @staticmethod
    def _orient_analyze_result(*, available: bool, content: str) -> str | None:
        if not available:
            return 'unavailable'
        if not content.strip():
            return 'no output'
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        if not lines:
            return None
        # Extract metric based on common payload patterns
        body = '\n'.join(lines[:20])
        body_lower = body.lower()
        if 'callers' in body_lower or 'caller of' in body_lower:
            # Count callers
            caller_lines = [line for line in lines if '::' in line or ' -> ' in line or '  ' in line and '(' in line and ')' in line]
            return f'{len(caller_lines)} callers' if caller_lines else 'completed'
        if 'dependency' in body_lower or 'depend on' in body_lower or 'import' in body_lower:
            dep_count = sum(1 for line in lines if line.strip() and ('<-' in line or '->' in line or 'import' in line.lower()))
            return f'{dep_count} deps' if dep_count else 'completed'
        if 'symbol' in body_lower:
            symbol_lines = [line for line in lines if line.strip() and not line.startswith('#') and not line.startswith('//')]
            return f'{len(symbol_lines)} symbols' if symbol_lines else 'completed'
        if 'tree' in body_lower or 'file_outline' in body_lower or 'recent' in body_lower:
            return 'completed'
        if 'semantic_search' in body_lower:
            return 'completed'
        return 'completed'

