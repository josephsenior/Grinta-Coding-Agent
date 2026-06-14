"""Per-action renderer methods for ``CLIEventRenderer``.

Extracted from ``backend/cli/event_renderer.py`` to keep the parent module
under the per-file LOC budget.  All methods rely on attributes/methods
defined on ``CLIEventRenderer``; the mixin is meant to be combined with
that class via multiple inheritance.
"""

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

from backend.cli._event_renderer.constants import (
    INTERNAL_THINK_TAG_RE as _INTERNAL_THINK_TAG_RE,
)
from backend.cli._event_renderer.constants import (
    THINK_RESULT_JSON_RE as _THINK_RESULT_JSON_RE,
)
from backend.cli._event_renderer.constants import (
    TOOL_RESULT_TAG_RE as _TOOL_RESULT_TAG_RE,
)
from backend.cli._event_renderer.delegate import (
    summarize_delegate_action as _summarize_delegate_action,
)
from backend.cli._event_renderer.text_utils import (
    sanitize_visible_transcript_text as _sanitize_visible_transcript_text,
)
from backend.cli._event_renderer.text_utils import (
    sync_reasoning_after_tool_line as _sync_reasoning_after_tool_line,
)
from backend.cli._tool_display.renderers.think import render_message, render_think
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
from backend.cli.path_links import linkify_plain
from backend.cli.theme import (
    CLR_OPTION_RECOMMENDED,
    CLR_OPTION_TEXT,
    CLR_QUESTION_TEXT,
    MARK_INFO,
    STYLE_DIM,
)
from backend.cli.tool_call_display import (
    friendly_verb_for_tool,
    tool_headline,
)

# MCP tool name → (high-level tool name, icon, verb)
_ORIENT_MCP_MAP: dict[str, tuple[str, str, str]] = {
    'web_search_exa': ('web_search', '⚐', 'Searched'),
    'web_fetch_exa': ('web_fetch', '⚐', 'Fetched'),
    'resolve-library-id': ('docs_resolve', '⚐', 'Resolved'),
    'query-docs': ('docs_query', '⚐', 'Queried'),
}

