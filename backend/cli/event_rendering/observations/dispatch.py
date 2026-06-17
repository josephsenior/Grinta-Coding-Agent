"""Observation renderers — dispatch domain."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.cli._typing import ObservationRenderersHost

    _ObservationRenderersBase = ObservationRenderersHost
else:
    _ObservationRenderersBase = object


from backend.cli._typing import ObservationRenderersHost
from backend.ledger.observation import (
    AgentCondensationObservation,
    AgentStateChangedObservation,
    AgentThinkObservation,
    AnalyzeProjectStructureObservation,
    BrowserScreenshotObservation,
    CmdOutputObservation,
    DebuggerObservation,
    DelegateTaskObservation,
    ErrorObservation,
    FileDownloadObservation,
    FileEditObservation,
    FileReadObservation,
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

logger = logging.getLogger(__name__)


class _ObsDispatchMixin(_ObservationRenderersBase):
    """Per-observation ``_render_*_observation`` renderers + dispatch."""

    _pending_shell_command: str | None
    _pending_shell_action: tuple[str, str] | None
    _pending_shell_title: str | None
    _pending_shell_is_internal: bool

    # Dispatch table for :meth:`_handle_observation` — maps observation class
    # to the method that knows how to render it.
    _OBSERVATION_DISPATCH: tuple[tuple[type, str], ...] = (
        (AgentStateChangedObservation, '_handle_state_change'),
        (AgentThinkObservation, '_render_agent_think_observation'),
        (BrowserScreenshotObservation, '_render_browser_screenshot_observation'),
        (CmdOutputObservation, '_render_cmd_output_observation'),
        (FileEditObservation, '_render_file_edit_observation'),
        (ErrorObservation, '_render_error_observation'),
        (UserRejectObservation, '_render_user_reject_observation'),
        (RecallObservation, '_render_recall_observation'),
        (StatusObservation, '_render_status_observation'),
        (FileReadObservation, '_render_file_read_observation'),
        (MCPObservation, '_render_mcp_observation'),
        (TerminalObservation, '_render_terminal_observation'),
        (LspQueryObservation, '_render_lsp_query_observation'),
        (DebuggerObservation, '_render_debugger_observation'),
        (GrepObservation, '_render_grep_observation'),
        (GlobObservation, '_render_glob_observation'),
        (FindSymbolsObservation, '_render_find_symbols_observation'),
        (ReadSymbolsObservation, '_render_read_symbols_observation'),
        (
            AnalyzeProjectStructureObservation,
            '_render_analyze_project_structure_observation',
        ),
        (ServerReadyObservation, '_render_server_ready_observation'),
        (SuccessObservation, '_render_success_observation'),
        (RecallFailureObservation, '_render_recall_failure_observation'),
        (FileDownloadObservation, '_render_file_download_observation'),
        (DelegateTaskObservation, '_render_delegate_task_observation'),
        (TaskTrackingObservation, '_render_task_tracking_observation'),
        (AgentCondensationObservation, '_render_agent_condensation_observation'),
    )

    def _handle_observation(self, obs: Observation) -> None:
        """Dispatch *obs* to the appropriate ``_render_*_observation`` handler."""
        for obs_type, method_name in self._OBSERVATION_DISPATCH:
            if isinstance(obs, obs_type):
                getattr(self, method_name)(obs)
                return
        self.refresh()

    # -- Per-observation renderers (small, single-CC dispatch targets) ------

    def _render_debugger_observation(self, obs: DebuggerObservation) -> None:
        """Render a debugger result in the legacy terminal frontend."""
        self._stop_reasoning()
        self._flush_pending_tool_cards()
        content = (getattr(obs, 'content', '') or '').strip()
        payload = getattr(obs, 'payload', None)
        if not content and isinstance(payload, dict):
            state = payload.get('state') or getattr(obs, 'state', None) or 'updated'
            target = payload.get('target') or getattr(obs, 'session_id', None) or ''
            content = f'{state}: {target}'.strip(': ')
        if content:
            self._render_terminal_panel(body=content)
        self.refresh()
