"""Action renderers — file domain."""

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

class _ActionFileMixin(_ActionRenderersBase):
    def _render_file_edit_action(self, action: FileEditAction) -> None:
        self._flush_pending_tool_cards()
        cmd = getattr(action, 'command', '')
        path = action.path
        insert_line = getattr(action, 'insert_line', None)
        start = getattr(action, 'start', 1)
        end = getattr(action, 'end', -1)
        stats: str | None = None
        verb_entry = self._FILE_EDIT_VERBS.get(cmd)
        if verb_entry is not None:
            verb, include_stats = verb_entry
            detail = path
            if include_stats and insert_line is not None:
                stats = f'line {insert_line}'
        elif not cmd:
            end_str = str(end) if end != -1 else 'end'
            verb, detail = 'Edited', f'{path} · {start}:{end_str}'
        else:
            verb, detail = 'Edited', path
        badge_label = self._file_badge_label(action)
        self._buffer_pending_activity(
            title=ACTIVITY_CARD_TITLE_FILES,
            verb=verb,
            detail=detail,
            secondary=stats,
            kind='file_edit',
            badge_label=badge_label,
        )
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(self._reasoning, f'{verb} {detail}', thought)
        self.refresh()

    def _render_file_write_action(self, action: FileWriteAction) -> None:
        self._flush_pending_tool_cards()
        self._buffer_pending_activity(
            title=ACTIVITY_CARD_TITLE_FILES,
            verb='Created',
            detail=action.path,
            kind='file_write',
            badge_label='files',
        )
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(
            self._reasoning, f'Created {action.path}', thought
        )
        self.refresh()

    def _render_recall_action(self, action: RecallAction) -> None:
        # Memory recall is an internal operation - don't show as visible activity
        # It's already indicated in the reasoning display if needed
        self.refresh()

    def _render_file_read_action(self, action: FileReadAction) -> None:
        self._queue_orient_line(file_read_action_model(action))
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(
            self._reasoning,
            f'Read {getattr(action, "path", "")}',
            thought,
        )
        self.refresh()

    @staticmethod
    def _file_badge_label(action: Any) -> str:
        impl_source = getattr(action, 'impl_source', None)
        source_value = getattr(impl_source, 'value', impl_source)
        if source_value == 'file_edit':
            return 'file_edit'
        if source_value == 'default':
            return 'files'
        return 'files'

