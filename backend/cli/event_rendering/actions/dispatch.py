"""Action renderers — dispatch domain."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.cli._typing import ActionRenderersHost

    _ActionRenderersBase = ActionRenderersHost
else:
    _ActionRenderersBase = object

from rich.padding import Padding

from backend.cli._typing import ActionRenderersHost
from backend.cli.display.transcript import (  # noqa: E402
    format_orient_line,
)
from backend.cli.layout_tokens import (
    ACTIVITY_BLOCK_BOTTOM_PAD,
)
from backend.cli.orient_tools import (
    ORIENT_MCP_TOOL_NAMES,
    OrientLineModel,
)
from backend.ledger.action import (  # noqa: E402
    Action,
    AgentThinkAction,
    AnalyzeProjectStructureAction,
    BrowseInteractiveAction,
    BrowserToolAction,
    ClarificationRequestAction,
    CmdRunAction,
    CondensationAction,
    DebuggerAction,
    DelegateTaskAction,
    EscalateToHumanAction,
    FileEditAction,
    FileReadAction,
    FindSymbolsAction,
    GlobAction,
    GrepAction,
    LspQueryAction,
    MCPAction,
    MessageAction,
    ProposalAction,
    ReadSymbolsAction,
    RecallAction,
    StreamingChunkAction,
    TaskTrackingAction,
    TerminalInputAction,
    TerminalReadAction,
    TerminalRunAction,
    UncertaintyAction,
)

_ORIENT_MCP_NAMES: frozenset[str] = ORIENT_MCP_TOOL_NAMES


class _ActionDispatchMixin(_ActionRenderersBase):
    """Per-action ``_render_*_action`` renderers + dispatch."""

    _pending_shell_command: str | None
    _pending_shell_action: tuple[str, str] | None
    _pending_shell_title: str | None
    _pending_shell_is_internal: bool
    _last_terminal_input_sent: str

    # Orient burst tracking — consecutive orient lines get grouped.
    _orient_burst_count: int
    _orient_burst_area: str
    _pending_orient_line: OrientLineModel | None
    _orient_burst_lines: list[OrientLineModel]

    # Dispatch table for :meth:`_handle_agent_action` — maps action class to
    # the method that knows how to render it.  Looked up via ``isinstance``
    # so subclasses dispatch to their parent's renderer when no entry exists.
    _AGENT_ACTION_DISPATCH: tuple[tuple[type, str], ...] = (
        (StreamingChunkAction, '_render_streaming_chunk_action'),
        (MessageAction, '_render_message_action'),
        (AgentThinkAction, '_render_agent_think_action'),
        (CmdRunAction, '_render_cmd_run_action'),
        (FileEditAction, '_render_file_edit_action'),
        (RecallAction, '_render_recall_action'),
        (FileReadAction, '_render_file_read_action'),
        (MCPAction, '_render_mcp_action'),
        (BrowserToolAction, '_render_browser_tool_action'),
        (BrowseInteractiveAction, '_render_browse_interactive_action'),
        (GrepAction, '_render_grep_action'),
        (GlobAction, '_render_glob_action'),
        (FindSymbolsAction, '_render_find_symbols_action'),
        (ReadSymbolsAction, '_render_read_symbols_action'),
        (AnalyzeProjectStructureAction, '_render_analyze_project_structure_action'),
        (LspQueryAction, '_render_lsp_query_action'),
        (DebuggerAction, '_render_debugger_action'),
        (TaskTrackingAction, '_render_task_tracking_action'),
        (CondensationAction, '_render_condensation_action'),
        (TerminalRunAction, '_render_terminal_run_action'),
        (TerminalInputAction, '_render_terminal_input_action'),
        (TerminalReadAction, '_render_terminal_read_action'),
        (DelegateTaskAction, '_render_delegate_task_action'),
        (EscalateToHumanAction, '_render_escalate_to_human_action'),
        (ClarificationRequestAction, '_render_clarification_request_action'),
        (UncertaintyAction, '_render_uncertainty_action'),
        (ProposalAction, '_render_proposal_action'),
    )

    _NO_MATCH_FRAGMENTS: tuple[str, ...] = (
        'No matches found.',
        'No matching files found',
    )

    # -- Orient tool helpers --------------------------------------------------

    def _queue_orient_line(self, model: OrientLineModel) -> None:
        """Queue an orient line until its observation supplies the metric."""
        self._flush_pending_activity_card()
        pending = getattr(self, '_pending_orient_line', None)
        if pending is not None:
            self._append_orient_line(pending)
        self._pending_orient_line = model

    def _append_orient_line(self, model: OrientLineModel) -> None:
        lines = getattr(self, '_orient_burst_lines', None)
        if lines is None:
            lines = []
            self._orient_burst_lines = lines
        lines.append(model)
        self._orient_burst_count = len(lines)
        self._orient_burst_area = model.area or self._orient_burst_area
        self._emit_activity_turn_header()
        line = format_orient_line(
            model.icon,
            model.verb,
            model.target,
            model.result,
        )
        self._print_or_buffer(Padding(line, pad=ACTIVITY_BLOCK_BOTTOM_PAD))

    def _flush_orient_burst(self) -> None:
        """Flush queued orient lines; group only when the finished burst is dense."""
        pending = getattr(self, '_pending_orient_line', None)
        if pending is not None:
            self._pending_orient_line = None
            self._append_orient_line(pending)

        self._orient_burst_lines = []
        self._orient_burst_count = 0
        self._orient_burst_area = 'codebase'
        return

    _FILE_EDIT_VERBS: dict[str, tuple[str, bool]] = {
        # cmd → (verb, include_stats)
        'create_file': ('Created', False),
        'replace_string': ('Edited', False),
        'multi_edit': ('Edited', False),
        'edit': ('Edited', False),
        'insert_text': ('Edited', False),
    }

    def _handle_agent_action(self, action: Action) -> None:
        """Dispatch *action* to the appropriate ``_render_*_action`` handler."""
        for action_type, method_name in self._AGENT_ACTION_DISPATCH:
            if isinstance(action, action_type):
                # Flush orient burst when a non-orient action arrives
                orient_action_types = {
                    GrepAction,
                    GlobAction,
                    FindSymbolsAction,
                    ReadSymbolsAction,
                    FileReadAction,
                    LspQueryAction,
                    AnalyzeProjectStructureAction,
                }
                is_orient = action_type in orient_action_types or (
                    action_type is MCPAction
                    and getattr(action, 'name', '') in _ORIENT_MCP_NAMES
                )
                if not is_orient:
                    self._flush_orient_burst()
                # Most handlers do their own ``_clear_streaming_preview`` /
                # flush calls; only ``AgentThinkAction`` is allowed to skip
                # the preview clear so reasoning text keeps rendering.
                if (
                    action_type is not AgentThinkAction
                    and action_type is not (StreamingChunkAction)
                    and action_type is not MessageAction
                ):
                    self._clear_streaming_preview()
                getattr(self, method_name)(action)
                return
        self.refresh()

    # -- Per-action renderers (small, single-CC dispatch targets) -----------

    def _render_debugger_action(self, action: DebuggerAction) -> None:
        """Render a debugger action in the legacy terminal frontend."""
        from backend.cli.tool_display.headline import friendly_verb_for_tool
        from backend.cli.tool_display.summarize import summarize_tool_arguments

        self._flush_pending_tool_cards()
        args = {
            'action': getattr(action, 'debug_action', '') or '',
            'session_id': getattr(action, 'session_id', None),
            'adapter': getattr(action, 'adapter', None),
            'language': getattr(action, 'language', None),
            'program': getattr(action, 'program', None),
            'cwd': getattr(action, 'cwd', None),
            'file': getattr(action, 'file', None),
            'lines': getattr(action, 'lines', None),
            'breakpoints': getattr(action, 'breakpoints', None),
            'expression': getattr(action, 'expression', None),
        }
        self._print_activity(
            friendly_verb_for_tool('debugger', args),
            summarize_tool_arguments('debugger', args),
            None,
            title='Debugger',
            shell_rail=True,
            badge_label='debugger',
        )
        self._ensure_reasoning()
        self.refresh()
