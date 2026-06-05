"""_AppRendererEventProcessorMixin: event drain/activity + per-event processing + diff extraction."""

from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path
from typing import Any

from rich.markdown import (
    Markdown,
)
from rich.text import (
    Text,
)

from backend.cli._event_renderer.text_utils import (
    truncate_activity_detail,
)
from backend.cli._event_renderer.unified_renderer import (
    ActivityRenderer,
)
from backend.cli.theme import (
    NAVY_TEXT_DIM,
    NAVY_TEXT_MUTED,
    NAVY_TEXT_PRIMARY,
)
from backend.cli.transcript import (
    strip_tool_result_validation_annotations,
)
from backend.cli.tui._app_constants import (
    _TUI_HISTORY_RENDER_LIMIT,
    _TUI_PENDING_EVENT_LIMIT,
)
from backend.cli.tui._app_helpers import (
    _count_text_lines,
    _count_unified_diff_changes,
    _encode_split_diff_contents,
    _encode_unified_diff_text,
    _extract_tagged_block,
    _format_diff_summary,
    _join_secondary_parts,
    _sanitize_terminal_display_text,
    _split_combined_diff,
)
from backend.cli.tui._app_small_widgets import (
    RendererDrainRequested,
)
from backend.core.workspace_resolution import (
    resolve_cli_workspace_directory,
)
from backend.ledger.action import (
    AgentThinkAction,
    BrowseInteractiveAction,
    BrowserToolAction,
    ChangeAgentStateAction,
    ClarificationRequestAction,
    CmdRunAction,
    CondensationAction,
    CondensationRequestAction,
    ConfirmRequestAction,
    DelegateTaskAction,
    EscalateToHumanAction,
    FileEditAction,
    FileReadAction,
    FileWriteAction,
    InformAction,
    LspQueryAction,
    MCPAction,
    MessageAction,
    NullAction,
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
from backend.ledger.observation import (
    AgentCondensationObservation,
    AgentStateChangedObservation,
    AgentThinkObservation,
    BrowserScreenshotObservation,
    CmdOutputObservation,
    DelegateTaskObservation,
    ErrorObservation,
    FileDownloadObservation,
    FileEditObservation,
    FileReadObservation,
    FileWriteObservation,
    LspQueryObservation,
    MCPObservation,
    NullObservation,
    RecallFailureObservation,
    RecallObservation,
    ServerReadyObservation,
    StatusObservation,
    SuccessObservation,
    TaskTrackingObservation,
    TerminalObservation,
    UserRejectObservation,
)
from backend.orchestration.autonomy import normalize_autonomy_level


class _AppRendererEventProcessorMixin:
    """event drain/activity + per-event processing + diff extraction."""

    @staticmethod
    def _compact_file_card_path(path: str) -> str:
        """Keep file tool card headlines to one compact row."""
        return truncate_activity_detail(path or '?', 80)

    def _remember_pending_file_card(self, attr: str, path: str, widget: Any) -> None:
        queues = getattr(self, attr, None)
        if queues is None:
            return
        queues[(path or '').strip()].append(widget)

    def _take_pending_file_card(self, attr: str, path: str) -> Any | None:
        queues = getattr(self, attr, None)
        if queues is None:
            return None
        key = (path or '').strip()
        queue = queues.get(key)
        if not queue:
            return None
        widget = queue.popleft()
        if not queue:
            queues.pop(key, None)
        return widget

    def _has_pending_file_card(self, attr: str, path: str) -> bool:
        queues = getattr(self, attr, None)
        if queues is None:
            return False
        queue = queues.get((path or '').strip())
        return bool(queue)

    def _is_full_autonomy(self) -> bool:
        controller = getattr(self._tui, '_controller', None)
        ac = getattr(controller, 'autonomy_controller', None)
        raw_level = getattr(ac, 'autonomy_level', '') if ac is not None else ''
        level = normalize_autonomy_level(raw_level)
        if level:
            return level == 'full'
        hud = getattr(self._tui, '_hud', None)
        state = getattr(hud, 'state', None)
        return normalize_autonomy_level(getattr(state, 'autonomy_level', '')) == 'full'

    def drain_events(self) -> None:
        with self._pending_lock:
            events = list(self._pending_events)
            self._pending_events.clear()
            self._drain_scheduled = False
            dropped = self._pending_events_dropped
            self._pending_events_dropped = 0
        if not events:
            self._refresh_display()  # Keep sidebar/HUD in sync
            return
        if dropped:
            self._history.append(
                Text(
                    f'... {dropped} TUI event(s) dropped while the renderer was backlogged ...',
                    style=NAVY_TEXT_DIM,
                )
            )
            self._history.append(Text(''))
            overflow = len(self._history) - _TUI_HISTORY_RENDER_LIMIT
            if overflow > 0:
                del self._history[:overflow]
        for event in events:
            self._process_event(event)
        self._refresh_display()

    async def wait_for_activity(self, wait_timeout_sec: float = 0.5) -> Any:
        with self._pending_lock:
            has_pending = bool(self._pending_events)
        if has_pending:
            self.drain_events()
            self._state_event.clear()
            return self._current_state
        try:
            await asyncio.wait_for(self._state_event.wait(), timeout=wait_timeout_sec)
        except TimeoutError:
            return None
        finally:
            self._state_event.clear()
        self.drain_events()
        return self._current_state

    def _on_event(self, event: Any) -> None:
        should_schedule_drain = False
        with self._pending_lock:
            if len(self._pending_events) >= _TUI_PENDING_EVENT_LIMIT:
                self._pending_events.popleft()
                self._pending_events_dropped += 1
            self._pending_events.append(event)
            if not self._drain_scheduled:
                self._drain_scheduled = True
                should_schedule_drain = True
        try:
            self._loop.call_soon_threadsafe(
                self._signal_activity,
                should_schedule_drain,
            )
        except RuntimeError:
            pass

    def _signal_activity(self, should_schedule_drain: bool) -> None:
        self._state_event.set()
        if not should_schedule_drain:
            return
        try:
            self._tui.post_message(RendererDrainRequested())
        except Exception:
            with self._pending_lock:
                self._drain_scheduled = False

    def _is_live_thinking_event(self, event: Any) -> bool:
        if isinstance(event, AgentThinkAction):
            if bool(getattr(event, 'suppress_cli', False)):
                return False
            thought = getattr(event, 'thought', '') or getattr(event, 'content', '')
            source_tool = getattr(event, 'source_tool', '') or ''
            kind = getattr(event, 'kind', '') or ''
            intent = self._classify_thinking_text(
                thought, source_tool=source_tool, kind=kind
            )
            return intent.kind == 'thinking'
        if isinstance(event, AgentThinkObservation):
            thought = getattr(event, 'thought', '') or getattr(event, 'content', '')
            kind = getattr(event, 'kind', '') or ''
            intent = self._classify_thinking_text(thought, kind=kind)
            return intent.kind == 'thinking'
        return isinstance(event, StreamingChunkAction)

    def _show_compaction_started_card(self) -> None:
        """Ensure an in-progress compaction is visible in the transcript."""
        if getattr(self, '_compaction_transcript_active', False):
            return
        count = max(self._condensation_count + 1, 1)
        self._condensation_count = count
        self._compaction_transcript_active = True
        card = ActivityRenderer.condensation(count=count)
        self._write_card(card)
        self._hud.update_condensation_count(count)

    def _process_event(self, event: Any) -> None:
        self._update_metrics(event)
        if isinstance(event, NullAction) or isinstance(event, NullObservation):
            return
        if isinstance(event, ChangeAgentStateAction):
            return

        source = getattr(event, 'source', None)
        if isinstance(event, MessageAction) and self._is_user_source(source):
            self._last_thinking_text_hash = ''
            self._last_thinking_artifact_hash = ''

        # Detect start of agent turn (first tool action after user input)
        if not self._in_agent_turn and not isinstance(
            event, (MessageAction, StreamingChunkAction, AgentStateChangedObservation)
        ):
            self._in_agent_turn = True
            self._turn_count += 1
            self._tools_in_turn = 0
            self._turn_start_time = time.monotonic()

        # Count tools in current turn
        is_tool_execution_event = isinstance(
            event,
            (
                FileReadAction,
                FileEditAction,
                FileWriteAction,
                CmdRunAction,
                MCPAction,
                BrowserToolAction,
                BrowseInteractiveAction,
                LspQueryAction,
                TerminalRunAction,
                TerminalInputAction,
                TerminalReadAction,
                RecallAction,
                DelegateTaskAction,
            ),
        )
        if self._in_agent_turn and is_tool_execution_event:
            self._tools_in_turn += 1

        if not self._is_live_thinking_event(event) and not getattr(self, '_streaming_active', False):
            self._finalize_live_thinking()

        if not isinstance(event, (MessageAction, StreamingChunkAction)):
            if self._live_response_dirty:
                if is_tool_execution_event:
                    self.clear_live_response()
                else:
                    self._commit_final_response(self._live_response)
            else:
                self.clear_live_response()

        if isinstance(event, MessageAction):
            if self._is_user_source(source):
                return
            self._handle_message_action(event)
        elif isinstance(event, FileReadAction):
            path = getattr(event, 'path', '')
            view_range = getattr(event, 'view_range', None)
            start = getattr(event, 'start', 0)
            end = getattr(event, 'end', -1)
            if view_range and len(view_range) == 2:
                line_range = f'{view_range[0]}:{view_range[1]}'
            elif start not in (0, 1) or end != -1:
                end_str = str(end) if end != -1 else 'end'
                line_range = f'{start}:{end_str}'
            else:
                line_range = ''
            card = ActivityRenderer.file_read(
                self._compact_file_card_path(path),
                line_range,
            )
            widget = self._write_card(card)
            self._remember_pending_file_card(
                '_pending_file_read_cards_by_path',
                path,
                widget,
            )
        elif isinstance(event, FileEditAction):
            cmd = getattr(event, 'command', '')
            path = event.path
            insert_line = getattr(event, 'insert_line', None)
            start = getattr(event, 'start', 1)
            end = getattr(event, 'end', -1)
            start_line = getattr(event, 'start_line', None)
            end_line = getattr(event, 'end_line', None)

            verb_entry = self._FILE_EDIT_VERBS.get(cmd)
            if verb_entry is not None:
                verb, include_stats = verb_entry
                if include_stats and insert_line is not None:
                    line_range = f'line {insert_line}'
                else:
                    line_range = ''
            elif not cmd:
                end_str = str(end) if end != -1 else 'end'
                verb = 'Edited'
                line_range = f'{start}:{end_str}'
            elif cmd == 'edit':
                edit_mode = getattr(event, 'edit_mode', '')
                if (
                    edit_mode == 'range'
                    and start_line is not None
                    and end_line is not None
                ):
                    verb = 'Edited'
                    line_range = f'{start_line}:{end_line}'
                else:
                    verb = 'Edited'
                    line_range = ''
            else:
                verb = 'Edited'
                line_range = ''

            if cmd == 'create_file':
                file_text = getattr(event, 'file_text', '') or ''
                if self._has_pending_file_card(
                    '_pending_file_create_cards_by_path',
                    path,
                ):
                    return
                card = ActivityRenderer.file_create(
                    self._compact_file_card_path(path),
                    line_count=_count_text_lines(file_text),
                )
                widget = self._write_card(card)
                self._remember_pending_file_card(
                    '_pending_file_create_cards_by_path',
                    path,
                    widget,
                )
            else:
                op_detail = f'{path} · {line_range}' if line_range else path
                self._tui.set_current_operation(
                    f'{verb} {op_detail}'.strip(),
                    meta='Running',
                    active=True,
                )
        elif isinstance(event, FileWriteAction):
            content = getattr(event, 'content', '') or ''
            card = ActivityRenderer.file_create(
                self._compact_file_card_path(event.path),
                line_count=_count_text_lines(content),
            )
            self._write_card(card)
        elif isinstance(event, FileReadObservation):
            path = getattr(event, 'path', '') or ''
            pending = self._take_pending_file_card(
                '_pending_file_read_cards_by_path',
                path,
            )
            operation_label = f'Read {self._compact_file_card_path(path)}'.strip()
            if pending is not None:
                self._update_activity_card_outcome(
                    pending,
                    status='ok',
                    operation_label=operation_label,
                )
            else:
                card = ActivityRenderer.file_read(self._compact_file_card_path(path))
                card.secondary_kind = 'ok'
                self._write_card(card)
        elif isinstance(event, FileEditObservation):
            # Strip agent-facing indentation warnings from user-visible content
            from backend.cli.transcript import strip_indentation_warnings

            if hasattr(event, 'content') and event.content:
                event.content = strip_indentation_warnings(event.content)

            path = (getattr(event, 'path', '') or '').strip()
            added = event.added
            removed = event.removed
            pending_create = self._take_pending_file_card(
                '_pending_file_create_cards_by_path',
                path,
            )
            if pending_create is not None:
                new_content = getattr(event, 'new_content', '') or ''
                line_count = added or _count_text_lines(new_content)
                self._update_activity_card_outcome(
                    pending_create,
                    status='ok',
                    outcome=f'+{line_count}' if line_count else None,
                    operation_label=f'Created {self._compact_file_card_path(path)}'.strip(),
                )
                return

            if not getattr(event, 'prev_exist', True):
                new_content = getattr(event, 'new_content', '') or ''
                card = ActivityRenderer.file_create(
                    self._compact_file_card_path(path or event.path),
                    line_count=added or _count_text_lines(new_content),
                )
                self._write_card(card)
            elif not path or path == '.':
                # Multi-file edit — split combined diff into per-file cards
                diff_text = self._extract_file_edit_diff(event)
                if diff_text:
                    per_file = _split_combined_diff(diff_text)
                    if per_file:
                        for fp, file_diff in per_file:
                            f_added, f_removed = _count_unified_diff_changes(file_diff)
                            encoded = _encode_unified_diff_text(file_diff)
                            if encoded:
                                self._write_tui_file_card(
                                    'Edited',
                                    fp,
                                    secondary=_format_diff_summary(f_added, f_removed),
                                    secondary_kind='ok' if f_added else 'neutral',
                                    extra_content=encoded,
                                )
                    else:
                        self._write_card(
                            ActivityRenderer.file_edit('Edited', path or '?')
                        )
                else:
                    self._write_card(ActivityRenderer.file_edit('Edited', path or '?'))
            else:
                encoded_diff = self._extract_file_edit_group_rows(event)
                diff_text = None
                if not encoded_diff:
                    diff_text = self._extract_file_edit_diff(event)
                    if not (added or removed):
                        added, removed = _count_unified_diff_changes(diff_text)
                    encoded_diff = (
                        _encode_unified_diff_text(diff_text) if diff_text else None
                    )
                if encoded_diff:
                    self._write_tui_file_card(
                        'Edited',
                        path,
                        secondary=_format_diff_summary(added, removed),
                        secondary_kind='ok' if added and not removed else 'neutral',
                        extra_content=encoded_diff,
                    )
                else:
                    card = ActivityRenderer.file_edit(
                        'Edited',
                        path,
                        added=added,
                        removed=removed,
                    )
                    self._write_card(card)
        elif isinstance(event, FileWriteObservation):
            diff_text = self._extract_file_observation_diff(event)
            if diff_text:
                encoded_diff = _encode_unified_diff_text(diff_text)
                added, removed = _count_unified_diff_changes(diff_text)
                self._write_tui_file_card(
                    'Edited',
                    event.path,
                    secondary=_format_diff_summary(added, removed),
                    secondary_kind='ok' if added and not removed else 'neutral',
                    extra_content=encoded_diff,
                )
        elif isinstance(event, MCPAction):
            card = ActivityRenderer.mcp_tool(event.name, event.arguments)
            widget = self._write_card(card)
            self._pending_mcp_card = widget
        elif isinstance(event, CmdRunAction):
            cmd = getattr(event, 'command', '') or ''
            if not getattr(event, 'hidden', False):
                self._create_shell_command_card(cmd)
        elif isinstance(event, MCPObservation):
            card = ActivityRenderer.mcp_tool(
                event.name,
                event.arguments,
                result=event.content or '',
                success=True,
            )
            preview = None
            if event.content:
                truncated = event.content[:200] + (
                    '...' if len(event.content) > 200 else ''
                )
                preview = f'  {truncated}'
            pending = self._pending_mcp_card
            if pending is not None:
                self._update_activity_card_outcome(
                    pending,
                    status='ok',
                    outcome='completed',
                    extra_content=preview,
                    operation_label=f'Called {event.name}'.strip(),
                )
                self._pending_mcp_card = None
            else:
                self._write_card(card)
        elif isinstance(event, CmdOutputObservation):
            output = (event.content or '').strip()
            exit_code = getattr(event, 'exit_code', None)
            cmd = getattr(event, 'command', '') or ''
            cwd = (
                getattr(event.metadata, 'working_dir', None)
                if hasattr(event, 'metadata') and event.metadata
                else None
            )
            if output:
                output = _sanitize_terminal_display_text(
                    strip_tool_result_validation_annotations(output)
                ).strip()
            if output or exit_code is not None:
                self._complete_shell_command_card(
                    cmd,
                    output=output[:500],
                    exit_code=exit_code,
                    cwd=cwd,
                )
        elif isinstance(event, ErrorObservation):
            self._compaction_transcript_active = False
            content = event.content or 'An unknown error occurred'
            # User-facing LLM/provider/config failures keep the red ✗ marker;
            # everything else (tool validation, no-tool-call, capability
            # outcomes, etc.) is a recoverable issue the agent retries on.
            if getattr(event, 'notify_ui_only', False):
                self._tui.add_error(content)
            else:
                self._tui.add_warning(content)
        elif isinstance(event, SuccessObservation):
            self._compaction_transcript_active = False
            self._clear_retry_strip('Recovered')
            self._clear_runtime_status('Recovered')
            self._tui.add_success(event.content or 'Done')
        elif isinstance(event, StatusObservation):
            status_type = str(getattr(event, 'status_type', '') or '')
            extras = getattr(event, 'extras', None) or {}
            if status_type in (
                'retry_pending',
                'retry_resuming',
                'llm_retry_pending',
                'llm_retry_resuming',
            ):
                label, last_status, message = self._format_retry_status_message(
                    status_type, extras
                )
                self._hud.update_ledger('Backoff')
                self._hud.update_agent_state(label)
                self._tui.set_agent_phase(label)
                self._update_retry_strip(label, message)
                return
            if status_type == 'compaction':
                self._clear_retry_strip('Idle')
                self._hud.update_agent_state('Compacting')
                self._tui.set_agent_phase('Compacting context...')
                self._update_runtime_strip(
                    'Compacting context',
                    'Reducing context to continue the task',
                    active=True,
                )
                self._show_compaction_started_card()
                return
            msg = (event.content or '').strip()
            if msg:
                summary = (
                    status_type.replace('_', ' ').strip().title()
                    if status_type
                    else 'Runtime notice'
                )
                self._update_runtime_strip(summary, msg, active=False)
        elif isinstance(event, AgentThinkAction):
            source_tool = getattr(event, 'source_tool', '') or ''
            thought = getattr(event, 'thought', '') or getattr(event, 'content', '')
            kind = getattr(event, 'kind', '') or ''
            self._render_thinking_payload(
                thought, source_tool=source_tool, kind=kind
            )
        elif isinstance(event, AgentThinkObservation):
            thought = getattr(event, 'thought', '') or getattr(event, 'content', '')
            kind = getattr(event, 'kind', '') or ''
            self._render_thinking_payload(thought, kind=kind)
        elif isinstance(event, BrowserToolAction):
            action_name = getattr(event, 'command', 'browser') or 'browser'
            url = ''
            if action_name == 'navigate':
                url = (getattr(event, 'params', {}) or {}).get('url', '')
            elif action_name == 'click':
                selector = (getattr(event, 'params', {}) or {}).get('selector', '')
                url = selector[:80] if selector else ''
            card = ActivityRenderer.browser_action(action_name, url)
            widget = self._write_card(card)
            self._last_browser_action_card = widget
            self._last_browser_cmd = action_name
        elif isinstance(event, BrowseInteractiveAction):
            actions = getattr(event, 'browser_actions', '') or ''
            detail = (
                actions[:80] + ('...' if len(actions) > 80 else '') if actions else ''
            )
            card = ActivityRenderer.browser_action('browse', detail)
            widget = self._write_card(card)
            self._last_browser_action_card = widget
            self._last_browser_cmd = 'browse'
        elif isinstance(event, BrowserScreenshotObservation):
            url = getattr(event, 'image_path', '') or ''
            content = (event.content or '').strip()
            card = ActivityRenderer.browser_action(
                'screenshot', url, result=content or 'captured'
            )
            prev = getattr(self, '_last_browser_action_card', None)
            last_cmd = getattr(self, '_last_browser_cmd', '') or ''
            if prev is not None and last_cmd not in ('', 'screenshot'):
                extra_parts = []
                if url:
                    extra_parts.append(f'URL: {url}')
                if content:
                    extra_parts.append(content[:200])
                preview = '\n'.join(extra_parts) if extra_parts else None
                self._update_activity_card_outcome(
                    prev,
                    status='ok',
                    outcome='done',
                    extra_content=preview,
                    operation_label=f'Browser {last_cmd}'.strip(),
                )
                self._last_browser_action_card = None
            else:
                self._write_card(card)
        elif isinstance(event, LspQueryAction):
            symbol = getattr(event, 'symbol', '') or getattr(event, 'query', '') or ''
            card = ActivityRenderer.lsp_query(symbol)
            widget = self._write_card(card)
            self._pending_lsp_card = widget
        elif isinstance(event, LspQueryObservation):
            content = (event.content or '').strip()
            symbol = getattr(event, 'symbol', '') or ''
            available = bool(getattr(event, 'available', True))
            card = ActivityRenderer.lsp_query(
                symbol, result=content, available=available
            )
            preview = None
            if content:
                truncated = content[:200] + ('...' if len(content) > 200 else '')
                preview = f'  {truncated}'
            pending = self._pending_lsp_card
            if pending is not None:
                status = 'ok' if available else 'err'
                self._update_activity_card_outcome(
                    pending,
                    status=status,
                    outcome=card.secondary or 'completed',
                    extra_content=preview,
                    operation_label=f'Analyzed {symbol}'.strip(),
                )
                self._pending_lsp_card = None
            else:
                self._write_card(card)
        elif isinstance(event, TerminalRunAction):
            cmd = getattr(event, 'command', '') or ''
            session_id = getattr(event, 'session_id', '') or ''
            detail = self._terminal_card_detail(session_id, cmd)
            self._upsert_terminal_session_card(
                session_id=session_id,
                verb='Started',
                detail=detail,
                secondary=_join_secondary_parts(
                    self._terminal_session_label(session_id),
                    'starting session',
                ),
                secondary_kind='neutral',
                processing=True,
            )
        elif isinstance(event, TerminalInputAction):
            session_id = getattr(event, 'session_id', '') or ''
            submitted = _sanitize_terminal_display_text(
                getattr(event, 'input', '') or ''
            )
            detail = self._terminal_card_detail(session_id, submitted)
            self._upsert_terminal_session_card(
                session_id=session_id,
                verb='Sent',
                detail=detail,
                secondary=_join_secondary_parts(
                    self._terminal_session_label(session_id),
                    'awaiting output',
                ),
                secondary_kind='neutral',
                extra_content=f'$ {submitted.rstrip()}' if submitted.strip() else None,
                processing=True,
            )
        elif isinstance(event, TerminalReadAction):
            session_id = getattr(event, 'session_id', '') or ''
            self._upsert_terminal_session_card(
                session_id=session_id,
                verb='Reading',
                detail=self._terminal_card_detail(session_id),
                secondary=_join_secondary_parts(
                    self._terminal_session_label(session_id),
                    'streaming output',
                ),
                secondary_kind='neutral',
                processing=True,
            )
        elif isinstance(event, TerminalObservation):
            content = event.content or ''
            session_id = getattr(event, 'session_id', '') or ''
            exit_code = getattr(event, 'exit_code', None)
            state = getattr(event, 'state', None)
            secondary = _join_secondary_parts(
                self._terminal_session_label(session_id),
                (f'exit {exit_code}' if exit_code is not None else (state or None)),
            )
            secondary_kind = (
                'ok'
                if exit_code == 0
                else ('err' if exit_code is not None and exit_code != 0 else 'neutral')
            )
            if content:
                content = _sanitize_terminal_display_text(
                    strip_tool_result_validation_annotations(content)
                ).strip()
            self._upsert_terminal_session_card(
                session_id=session_id,
                verb='Output',
                detail=self._terminal_card_detail(session_id),
                secondary=secondary,
                secondary_kind=secondary_kind,
                extra_content=content or None,
                processing=exit_code is None,
                collapse_after_update=exit_code == 0 and bool(content),
            )
        elif isinstance(event, RecallAction):
            # Don't show memory recall as a visible card - it's an internal operation
            pass
        elif isinstance(event, CondensationRequestAction):
            self._show_compaction_started_card()
        elif isinstance(event, RecallObservation):
            pass
        elif isinstance(event, RecallFailureObservation):
            pass
        elif isinstance(event, CondensationAction):
            self._show_compaction_started_card()
        elif isinstance(event, AgentCondensationObservation):
            self._compaction_transcript_active = False
            self._update_runtime_strip(
                'Context compacted',
                'Context compressed successfully',
                active=False,
            )
            count = max(self._condensation_count, 1)
            self._condensation_count = count
            self._hud.update_condensation_count(count)
            card = ActivityRenderer.condensation(count=count, result=event.content)
            self._write_card(card)
        elif isinstance(event, DelegateTaskAction):
            task = (
                getattr(event, 'task_description', '')
                or getattr(event, 'task', '')
                or ''
            )
            worker = getattr(event, 'worker', '') or ''
            if getattr(event, 'parallel_tasks', None):
                for item in list(getattr(event, 'parallel_tasks', []) or []):
                    task_desc = self._summarize_worker_task(
                        str(item.get('task_description') or 'delegated task')
                    )
                    self._active_worker_tasks.append(task_desc)
            else:
                self._active_worker_tasks.append(self._summarize_worker_task(task))
            self._sync_worker_strip()
            card = ActivityRenderer.delegation(task, worker)
            widget = self._write_card(card)
            self._pending_delegate_card = widget
        elif isinstance(event, DelegateTaskObservation):
            content = (event.content or '').strip()
            success = bool(getattr(event, 'success', True))
            error_message = (getattr(event, 'error_message', '') or '').strip()
            resolved_task = (
                self._active_worker_tasks.pop(0)
                if self._active_worker_tasks
                else 'delegated task'
            )
            if success:
                self._worker_completed += 1
                if resolved_task:
                    self._worker_recent_results.append(f'ok: {resolved_task}')
            else:
                self._worker_failed += 1
                if resolved_task:
                    self._worker_recent_results.append(f'fail: {resolved_task}')
            self._sync_worker_strip()
            card = ActivityRenderer.delegation(
                resolved_task,
                result=error_message or content,
                success=success,
            )
            preview = None
            detail = error_message or content
            if detail:
                truncated = detail[:200] + ('...' if len(detail) > 200 else '')
                preview = f'  {truncated}'
            pending = self._pending_delegate_card
            if pending is not None:
                self._update_activity_card_outcome(
                    pending,
                    status='ok' if success else 'err',
                    outcome='completed' if success else 'failed',
                    extra_content=preview,
                    operation_label=f'Delegated {resolved_task}'.strip(),
                )
                self._pending_delegate_card = None
            else:
                self._write_card(card)
        elif isinstance(event, PlaybookFinishAction):
            from backend.cli.plan_display import is_structured_plan_finish
            from backend.cli.tui.widgets.activity_card import PlanMessage

            if is_structured_plan_finish(event):
                self._tui._write_log(PlanMessage(event))
            else:
                message = getattr(event, 'message', '') or ''
                if message:
                    from backend.cli.theme import get_grinta_pygments_style

                    self._tui._write_log(
                        Markdown(message, code_theme=get_grinta_pygments_style())
                    )
        elif isinstance(event, UserRejectObservation):
            card = ActivityRenderer.user_reject()
            self._write_card(card)
        elif isinstance(event, ServerReadyObservation):
            url = getattr(event, 'url', '')
            port = getattr(event, 'port', '')
            card = ActivityRenderer.server_ready(url, port)
            self._write_card(card)
        elif isinstance(event, FileDownloadObservation):
            url = getattr(event, 'url', '') or ''
            self._tui._write_log(
                Text(f'  [bold #91abec]Downloaded[/] {url}', style=NAVY_TEXT_PRIMARY)
            )
        elif isinstance(event, TaskTrackingObservation):
            if self._should_replace_task_list_from_event(event):
                self._task_list = list(getattr(event, 'task_list', []) or [])
                self._refresh_display()
        elif isinstance(event, StreamingChunkAction):
            self._handle_streaming_chunk(event)
        elif isinstance(event, AgentStateChangedObservation):
            self._handle_state_change(event)
        elif isinstance(event, ClarificationRequestAction):
            self._tui.add_communicate_clarification(event)
        elif isinstance(event, ConfirmRequestAction):
            if not self._is_full_autonomy():
                self._tui.add_communicate_confirm(event)
        elif isinstance(event, InformAction):
            self._tui.add_communicate_inform(event)
        elif isinstance(event, UncertaintyAction):
            self._tui.add_communicate_uncertainty(event)
        elif isinstance(event, ProposalAction):
            self._tui.add_communicate_proposal(event)
        elif isinstance(event, EscalateToHumanAction):
            self._tui.add_communicate_escalate(event)
        elif isinstance(event, TaskTrackingAction):
            if self._should_replace_task_list_from_event(event):
                self._task_list = list(getattr(event, 'task_list', []) or [])
                self._refresh_display()
        else:
            name = type(event).__name__
            self._tui._write_log(Text(f'  [{name}]', style=NAVY_TEXT_MUTED))

    def _should_replace_task_list_from_event(self, event: Any) -> bool:
        """Ignore empty task payloads unless they clearly mean to clear the plan."""
        command = str(getattr(event, 'command', '') or '').strip().lower()
        task_list = list(getattr(event, 'task_list', []) or [])
        if task_list:
            return True
        if command == 'view':
            return False
        if command == 'clear':
            return True

        content = str(getattr(event, 'content', '') or '').strip().lower()
        thought = str(getattr(event, 'thought', '') or '').strip().lower()
        explicit_clear_markers = (
            'clearing the task list',
            'plan updated with 0 tasks',
            'cleared task list',
            'cleared the task list',
        )
        if any(marker in content for marker in explicit_clear_markers):
            return True
        if any(marker in thought for marker in explicit_clear_markers):
            return True
        return not self._task_list

    def _extract_file_observation_diff(self, event: Any) -> str | None:
        """Extract unified diff text from any file edit/write observation."""
        return self._extract_file_edit_diff(event)

    def _extract_file_edit_group_rows(self, event: Any) -> str | None:
        """Extract two-pane diff rows from before/after edit groups."""
        old_content = getattr(event, 'old_content', None)
        new_content = getattr(event, 'new_content', None)
        if old_content is None or new_content is None:
            return None
        return _encode_split_diff_contents(old_content, new_content)

    def _extract_file_edit_diff(self, event: Any) -> str | None:
        """Extract unified diff from a FileEditObservation for TUI display."""
        explicit_diff = getattr(event, 'diff', None)
        if isinstance(explicit_diff, str) and explicit_diff.strip():
            return explicit_diff

        content = getattr(event, 'content', None)
        if isinstance(content, str) and content:
            marker = '[EDIT_DIFF]'
            marker_index = content.find(marker)
            if marker_index != -1:
                embedded = content[marker_index + len(marker) :].strip()
                if embedded:
                    return embedded

            preview = _extract_tagged_block(
                content,
                '<DIFF_PREVIEW>',
                '</DIFF_PREVIEW>',
            )
            if preview:
                return preview

        try:
            from backend.execution.utils.diff import get_diff

            old_content = getattr(event, 'old_content', None)
            new_content = getattr(event, 'new_content', None)
            if old_content is None or new_content is None:
                return self._extract_git_file_diff(getattr(event, 'path', ''))

            diff = get_diff(old_content, new_content, path=event.path)
            if diff:
                return diff
            return None
        except Exception:
            pass
        return self._extract_git_file_diff(getattr(event, 'path', ''))

    def _extract_git_file_diff(self, path: str) -> str | None:
        """Best-effort fallback when observations omit inline diff payloads."""
        clean_path = (path or '').strip()
        if not clean_path or clean_path == '.':
            return None
        try:
            workspace = resolve_cli_workspace_directory(
                getattr(self._tui, '_config', None)
            )
            if workspace is None:
                return None

            path_obj = Path(clean_path)
            if path_obj.is_absolute():
                try:
                    clean_path = str(
                        path_obj.resolve().relative_to(workspace.resolve())
                    )
                except (OSError, ValueError):
                    return None

            for args in (
                ['git', '-C', str(workspace), '--no-pager', 'diff', '--', clean_path],
                [
                    'git',
                    '-C',
                    str(workspace),
                    '--no-pager',
                    'diff',
                    '--cached',
                    '--',
                    clean_path,
                ],
            ):
                result = subprocess.run(
                    args,
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout
        except Exception:
            return None
        return None
