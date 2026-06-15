"""Action renderers — message domain."""

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

class _ActionMessageMixin(_ActionRenderersBase):
    def _render_streaming_chunk_action(self, action: StreamingChunkAction) -> None:
        self._handle_streaming_chunk(action)

    def _render_message_action(self, action: MessageAction) -> None:
        if bool(getattr(action, 'suppress_cli', False)):
            self._stop_reasoning()
        thought = self._resolve_message_thought(action)
        content = (action.content or '').strip()

        if not thought:
            self._render_message_without_thought(action, content)
            return

        display_parts = self._build_message_display_parts(thought, content)

        if not display_parts:
            self._stop_reasoning()
            self.refresh()
            return

        self._stop_reasoning()
        attachments = self._message_action_attachments(action)
        self._finalize_message_display(display_parts, attachments)

    def _resolve_message_thought(self, action: MessageAction) -> str:
        host = cast(ActionRenderersHost, self)
        thought = (getattr(action, 'thought', None) or '').strip()
        if not thought:
            captured_thoughts = host._reasoning.snapshot_thoughts()
            if captured_thoughts:
                thought = '\n'.join(captured_thoughts)
        return thought

    def _render_message_without_thought(
        self, action: MessageAction, content: str
    ) -> None:
        display_content = content
        if display_content:
            display_content = _sanitize_visible_transcript_text(display_content)
        if not display_content:
            self._stop_reasoning()
            self.refresh()
            return
        self._stop_reasoning()
        attachments = self._message_action_attachments(action)
        self._append_assistant_message(display_content, attachments=attachments)

    def _build_message_display_parts(self, thought: str, content: str) -> list[Any]:
        from rich.text import Text

        display_parts: list[Any] = []
        extra_lines = render_message(thought)
        text_parts: list[str] = []
        for item in extra_lines[1:]:
            if isinstance(item, Text):
                text_parts.append(item.plain)
            elif hasattr(item, 'code'):
                text_parts.append(item.code)
            else:
                text_parts.append(str(item))
        display_parts.append(Text('\n'.join(text_parts)))

        if content:
            sanitized_content = _sanitize_visible_transcript_text(content)
            if sanitized_content:
                display_parts.append(Text(sanitized_content))

        return display_parts

    def _finalize_message_display(
        self, display_parts: list[Any], attachments: list[Any]
    ) -> None:
        from rich.text import Text

        if len(display_parts) == 1:
            final_content = display_parts[0]
        else:
            final_content = Text('\n', style='reset').join(display_parts)

        self._append_assistant_message(final_content, attachments=attachments)

    @staticmethod
    def _message_action_attachments(action: MessageAction) -> list[Any]:
        attachments: list[Any] = []
        for attr, label in (('file_urls', 'file'), ('image_urls', 'image')):
            urls = getattr(action, attr, None) or []
            if urls:
                attachments.append(
                    format_activity_secondary(
                        f'{label}s attached · {len(urls)} {label}(s)',
                        kind='neutral',
                    )
                )
        return attachments

    def _render_agent_think_action(self, action: AgentThinkAction) -> None:
        suppress = bool(getattr(action, 'suppress_cli', False))
        if suppress:
            self.refresh()
            return
        source_tool = getattr(action, 'source_tool', '') or ''
        thought = getattr(action, 'thought', '') or getattr(action, 'content', '')
        if source_tool:
            self._render_tool_sourced_think(source_tool, thought)
            return

        if not self._check_think_dedup(thought):
            return

        self._render_think_card(thought)

    def _check_think_dedup(self, thought: str) -> bool:
        import hashlib

        content_hash = hashlib.sha256((thought or '').encode()).hexdigest()[:16]
        if content_hash == getattr(self, '_last_think_action_hash', None):
            self.refresh()
            return False
        self._last_think_action_hash = content_hash
        return True

    def _render_think_card(self, thought: str) -> None:
        extra_lines = render_think(thought)
        first_line = (
            thought.split('\n')[0].replace('\n', ' ').strip()[:100]
            if thought
            else 'Thinking'
        )

        inner = format_activity_block(
            'Thinking:',
            first_line[:100] or 'Thinking',
            secondary=None,
            secondary_kind='neutral',
            extra_lines=extra_lines,
        )
        self._print_or_buffer(Padding(inner, pad=ACTIVITY_BLOCK_BOTTOM_PAD))
        self.refresh()

    def _render_tool_sourced_think(self, source_tool: str, thought: str) -> None:
        """Render an ``AgentThinkAction`` that originated from a tool call."""
        cleaned = _THINK_RESULT_JSON_RE.sub('', thought).strip()
        tag_m = _INTERNAL_THINK_TAG_RE.match(cleaned)
        human_msg = (tag_m.group('payload') or '').strip() if tag_m else cleaned
        human_msg = _TOOL_RESULT_TAG_RE.sub('', human_msg).strip()

        verb, title, detail = self._think_action_card_fields(source_tool, human_msg)
        self._emit_activity_turn_header()
        self._render_generic_tool_think(verb, title, detail, human_msg)

    def _render_generic_tool_think(
        self, verb: str, title: str, detail: str, human_msg: str
    ) -> None:
        kind = 'err' if 'Failure' in (human_msg or '') else 'ok'
        self._print_or_buffer(
            Padding(
                format_activity_block(
                    verb,
                    detail,
                    secondary=None,
                    secondary_kind=kind,
                    title=title,
                ),
                pad=ACTIVITY_BLOCK_BOTTOM_PAD,
            )
        )
        self.refresh()

    @classmethod
    def _think_action_card_fields(
        cls, source_tool: str, human_msg: str
    ) -> tuple[str, str, str]:
        if source_tool == 'checkpoint':
            return 'Saved', ACTIVITY_CARD_TITLE_CHECKPOINT, human_msg or 'checkpoint'
        verb = source_tool.replace('_', ' ').title()
        return verb, ACTIVITY_CARD_TITLE_TOOL, str(human_msg)[:150] or source_tool
