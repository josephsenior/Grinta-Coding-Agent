"""Action renderers — shell domain."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from backend.cli._typing import ActionRenderersHost

    _ActionRenderersBase = ActionRenderersHost
else:
    _ActionRenderersBase = object

from rich.console import Group
from rich.padding import Padding
from rich.text import Text

from backend.cli.event_rendering.constants import (
    INTERNAL_THINK_TAG_RE as _INTERNAL_THINK_TAG_RE,
)
from backend.cli.event_rendering.constants import (
    THINK_RESULT_JSON_RE as _THINK_RESULT_JSON_RE,
)
from backend.cli.event_rendering.constants import (
    TOOL_RESULT_TAG_RE as _TOOL_RESULT_TAG_RE,
)
from backend.cli.event_rendering.delegate import (
    summarize_delegate_action as _summarize_delegate_action,
)
from backend.cli.event_rendering.text_utils import (
    sanitize_visible_transcript_text as _sanitize_visible_transcript_text,
)
from backend.cli.event_rendering.text_utils import (
    sync_reasoning_after_tool_line as _sync_reasoning_after_tool_line,
)
from backend.cli.tool_display.renderers.think import render_message, render_think
from backend.cli._typing import ActionRenderersHost
from backend.cli.layout_tokens import (
    ACTIVITY_BLOCK_BOTTOM_PAD,
    ACTIVITY_CARD_TITLE_BROWSER,
    ACTIVITY_CARD_TITLE_CHECKPOINT,
    ACTIVITY_CARD_TITLE_DELEGATION,
    ACTIVITY_CARD_TITLE_FILES,
    ACTIVITY_CARD_TITLE_MCP,
    ACTIVITY_CARD_TITLE_SHELL,
    ACTIVITY_CARD_TITLE_TERMINAL,
    ACTIVITY_CARD_TITLE_TOOL,
    DECISION_PANEL_ACCENT_STYLE,
)
from backend.cli.orient_tools import (
    ORIENT_MCP_TOOL_NAMES,
    OrientLineModel,
    analyze_action_model,
    file_read_action_model,
    find_symbols_action_model,
    glob_action_model,
    grep_action_model,
    lsp_action_model,
    mcp_action_model,
    read_symbols_action_model,
)
from backend.cli.path_links import linkify_plain
from backend.cli.theme import (
    CLR_OPTION_RECOMMENDED,
    CLR_OPTION_TEXT,
    CLR_QUESTION_TEXT,
    MARK_INFO,
    STYLE_DIM,
)
from backend.cli.display.tool_call_display import friendly_verb_for_tool, tool_headline
from backend.cli.display.transcript import (  # noqa: E402
    format_activity_block,
    format_activity_secondary,
    format_callout_panel,
    format_orient_line,
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
    DelegateTaskAction,
    EscalateToHumanAction,
    FileEditAction,
    FileReadAction,
    FileWriteAction,
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

class _ActionShellMixin(_ActionRenderersBase):
    def _render_cmd_run_action(self, action: CmdRunAction) -> None:
        self._flush_pending_activity_card()
        if getattr(action, 'hidden', False):
            self.refresh()
            return
        if self._pending_shell_action is not None:
            self._flush_pending_shell_action()
        display_label = (getattr(action, 'display_label', '') or '').strip()
        if display_label:
            self._buffer_internal_shell_command(action, display_label)
            return
        self._buffer_external_shell_command(action)

    def _buffer_external_shell_command(self, action: CmdRunAction) -> None:
        self._pending_shell_is_internal = False
        self._pending_shell_title = None
        cmd_display = (action.command or '').strip()
        if len(cmd_display) > 12_000:
            cmd_display = cmd_display[:11_997] + '…'
        self._pending_shell_command = cmd_display
        label = f'$ {cmd_display}' if cmd_display else '$ (empty)'
        self._pending_shell_action = ('Ran', label)
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(self._reasoning, label, thought)
        self.refresh()

    def _buffer_internal_shell_command(
        self, action: CmdRunAction, display_label: str
    ) -> None:
        """Buffer an internal-tool ``CmdRunAction`` (``display_label`` set)."""
        meta = getattr(action, 'tool_call_metadata', None)
        function_name = getattr(meta, 'function_name', '') or ''
        _icon, headline = tool_headline(function_name, use_icons=self._cli_tool_icons)
        self._pending_shell_command = None
        self._pending_shell_action = ('Ran', display_label)
        self._pending_shell_title = headline or ACTIVITY_CARD_TITLE_SHELL
        self._pending_shell_is_internal = True
        self.refresh()
