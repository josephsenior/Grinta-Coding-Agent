"""Action renderers — browser domain."""

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

class _ActionBrowserMixin(_ActionRenderersBase):
    def _render_browser_tool_action(self, action: BrowserToolAction) -> None:
        self._flush_pending_tool_cards()
        cmd = getattr(action, 'command', '') or 'browser'
        params = getattr(action, 'params', None) or {}
        url = params.get('url') if isinstance(params, dict) else None
        if url:
            detail: str | Text = linkify_plain(
                str(url)[:500], link_files=True, link_urls=True
            )
            reasoning_detail = str(url)[:500]
        else:
            detail = str(cmd)
            reasoning_detail = detail
        self._print_activity(
            str(cmd),
            detail,
            None,
            title=ACTIVITY_CARD_TITLE_BROWSER,
            badge_label='browser',
        )
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(self._reasoning, reasoning_detail, thought)
        self.refresh()

    def _render_browse_interactive_action(
        self, action: BrowseInteractiveAction
    ) -> None:
        self._flush_pending_tool_cards()
        browser_actions = getattr(action, 'browser_actions', '') or ''
        url_match = re.search(r'https?://[^\s\'")\]]+', browser_actions)
        if url_match:
            raw_url = url_match.group(0)[:500]
            detail: str | Text = linkify_plain(raw_url, link_files=True, link_urls=True)
            reasoning_detail = raw_url
        else:
            detail = 'interactive session'  # type: ignore[unreachable]
            reasoning_detail = detail
        self._print_activity(
            'Opened',
            detail,
            None,
            title=ACTIVITY_CARD_TITLE_BROWSER,
            badge_label='browser',
        )
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(self._reasoning, reasoning_detail, thought)
        self.refresh()

