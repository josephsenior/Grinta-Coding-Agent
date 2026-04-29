"""Per-action renderer methods for ``CLIEventRenderer``.

Extracted from ``backend/cli/event_renderer.py`` to keep the parent module
under the per-file LOC budget.  All methods rely on attributes/methods
defined on ``CLIEventRenderer``; the mixin is meant to be combined with
that class via multiple inheritance.
"""

from __future__ import annotations

import re
from typing import Any

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
    show_reasoning_text as _show_reasoning_text,
)
from backend.cli._event_renderer.text_utils import (
    sync_reasoning_after_tool_line as _sync_reasoning_after_tool_line,
)
from backend.cli.layout_tokens import (
    ACTIVITY_BLOCK_BOTTOM_PAD,
    ACTIVITY_CARD_TITLE_BROWSER,
    ACTIVITY_CARD_TITLE_CHECKPOINT,
    ACTIVITY_CARD_TITLE_CODE,
    ACTIVITY_CARD_TITLE_DELEGATION,
    ACTIVITY_CARD_TITLE_FILES,
    ACTIVITY_CARD_TITLE_MCP,
    ACTIVITY_CARD_TITLE_MEMORY,
    ACTIVITY_CARD_TITLE_SEARCH,
    ACTIVITY_CARD_TITLE_SHELL,
    ACTIVITY_CARD_TITLE_TERMINAL,
    ACTIVITY_CARD_TITLE_TOOL,
    DECISION_PANEL_ACCENT_STYLE,
)
from backend.cli.tool_call_display import (
    format_tool_activity_rows,
    tool_headline,
)
from backend.cli.transcript import (
    format_activity_block,
    format_activity_secondary,
    format_callout_panel,
)
from backend.ledger.action import (
    Action,
    AgentThinkAction,
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
    LspQueryAction,
    MCPAction,
    MessageAction,
    PlaybookFinishAction,
    ProposalAction,
    RecallAction,
    StreamingChunkAction,
    TaskTrackingAction,
    TerminalInputAction,
    TerminalReadAction,
    TerminalRunAction,
    UncertaintyAction,
)


