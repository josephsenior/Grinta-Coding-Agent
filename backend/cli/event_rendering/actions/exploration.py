"""Action renderers — exploration domain."""

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

class _ActionExplorationMixin(_ActionRenderersBase):
    def _render_lsp_query_action(self, action: LspQueryAction) -> None:
        self._queue_orient_line(lsp_action_model(action))
        self.refresh()

    def _render_grep_action(self, action: GrepAction) -> None:
        self._queue_orient_line(grep_action_model(action))
        self.refresh()

    def _render_glob_action(self, action: GlobAction) -> None:
        self._queue_orient_line(glob_action_model(action))
        self.refresh()

    def _render_find_symbols_action(self, action: FindSymbolsAction) -> None:
        self._queue_orient_line(find_symbols_action_model(action))
        self.refresh()

    def _render_read_symbols_action(self, action: ReadSymbolsAction) -> None:
        self._queue_orient_line(read_symbols_action_model(action))
        self.refresh()

    def _render_analyze_project_structure_action(
        self, action: AnalyzeProjectStructureAction
    ) -> None:
        self._queue_orient_line(analyze_action_model(action))
        self.refresh()