_ORIENT_MCP_NAMES: frozenset[str] = frozenset(_ORIENT_MCP_MAP.keys())
from backend.cli.transcript import (
    format_activity_block,
    format_activity_secondary,
    format_callout_panel,
    format_orient_line,
)
from backend.ledger.action import (
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


class ActionRenderersMixin(_ActionRenderersBase):
    """Per-action ``_render_*_action`` renderers + dispatch."""

    _pending_shell_command: str | None
    _pending_shell_action: tuple[str, str] | None
    _pending_shell_title: str | None
    _pending_shell_is_internal: bool
    _last_terminal_input_sent: str

    # Orient burst tracking — consecutive orient lines get grouped.
    _orient_burst_count: int
    _orient_burst_area: str

    # Dispatch table for :meth:`_handle_agent_action` — maps action class to
    # the method that knows how to render it.  Looked up via ``isinstance``
    # so subclasses dispatch to their parent's renderer when no entry exists.
    _AGENT_ACTION_DISPATCH: tuple[tuple[type, str], ...] = (
        (StreamingChunkAction, '_render_streaming_chunk_action'),
        (MessageAction, '_render_message_action'),
        (AgentThinkAction, '_render_agent_think_action'),
        (CmdRunAction, '_render_cmd_run_action'),
        (FileEditAction, '_render_file_edit_action'),
        (FileWriteAction, '_render_file_write_action'),
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

    def _emit_orient_line(
        self, icon: str, verb: str, target: str, result: str = '…'
    ) -> None:
        """Emit a flat orient tool line with burst tracking."""
        count = getattr(self, '_orient_burst_count', 0)
        # Flush any pending non-orient card before starting a burst
        if count == 0:
            self._flush_pending_activity_card()
        # Track burst
        setattr(self, '_orient_burst_count', count + 1)
        # Print the orient line immediately
        self._emit_activity_turn_header()
        line = format_orient_line(icon, verb, target, result)
        self._print_or_buffer(Padding(line, pad=ACTIVITY_BLOCK_BOTTOM_PAD))

    def _flush_orient_burst(self) -> None:
        """Flush the orient burst — emit a summary header if ≥3 lines."""
        count = getattr(self, '_orient_burst_count', 0)
        setattr(self, '_orient_burst_count', 0)
        setattr(self, '_orient_burst_area', 'codebase')

        if count >= 3:
            area = getattr(self, '_orient_burst_area', 'codebase')
            from backend.cli.transcript import format_orient_burst_header

            header = format_orient_burst_header(area, count)
            self._print_or_buffer(
                Padding(header, pad=ACTIVITY_BLOCK_BOTTOM_PAD)
            )

    _FILE_EDIT_VERBS: dict[str, tuple[str, bool]] = {
        # cmd → (verb, include_stats)
        'create_file': ('Created', False),
        'replace_string': ('Edited', False),
        'multi_edit': ('Edited', False),
    }

    def _handle_agent_action(self, action: Action) -> None:
        """Dispatch *action* to the appropriate ``_render_*_action`` handler."""
        for action_type, method_name in self._AGENT_ACTION_DISPATCH:
            if isinstance(action, action_type):
                # Flush orient burst when a non-orient action arrives
                orient_action_types = {
                    GrepAction, GlobAction, FindSymbolsAction, ReadSymbolsAction,
                    FileReadAction, LspQueryAction, AnalyzeProjectStructureAction,
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
        self._flush_pending_tool_cards()
        path = getattr(action, 'path', '')
        view_range = getattr(action, 'view_range', None)
        start = getattr(action, 'start', 0)
        end = getattr(action, 'end', -1)
        # Build target with left-ellipsis path
        from backend.cli._tool_display.summarize import _orient_path

        display_path = _orient_path(path, 36) if path else ''
        if view_range and len(view_range) == 2:
            target = f'{display_path} · lines {view_range[0]}–{view_range[1]}'
        elif start not in (0, 1) or end != -1:
            end_str = str(end) if end != -1 else 'end'
            target = f'{display_path} · {start}:{end_str}'
        else:
            target = display_path
        self._emit_orient_line('↳', 'Read', target)
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(self._reasoning, f'Read {path}', thought)
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

    def _render_mcp_action(self, action: MCPAction) -> None:
        self._flush_pending_tool_cards()
        name = getattr(action, 'name', 'tool')
        raw_args = getattr(action, 'arguments', None) or {}
        # Emit flat orient line for orient MCP tools
        if name in _ORIENT_MCP_NAMES:
            hl_name, icon, verb = _ORIENT_MCP_MAP[name]
            # Build target from args
            query = raw_args.get('query') or raw_args.get('pattern') or ''
            url = ''
            if isinstance(raw_args.get('urls'), list) and raw_args['urls']:
                url = str(raw_args['urls'][0])
            elif raw_args.get('url'):
                url = str(raw_args['url'])
            library = raw_args.get('library') or raw_args.get('library_name') or ''
            if hl_name == 'web_search':
                target = f'"{query}"' if query else 'search'
            elif hl_name == 'web_fetch':
                from backend.cli._tool_display.summarize import _orient_path

                target = _orient_path(url) if url else 'fetch'
            elif hl_name == 'docs_resolve':
                target = f'{library} · "{query}"' if library and query else str(query or library or 'docs')
            elif hl_name == 'docs_query':
                target = f'{library} · "{query}"' if library and query else str(query or library or 'docs')
            else:
                target = str(query or url or name)
            self._emit_orient_line(icon, verb, target)
            thought = getattr(action, 'thought', '') or ''
            _sync_reasoning_after_tool_line(self._reasoning, f'{name}', thought)
            self.refresh()
            return
        # Non-orient MCP tools use the existing card mechanism
        verb = friendly_verb_for_tool(name, raw_args)
        args_str = ', '.join(
            f'{k}={repr(v)[:40]}' for k, v in list(raw_args.items())[:2]
        )
        if len(args_str) > 80:
            args_str = args_str[:77] + '…'
        detail = f'{name}({args_str})' if args_str else name
        self._buffer_pending_activity(
            title=ACTIVITY_CARD_TITLE_MCP,
            verb=verb,
            detail=detail,
            kind='mcp',
            badge_label='mcp',
        )
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(self._reasoning, f'MCP {name}', thought)
        self.refresh()

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

    def _render_lsp_query_action(self, action: LspQueryAction) -> None:
        self._flush_pending_tool_cards()
        cmd = getattr(action, 'command', 'query')
        symbol = getattr(action, 'symbol', '')
        file = getattr(action, 'file', '')
        target = f'{cmd} · {symbol or file}'.strip()
        self._emit_orient_line('≡', 'Analyzed', target)
        self.refresh()

    def _render_grep_action(self, action: GrepAction) -> None:
        self._flush_pending_tool_cards()
        target = f'"{action.pattern or ""}" in {action.path or ""}'.strip()
        self._emit_orient_line('₡', 'Grepped', target)
        self.refresh()

    def _render_glob_action(self, action: GlobAction) -> None:
        self._flush_pending_tool_cards()
        target = f'{action.pattern or ""} in {action.path or ""}'.strip()
        self._emit_orient_line('✻', 'Globbed', target)
        self.refresh()

    def _render_find_symbols_action(self, action: FindSymbolsAction) -> None:
        self._flush_pending_tool_cards()
        target = f'"{action.query or ""}"'
        if action.path:
            target += f' in {action.path}'
        self._emit_orient_line('ƒ', 'Found', target)
        self.refresh()

    def _render_read_symbols_action(self, action: ReadSymbolsAction) -> None:
        self._flush_pending_tool_cards()
        target_count = len(getattr(action, 'targets', []) or [])
        target = f'{target_count} symbol{"s" if target_count != 1 else ""}'
        if action.path:
            target += f' in {action.path}'
        self._emit_orient_line('↳', 'Read', target)
        self.refresh()

    def _render_analyze_project_structure_action(
        self, action: AnalyzeProjectStructureAction
    ) -> None:
        self._flush_pending_tool_cards()
        target = f'{action.command} {action.path}'.strip()
        self._emit_orient_line('≡', 'Analyzed', target or 'project structure')
        self.refresh()

    def _render_task_tracking_action(self, action: TaskTrackingAction) -> None:
        command = str(getattr(action, 'command', '') or '').strip().lower()
        task_list = getattr(action, 'task_list', None)
        if command == 'update' and isinstance(task_list, list):
            self._set_task_panel(task_list)
        self.refresh()

    def _render_condensation_action(self, action: CondensationAction) -> None:
        count = getattr(self, '_condensation_count', 0) + 1
        self._condensation_count = count
        suffix = self._ordinal_suffix(count)

        self._ensure_reasoning()
        self._reasoning.update_action(f'Compressing context ({count}{suffix})…')

        host = getattr(self, '_host', None)
        if host is not None:
            host._hud.update_condensation_count(count)
        self.refresh()

    @staticmethod
    def _ordinal_suffix(n: int) -> str:
        if n % 10 == 1 and n % 11 != 1:
            return 'st'
        if n % 10 == 2 and n % 11 != 2:
            return 'nd'
        if n % 10 == 3 and n % 11 != 3:
            return 'rd'
        return 'th'

    def _render_terminal_run_action(self, action: TerminalRunAction) -> None:
        self._flush_pending_tool_cards()
        cmd = (getattr(action, 'command', '') or '').strip()
        if len(cmd) > 12_000:
            cmd = cmd[:11_997] + '…'
        self._pending_shell_command = cmd
        label = cmd if cmd else '(empty)'
        self._print_activity(
            'Launch',
            f'$ {label}',
            None,
            title=ACTIVITY_CARD_TITLE_TERMINAL,
            shell_rail=True,
            badge_label='terminal',
        )
        self._ensure_reasoning()
        pty_line = f'{ACTIVITY_CARD_TITLE_TERMINAL} · {label}'
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(self._reasoning, pty_line, thought)
        self.refresh()

    def _render_terminal_input_action(self, action: TerminalInputAction) -> None:
        self._flush_pending_tool_cards()
        sess = (getattr(action, 'session_id', '') or '').strip()
        inp = getattr(action, 'input', '') or ''
        ctrl = getattr(action, 'control', None)
        is_ctl = bool(getattr(action, 'is_control', False))
        inp_display, sent_for_echo = self._terminal_input_display(
            inp=inp, ctrl=ctrl, is_ctl=is_ctl
        )
        self._last_terminal_input_sent = sent_for_echo
        cmd_detail = f'[{sess}]  $ {inp_display}' if sess else f'$ {inp_display}'
        self._print_activity(
            'Run',
            cmd_detail,
            None,
            title=ACTIVITY_CARD_TITLE_TERMINAL,
            badge_label='terminal',
        )
        self._ensure_reasoning()
        line = self._terminal_input_reasoning_line(sess=sess, inp_display=inp_display)
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(self._reasoning, line, thought)
        self.refresh()

    @staticmethod
    def _terminal_input_display(
        *, inp: str, ctrl: Any, is_ctl: bool
    ) -> tuple[str, str]:
        if ctrl and str(ctrl).strip():
            return f'ctrl {ctrl}'[:60], ''
        if is_ctl and inp:
            return inp[:60] + ('…' if len(inp) > 60 else ''), ''
        return (
            inp[:60] + ('…' if len(inp) > 60 else ''),
            inp.strip().rstrip('\r\n'),
        )

    @staticmethod
    def _terminal_input_reasoning_line(*, sess: str, inp_display: str) -> str:
        if sess and inp_display:
            return f'{ACTIVITY_CARD_TITLE_TERMINAL} input · {sess} · {inp_display}'
        if sess:
            return f'{ACTIVITY_CARD_TITLE_TERMINAL} input · {sess}'
        return f'{ACTIVITY_CARD_TITLE_TERMINAL} input · {inp_display or "…"}'

    def _render_terminal_read_action(self, action: TerminalReadAction) -> None:
        # Read is a polling operation — don't clutter the transcript with a
        # full card; just keep the reasoning panel up-to-date.
        sess = (getattr(action, 'session_id', '') or '').strip()
        self._ensure_reasoning()
        line = (
            f'{ACTIVITY_CARD_TITLE_TERMINAL} read · {sess}'
            if sess
            else f'{ACTIVITY_CARD_TITLE_TERMINAL} read · …'
        )
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(self._reasoning, line, thought)
        self.refresh()

    def _render_delegate_task_action(self, action: DelegateTaskAction) -> None:
        self._flush_pending_tool_cards()
        self._reset_delegate_panel(batch_id=action.id if action.id > 0 else None)
        desc_display, secondary = _summarize_delegate_action(action)
        self._buffer_pending_activity(
            title=ACTIVITY_CARD_TITLE_DELEGATION,
            verb='Delegated',
            detail=desc_display,
            secondary=secondary,
            kind='delegate',
            badge_label='workers',
        )
        self.refresh()

    def _render_escalate_to_human_action(self, action: EscalateToHumanAction) -> None:
        self._flush_pending_tool_cards()
        self._stop_reasoning()
        reason = getattr(action, 'reason', '')
        help_needed = getattr(action, 'specific_help_needed', '')
        escalate_parts: list[Any] = []
        if reason:
            escalate_parts.append(Text(reason, style=CLR_QUESTION_TEXT))
        if help_needed:
            escalate_parts.append(
                Text(f'Help needed: {help_needed}', style=CLR_QUESTION_TEXT)
            )
        if not escalate_parts:
            escalate_parts.append(
                Text('The agent needs your input to continue.', style=CLR_QUESTION_TEXT)
            )
        self._append_history(
            format_callout_panel(
                'Need Your Input',
                Group(*escalate_parts),
                accent_style=DECISION_PANEL_ACCENT_STYLE,
            )
        )
        self.refresh()

    def _render_clarification_request_action(
        self, action: ClarificationRequestAction
    ) -> None:
        self._flush_pending_tool_cards()
        self._stop_reasoning()
        question = getattr(action, 'question', '')
        options = getattr(action, 'options', []) or []
        clarify_parts: list[Any] = []
        if question:
            clarify_parts.append(Text(question, style=CLR_QUESTION_TEXT))
        for i, opt in enumerate(options, 1):
            option_line = Text()
            option_line.append(f'{i}. ', style=f'bold {CLR_OPTION_RECOMMENDED}')
            option_line.append(str(opt), style=CLR_OPTION_TEXT)
            clarify_parts.append(option_line)
        if clarify_parts:
            self._append_history(
                format_callout_panel(
                    'Question',
                    Group(*clarify_parts),
                    accent_style=DECISION_PANEL_ACCENT_STYLE,
                )
            )
        self.refresh()

    def _render_uncertainty_action(self, action: UncertaintyAction) -> None:
        self._flush_pending_tool_cards()
        concerns = getattr(action, 'specific_concerns', []) or []
        info_needed = getattr(action, 'requested_information', '')
        uncertainty_parts: list[Any] = []
        for concern in concerns[:5]:
            concern_line = Text()
            concern_line.append(f'{MARK_INFO} ', style=STYLE_DIM)
            concern_line.append(str(concern), style=STYLE_DIM)
            uncertainty_parts.append(concern_line)
        if info_needed:
            uncertainty_parts.append(
                Text(f'Need: {info_needed}', style=CLR_QUESTION_TEXT)
            )
        if uncertainty_parts:
            self._append_history(
                format_callout_panel(
                    'Needs Context',
                    Group(*uncertainty_parts),
                    accent_style=DECISION_PANEL_ACCENT_STYLE,
                )
            )
        self.refresh()

    def _render_proposal_action(self, action: ProposalAction) -> None:
        self._flush_pending_tool_cards()
        self._stop_reasoning()
        options = getattr(action, 'options', []) or []
        recommended = getattr(action, 'recommended', 0)
        rationale = getattr(action, 'rationale', '')
        proposal_parts: list[Any] = []
        if rationale:
            proposal_parts.append(Text(rationale, style=STYLE_DIM))
        for i, opt in enumerate(options):
            label = opt.get('name', opt.get('title', f'Option {i + 1}'))
            desc = opt.get('description', '')
            marker = ' (recommended)' if i == recommended else ''
            proposal_line = Text()
            proposal_line.append(
                f'{i + 1}. ',
                style=f'bold {DECISION_PANEL_ACCENT_STYLE}',
            )
            proposal_line.append(
                f'{label}{marker}',
                style=f'bold {CLR_OPTION_RECOMMENDED}'
                if i == recommended
                else f'bold {CLR_OPTION_TEXT}',
            )
            proposal_parts.append(proposal_line)
            if desc:
                proposal_parts.append(Text(f'   {desc}', style=STYLE_DIM))
        if proposal_parts:
            self._append_history(
                format_callout_panel(
                    'Options',
                    Group(*proposal_parts),
                    accent_style=DECISION_PANEL_ACCENT_STYLE,
                )
            )
        self.refresh()


__all__ = ['ActionRenderersMixin']