class ActionRenderersMixin:
    """Per-action ``_render_*_action`` renderers + dispatch."""

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
        (LspQueryAction, '_render_lsp_query_action'),
        (TaskTrackingAction, '_render_task_tracking_action'),
        (CondensationAction, '_render_condensation_action'),
        (TerminalRunAction, '_render_terminal_run_action'),
        (TerminalInputAction, '_render_terminal_input_action'),
        (TerminalReadAction, '_render_terminal_read_action'),
        (DelegateTaskAction, '_render_delegate_task_action'),
        (PlaybookFinishAction, '_render_playbook_finish_action'),
        (EscalateToHumanAction, '_render_escalate_to_human_action'),
        (ClarificationRequestAction, '_render_clarification_request_action'),
        (UncertaintyAction, '_render_uncertainty_action'),
        (ProposalAction, '_render_proposal_action'),
    )

    _NO_MATCH_FRAGMENTS: tuple[str, ...] = (
        'No matches found.',
        'No matching files found',
    )

    _FILE_EDIT_VERBS: dict[str, tuple[str, bool]] = {
        # cmd → (verb, include_stats)
        'read_file': ('Read', False),
        'create_file': ('Created', False),
        'insert_text': ('Inserted', True),
        'undo_last_edit': ('Reverted', False),
        'write': ('Wrote', False),
    }

    def _handle_agent_action(self, action: Action) -> None:
        """Dispatch *action* to the appropriate ``_render_*_action`` handler."""
        for action_type, method_name in self._AGENT_ACTION_DISPATCH:
            if isinstance(action, action_type):
                # Most handlers do their own ``_clear_streaming_preview`` /
                # flush calls; only ``AgentThinkAction`` is allowed to skip
                # the preview clear so reasoning text keeps rendering.
                if action_type is not AgentThinkAction and action_type is not (
                    StreamingChunkAction
                ) and action_type is not MessageAction:
                    self._clear_streaming_preview()
                getattr(self, method_name)(action)
                return
        self.refresh()

    # -- Per-action renderers (small, single-CC dispatch targets) -----------

    def _render_streaming_chunk_action(self, action: StreamingChunkAction) -> None:
        self._handle_streaming_chunk(action)

    def _render_message_action(self, action: MessageAction) -> None:
        self._flush_pending_tool_cards()
        # Suppress mid-task internal messages that were intercepted by the
        # event router (e.g. verbose model text between checkpoint and next
        # tool call). Still clear the streaming preview and stop reasoning
        # so Live panel doesn't linger.
        if bool(getattr(action, 'suppress_cli', False)):
            self._stop_reasoning()
            self._clear_streaming_preview()
            self.refresh()
            return
        cot = (getattr(action, 'thought', None) or '').strip()
        if cot and _show_reasoning_text():
            cleaned_cot = _sanitize_visible_transcript_text(cot)
            if cleaned_cot:
                self._ensure_reasoning()
                self._reasoning.update_thought(cleaned_cot)
        self._stop_reasoning()
        self._clear_streaming_preview()
        display_content = _sanitize_visible_transcript_text(action.content or '')
        if not display_content:
            self.refresh()
            return
        attachments = self._message_action_attachments(action)
        self._append_assistant_message(display_content, attachments=attachments)

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
        self._apply_reasoning_text(thought)
        self.refresh()

    def _render_tool_sourced_think(self, source_tool: str, thought: str) -> None:
        """Render an ``AgentThinkAction`` that originated from a tool call."""
        cleaned = _THINK_RESULT_JSON_RE.sub('', thought).strip()
        tag_m = _INTERNAL_THINK_TAG_RE.match(cleaned)
        human_msg = (tag_m.group('payload') or '').strip() if tag_m else cleaned
        human_msg = _TOOL_RESULT_TAG_RE.sub('', human_msg).strip()

        verb, title, detail = self._think_action_card_fields(source_tool, human_msg)
        self._emit_activity_turn_header()
        kind = 'err' if 'Failure' in (human_msg or '') else 'ok'
        self._print_or_buffer(
            Padding(
                format_activity_block(
                    verb, detail, secondary=None, secondary_kind=kind, title=title,
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
        if source_tool == 'search_code':
            detail = cls._search_code_detail(human_msg or '')
            return 'Search Code', ACTIVITY_CARD_TITLE_SEARCH, detail
        verb = source_tool.replace('_', ' ').title()
        return verb, ACTIVITY_CARD_TITLE_TOOL, str(human_msg)[:150] or source_tool

    @classmethod
    def _search_code_detail(cls, human_msg: str) -> str:
        lines = [
            ln
            for ln in human_msg.splitlines()
            if ln.strip() and not ln.startswith('Error running ripgrep:')
        ]
        if not lines:
            return 'No matches found.'
        head_blob = '\n'.join(lines[:5])
        if any(frag in head_blob for frag in cls._NO_MATCH_FRAGMENTS):
            return 'No matches found.'
        match_count = sum(
            1 for line in lines if re.match(r'^.*:\d+:', line)
        ) or len(lines)
        return f'Found {match_count} match lines.'

    def _render_cmd_run_action(self, action: CmdRunAction) -> None:
        self._flush_pending_activity_card()
        if getattr(action, 'hidden', False):
            self.refresh()
            return
        # Flush any previous buffered command that never received an observation
        if self._pending_shell_action is not None:
            self._flush_pending_shell_action()
        display_label = (getattr(action, 'display_label', '') or '').strip()
        if display_label:
            self._buffer_internal_shell_command(action, display_label)
            return
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
            end_str = f'L{end}' if end != -1 else 'end'
            verb, detail = 'Edited', f'{path} · L{start}:{end_str}'
        else:
            verb, detail = 'Edited', path
        self._buffer_pending_activity(
            title=ACTIVITY_CARD_TITLE_FILES,
            verb=verb,
            detail=detail,
            secondary=stats,
            kind='file_edit',
        )
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(self._reasoning, f'{verb} {detail}', thought)
        self.refresh()

    def _render_file_write_action(self, action: FileWriteAction) -> None:
        self._flush_pending_tool_cards()
        content = getattr(action, 'content', '') or ''
        n_lines = len(content.splitlines()) if content else 0
        self._buffer_pending_activity(
            title=ACTIVITY_CARD_TITLE_FILES,
            verb='Created',
            detail=action.path,
            kind='file_write',
            payload={'line_count': n_lines},
        )
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(
            self._reasoning, f'Created {action.path}', thought
        )
        self.refresh()

    def _render_recall_action(self, action: RecallAction) -> None:
        self._flush_pending_tool_cards()
        query = getattr(action, 'query', '')
        detail = query or 'workspace context'
        if len(detail) > 100:
            detail = detail[:97] + '…'
        self._print_activity('Recalled', detail, None, title=ACTIVITY_CARD_TITLE_MEMORY)
        self.refresh()

    def _render_file_read_action(self, action: FileReadAction) -> None:
        self._flush_pending_tool_cards()
        path = getattr(action, 'path', '')
        view_range = getattr(action, 'view_range', None)
        start = getattr(action, 'start', 0)
        end = getattr(action, 'end', -1)
        if view_range and len(view_range) == 2:
            detail = f'{path} · L{view_range[0]}:L{view_range[1]}'
        elif start not in (0, 1) or end != -1:
            end_str = str(end) if end != -1 else 'end'
            detail = f'{path} · L{start}:{end_str}'
        else:
            detail = path
        self._buffer_pending_activity(
            title=ACTIVITY_CARD_TITLE_FILES,
            verb='Viewed',
            detail=detail,
            kind='file_read',
        )
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(self._reasoning, f'Viewed {path}', thought)
        self.refresh()

    def _render_mcp_action(self, action: MCPAction) -> None:
        self._flush_pending_tool_cards()
        name = getattr(action, 'name', 'tool')
        raw_args = getattr(action, 'arguments', None) or {}
        args_dict = raw_args if isinstance(raw_args, dict) else {}
        verb, detail, stats = format_tool_activity_rows(name, args_dict)
        self._buffer_pending_activity(
            title=ACTIVITY_CARD_TITLE_MCP,
            verb=verb,
            detail=detail,
            secondary=stats,
            kind='mcp',
        )
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(self._reasoning, f'{verb} {detail}', thought)
        self.refresh()

    def _render_browser_tool_action(self, action: BrowserToolAction) -> None:
        self._flush_pending_tool_cards()
        cmd = getattr(action, 'command', '') or 'browser'
        params = getattr(action, 'params', None) or {}
        url = params.get('url') if isinstance(params, dict) else None
        detail = str(url)[:80] if url else str(cmd)
        self._print_activity(str(cmd), detail, None, title=ACTIVITY_CARD_TITLE_BROWSER)
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(self._reasoning, detail, thought)
        self.refresh()

    def _render_browse_interactive_action(
        self, action: BrowseInteractiveAction
    ) -> None:
        self._flush_pending_tool_cards()
        browser_actions = getattr(action, 'browser_actions', '') or ''
        url_match = re.search(r'https?://[^\s\'")\]]+', browser_actions)
        if url_match:
            detail = url_match.group(0)[:80]
        else:
            detail = 'interactive session'
        self._print_activity('Opened', detail, None, title=ACTIVITY_CARD_TITLE_BROWSER)
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(self._reasoning, detail, thought)
        self.refresh()

    def _render_lsp_query_action(self, action: LspQueryAction) -> None:
        self._flush_pending_tool_cards()
        cmd = getattr(action, 'command', 'query')
        file = getattr(action, 'file', '')
        symbol = getattr(action, 'symbol', '')
        detail = symbol or file
        stats = str(cmd) if cmd else None
        self._buffer_pending_activity(
            title=ACTIVITY_CARD_TITLE_CODE,
            verb='Analyzed',
            detail=detail,
            secondary=stats,
            kind='lsp',
        )
        self.refresh()

    def _render_task_tracking_action(self, action: TaskTrackingAction) -> None:
        command = str(getattr(action, 'command', '') or '').strip().lower()
        task_list = getattr(action, 'task_list', None)
        if command == 'update' and isinstance(task_list, list):
            self._set_task_panel(task_list)
        self.refresh()

    def _render_condensation_action(self, action: CondensationAction) -> None:
        del action
        self._ensure_reasoning()
        self._reasoning.update_action('Compressing context…')
        self.refresh()

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
            'Run', cmd_detail, None, title=ACTIVITY_CARD_TITLE_TERMINAL
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
        )
        self.refresh()

    def _render_playbook_finish_action(self, action: PlaybookFinishAction) -> None:
        self._flush_pending_tool_cards()
        self._stop_reasoning()
        # Buffer the finish text — do NOT render it yet.  The validation
        # service may still block this finish call; ``_handle_state_change``
        # renders it once the agent actually reaches AgentState.FINISHED.
        finish_text = _sanitize_visible_transcript_text(action.message or '')
        self._pending_finish_text = finish_text or None
        self.refresh()

    def _render_escalate_to_human_action(self, action: EscalateToHumanAction) -> None:
        self._flush_pending_tool_cards()
        self._stop_reasoning()
        reason = getattr(action, 'reason', '')
        help_needed = getattr(action, 'specific_help_needed', '')
        escalate_parts: list[Any] = []
        if reason:
            escalate_parts.append(Text(reason, style='yellow'))
        if help_needed:
            escalate_parts.append(Text(f'Help needed: {help_needed}', style='yellow'))
        if not escalate_parts:
            escalate_parts.append(
                Text('The agent needs your input to continue.', style='yellow')
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
            clarify_parts.append(Text(question, style='yellow'))
        for i, opt in enumerate(options, 1):
            option_line = Text()
            option_line.append(f'{i}. ', style='bold #f1bf63')
            option_line.append(str(opt), style='#e2e8f0')
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
            concern_line.append('• ', style='dim')
            concern_line.append(str(concern), style='dim')
            uncertainty_parts.append(concern_line)
        if info_needed:
            uncertainty_parts.append(Text(f'Need: {info_needed}', style='yellow'))
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
            proposal_parts.append(Text(rationale, style='dim'))
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
                style='bold #f1bf63' if i == recommended else 'bold #e2e8f0',
            )
            proposal_parts.append(proposal_line)
            if desc:
                proposal_parts.append(Text(f'   {desc}', style='dim'))
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
