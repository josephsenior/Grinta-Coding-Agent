"""Event-dispatch state machine for :class:`_AppRendererEventProcessorMixin`.

This module is the heart of the TUI event pipeline: a single ``_process_event``
function that examines an incoming ledger event/action and routes it to the
appropriate renderer hook (card writer, transcript, status strip, …).

Each event-type branch is extracted into its own ``_handle_*`` helper so that
the main dispatcher stays a flat, readable table.  No behaviour has been
changed — only structural decomposition.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from rich.markdown import Markdown
from rich.text import Text

from backend.cli._event_renderer.error_panel import notice_panel_title
from backend.cli._event_renderer.unified_renderer import ActivityRenderer
from backend.ledger.observation.error import (
    ERROR_CATEGORY_NETWORK,
    ERROR_CATEGORY_RATE_LIMIT,
    ERROR_CATEGORY_TIMEOUT,
)

_TRANSIENT_HUD_ONLY_CATEGORIES = frozenset(
    {
        ERROR_CATEGORY_TIMEOUT,
        ERROR_CATEGORY_NETWORK,
        ERROR_CATEGORY_RATE_LIMIT,
    }
)
from backend.cli.theme import NAVY_TEXT_MUTED, NAVY_TEXT_PRIMARY
from backend.cli.transcript import strip_tool_result_validation_annotations
from backend.cli.tui._app_helpers import (
    _count_text_lines,
    _count_unified_diff_changes,
    _encode_unified_diff_text,
    _format_diff_summary,
    _join_secondary_parts,
    _sanitize_terminal_display_text,
    _split_combined_diff,
)
from backend.cli.tui._app_renderer_event_classify import _is_full_autonomy
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

if TYPE_CHECKING:
    from backend.cli.tui._app_renderer_event_processor_mixin import (
        _AppRendererEventProcessorMixin,
    )


def _show_compaction_started_card(orch: '_AppRendererEventProcessorMixin') -> None:
    """Ensure an in-progress compaction is visible in the transcript."""
    if getattr(orch, '_compaction_transcript_active', False):
        return
    count = max(orch._condensation_count + 1, 1)
    orch._condensation_count = count
    orch._compaction_transcript_active = True
    card = ActivityRenderer.condensation(count=count)
    orch._write_card(card)
    orch._hud.update_condensation_count(count)


# ---------------------------------------------------------------------------
# Per-event-type handlers
# ---------------------------------------------------------------------------


def _handle_message_action(
    orch: '_AppRendererEventProcessorMixin', event: MessageAction
) -> None:
    source = getattr(event, 'source', None)
    if orch._is_user_source(source):
        return
    orch._handle_message_action(event)


def _handle_file_read_action(
    orch: '_AppRendererEventProcessorMixin', event: FileReadAction
) -> None:
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
        orch._compact_file_card_path(path),
        line_range,
    )
    widget = orch._write_card(card)
    orch._remember_pending_file_card(
        '_pending_file_read_cards_by_path',
        path,
        widget,
    )


def _handle_file_edit_action(
    orch: '_AppRendererEventProcessorMixin', event: FileEditAction
) -> None:
    cmd = getattr(event, 'command', '')
    path = event.path
    insert_line = getattr(event, 'insert_line', None)
    start = getattr(event, 'start', 1)
    end = getattr(event, 'end', -1)
    start_line = getattr(event, 'start_line', None)
    end_line = getattr(event, 'end_line', None)

    verb_entry = orch._FILE_EDIT_VERBS.get(cmd)
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
        if orch._has_pending_file_card(
            '_pending_file_create_cards_by_path',
            path,
        ):
            return
        card = ActivityRenderer.file_create(
            orch._compact_file_card_path(path),
            line_count=_count_text_lines(file_text),
        )
        widget = orch._write_card(card)
        orch._remember_pending_file_card(
            '_pending_file_create_cards_by_path',
            path,
            widget,
        )
    else:
        op_detail = f'{path} · {line_range}' if line_range else path
        orch._tui.set_current_operation(
            f'{verb} {op_detail}'.strip(),
            meta='Running',
            active=True,
        )


def _handle_file_write_action(
    orch: '_AppRendererEventProcessorMixin', event: FileWriteAction
) -> None:
    content = getattr(event, 'content', '') or ''
    card = ActivityRenderer.file_create(
        orch._compact_file_card_path(event.path),
        line_count=_count_text_lines(content),
    )
    orch._write_card(card)


def _handle_file_read_observation(
    orch: '_AppRendererEventProcessorMixin', event: FileReadObservation
) -> None:
    path = getattr(event, 'path', '') or ''
    pending = orch._take_pending_file_card(
        '_pending_file_read_cards_by_path',
        path,
    )
    operation_label = f'Read {orch._compact_file_card_path(path)}'.strip()
    if pending is not None:
        orch._update_activity_card_outcome(
            pending,
            status='ok',
            operation_label=operation_label,
        )
    else:
        card = ActivityRenderer.file_read(orch._compact_file_card_path(path))
        card.secondary_kind = 'ok'
        orch._write_card(card)


def _resolve_file_edit_pending_create(
    orch: '_AppRendererEventProcessorMixin',
    event: FileEditObservation,
    path: str,
    added: int,
) -> bool:
    pending_create = orch._take_pending_file_card(
        '_pending_file_create_cards_by_path',
        path,
    )
    if pending_create is None:
        return False
    new_content = getattr(event, 'new_content', '') or ''
    line_count = added or _count_text_lines(new_content)
    orch._update_activity_card_outcome(
        pending_create,
        status='ok',
        outcome=f'+{line_count}' if line_count else None,
        operation_label=f'Created {orch._compact_file_card_path(path)}'.strip(),
    )
    return True


def _handle_file_edit_new_file(
    orch: '_AppRendererEventProcessorMixin',
    event: FileEditObservation,
    path: str,
    added: int,
) -> None:
    new_content = getattr(event, 'new_content', '') or ''
    card = ActivityRenderer.file_create(
        orch._compact_file_card_path(path or event.path),
        line_count=added or _count_text_lines(new_content),
    )
    orch._write_card(card)


def _handle_file_edit_multi_file(
    orch: '_AppRendererEventProcessorMixin',
    event: FileEditObservation,
    path: str,
) -> None:
    diff_text = orch._extract_file_edit_diff(event)
    if diff_text:
        per_file = _split_combined_diff(diff_text)
        if per_file:
            for fp, file_diff in per_file:
                f_added, f_removed = _count_unified_diff_changes(file_diff)
                encoded = _encode_unified_diff_text(file_diff)
                if encoded:
                    orch._write_tui_file_card(
                        'Edited',
                        fp,
                        secondary=_format_diff_summary(f_added, f_removed),
                        secondary_kind='ok' if f_added or f_removed else 'neutral',
                        extra_content=encoded,
                    )
        else:
            orch._write_card(
                ActivityRenderer.file_edit('Edited', path or '?')
            )
    else:
        orch._write_card(ActivityRenderer.file_edit('Edited', path or '?'))


def _handle_file_edit_existing(
    orch: '_AppRendererEventProcessorMixin',
    event: FileEditObservation,
    path: str,
    added: int,
    removed: int,
) -> None:
    encoded_diff = orch._extract_file_edit_group_rows(event)
    if not encoded_diff:
        diff_text = orch._extract_file_edit_diff(event)
        if not (added or removed):
            added, removed = _count_unified_diff_changes(diff_text)
        encoded_diff = (
            _encode_unified_diff_text(diff_text) if diff_text else None
        )
    if encoded_diff:
        orch._write_tui_file_card(
            'Edited',
            path,
            secondary=_format_diff_summary(added, removed),
            secondary_kind='ok' if added or removed else 'neutral',
            extra_content=encoded_diff,
        )
    else:
        card = ActivityRenderer.file_edit(
            'Edited',
            path,
            added=added,
            removed=removed,
        )
        orch._write_card(card)


def _handle_file_edit_observation(
    orch: '_AppRendererEventProcessorMixin', event: FileEditObservation
) -> None:
    from backend.cli.transcript import strip_indentation_warnings

    if hasattr(event, 'content') and event.content:
        event.content = strip_indentation_warnings(event.content)

    path = (getattr(event, 'path', '') or '').strip()
    added = event.added
    removed = event.removed

    if _resolve_file_edit_pending_create(orch, event, path, added):
        return

    if not getattr(event, 'prev_exist', True):
        _handle_file_edit_new_file(orch, event, path, added)
    elif not path or path == '.':
        _handle_file_edit_multi_file(orch, event, path)
    else:
        _handle_file_edit_existing(orch, event, path, added, removed)


def _handle_file_write_observation(
    orch: '_AppRendererEventProcessorMixin', event: FileWriteObservation
) -> None:
    diff_text = orch._extract_file_observation_diff(event)
    if diff_text:
        encoded_diff = _encode_unified_diff_text(diff_text)
        added, removed = _count_unified_diff_changes(diff_text)
        orch._write_tui_file_card(
            'Edited',
            event.path,
            secondary=_format_diff_summary(added, removed),
            secondary_kind='ok' if added or removed else 'neutral',
            extra_content=encoded_diff,
        )


def _handle_mcp_action(
    orch: '_AppRendererEventProcessorMixin', event: MCPAction
) -> None:
    card = ActivityRenderer.mcp_tool(event.name, event.arguments)
    widget = orch._write_card(card)
    orch._pending_mcp_card = widget


def _handle_cmd_run_action(
    orch: '_AppRendererEventProcessorMixin', event: CmdRunAction
) -> None:
    cmd = getattr(event, 'command', '') or ''
    if not getattr(event, 'hidden', False):
        orch._create_shell_command_card(cmd)


def _handle_mcp_observation(
    orch: '_AppRendererEventProcessorMixin', event: MCPObservation
) -> None:
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
    pending = orch._pending_mcp_card
    if pending is not None:
        orch._update_activity_card_outcome(
            pending,
            status='ok',
            outcome='completed',
            extra_content=preview,
            operation_label=f'Called {event.name}'.strip(),
        )
        orch._pending_mcp_card = None
    else:
        orch._write_card(card)


def _handle_cmd_output_observation(
    orch: '_AppRendererEventProcessorMixin', event: CmdOutputObservation
) -> None:
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
        orch._complete_shell_command_card(
            cmd,
            output=output[:500],
            exit_code=exit_code,
            cwd=cwd,
        )


def _handle_error_observation(
    orch: '_AppRendererEventProcessorMixin', event: ErrorObservation
) -> None:
    orch._compaction_transcript_active = False
    content = event.content or 'An unknown error occurred'
    if getattr(event, 'notify_ui_only', False):
        error_category = getattr(event, 'error_category', None)
        if (
            error_category
            and error_category not in _TRANSIENT_HUD_ONLY_CATEGORIES
        ):
            summary = notice_panel_title(content, error_category=error_category)
            first_line = content.split('\n', 1)[0].strip()
            orch._update_runtime_strip(summary, first_line, active=True)
        return
    orch._tui.add_warning(content)


def _handle_success_observation(
    orch: '_AppRendererEventProcessorMixin', event: SuccessObservation
) -> None:
    orch._compaction_transcript_active = False
    orch._clear_retry_strip('Recovered')
    orch._clear_runtime_status('Recovered')
    orch._tui.add_success(event.content or 'Done')


def _handle_status_observation(
    orch: '_AppRendererEventProcessorMixin', event: StatusObservation
) -> None:
    status_type = str(getattr(event, 'status_type', '') or '')
    extras = getattr(event, 'extras', None) or {}
    if status_type in (
        'retry_pending',
        'retry_resuming',
        'llm_retry_pending',
        'llm_retry_resuming',
    ):
        label, last_status, message = orch._format_retry_status_message(
            status_type, extras
        )
        orch._hud.update_ledger('Backoff')
        orch._hud.update_agent_state(label)
        orch._tui.set_agent_phase(label)
        orch._update_retry_strip(label, message)
        return
    if status_type == 'compaction':
        orch._clear_retry_strip('Idle')
        orch._hud.update_agent_state('Compacting')
        orch._tui.set_agent_phase('Compacting context...')
        orch._update_runtime_strip(
            'Compacting context',
            'Reducing context to continue the task',
            active=True,
        )
        _show_compaction_started_card(orch)
        return
    msg = (event.content or '').strip()
    if msg:
        summary = (
            status_type.replace('_', ' ').strip().title()
            if status_type
            else 'Runtime notice'
        )
        orch._update_runtime_strip(summary, msg, active=False)


def _handle_agent_think_action(
    orch: '_AppRendererEventProcessorMixin', event: AgentThinkAction
) -> None:
    source_tool = getattr(event, 'source_tool', '') or ''
    thought = getattr(event, 'thought', '') or getattr(event, 'content', '')
    kind = getattr(event, 'kind', '') or ''
    orch._render_thinking_payload(
        thought, source_tool=source_tool, kind=kind
    )


def _handle_agent_think_observation(
    orch: '_AppRendererEventProcessorMixin', event: AgentThinkObservation
) -> None:
    thought = getattr(event, 'thought', '') or getattr(event, 'content', '')
    kind = getattr(event, 'kind', '') or ''
    orch._render_thinking_payload(thought, kind=kind)


def _handle_browser_tool_action(
    orch: '_AppRendererEventProcessorMixin', event: BrowserToolAction
) -> None:
    action_name = getattr(event, 'command', 'browser') or 'browser'
    url = ''
    if action_name == 'navigate':
        url = (getattr(event, 'params', {}) or {}).get('url', '')
    elif action_name == 'click':
        selector = (getattr(event, 'params', {}) or {}).get('selector', '')
        url = selector[:80] if selector else ''
    card = ActivityRenderer.browser_action(action_name, url)
    widget = orch._write_card(card)
    orch._last_browser_action_card = widget
    orch._last_browser_cmd = action_name


def _handle_browse_interactive_action(
    orch: '_AppRendererEventProcessorMixin', event: BrowseInteractiveAction
) -> None:
    actions = getattr(event, 'browser_actions', '') or ''
    detail = (
        actions[:80] + ('...' if len(actions) > 80 else '') if actions else ''
    )
    card = ActivityRenderer.browser_action('browse', detail)
    widget = orch._write_card(card)
    orch._last_browser_action_card = widget
    orch._last_browser_cmd = 'browse'


def _handle_browser_screenshot_observation(
    orch: '_AppRendererEventProcessorMixin', event: BrowserScreenshotObservation
) -> None:
    url = getattr(event, 'image_path', '') or ''
    content = (event.content or '').strip()
    card = ActivityRenderer.browser_action(
        'screenshot', url, result=content or 'captured'
    )
    prev = getattr(orch, '_last_browser_action_card', None)
    last_cmd = getattr(orch, '_last_browser_cmd', '') or ''
    if prev is not None and last_cmd not in ('', 'screenshot'):
        extra_parts = []
        if url:
            extra_parts.append(f'URL: {url}')
        if content:
            extra_parts.append(content[:200])
        preview = '\n'.join(extra_parts) if extra_parts else None
        orch._update_activity_card_outcome(
            prev,
            status='ok',
            outcome='done',
            extra_content=preview,
            operation_label=f'Browser {last_cmd}'.strip(),
        )
        orch._last_browser_action_card = None
    else:
        orch._write_card(card)


def _handle_lsp_query_action(
    orch: '_AppRendererEventProcessorMixin', event: LspQueryAction
) -> None:
    symbol = getattr(event, 'symbol', '') or getattr(event, 'query', '') or ''
    card = ActivityRenderer.lsp_query(symbol)
    widget = orch._write_card(card)
    orch._pending_lsp_card = widget


def _handle_lsp_query_observation(
    orch: '_AppRendererEventProcessorMixin', event: LspQueryObservation
) -> None:
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
    pending = orch._pending_lsp_card
    if pending is not None:
        status = 'ok' if available else 'err'
        orch._update_activity_card_outcome(
            pending,
            status=status,
            outcome=card.secondary or 'completed',
            extra_content=preview,
            operation_label=f'Analyzed {symbol}'.strip(),
        )
        orch._pending_lsp_card = None
    else:
        orch._write_card(card)


def _handle_terminal_run_action(
    orch: '_AppRendererEventProcessorMixin', event: TerminalRunAction
) -> None:
    cmd = getattr(event, 'command', '') or ''
    session_id = getattr(event, 'session_id', '') or ''
    detail = orch._terminal_card_detail(session_id, cmd)
    orch._upsert_terminal_session_card(
        session_id=session_id,
        verb='Started',
        detail=detail,
        secondary=_join_secondary_parts(
            orch._terminal_session_label(session_id),
            'starting session',
        ),
        secondary_kind='neutral',
        processing=True,
    )


def _handle_terminal_input_action(
    orch: '_AppRendererEventProcessorMixin', event: TerminalInputAction
) -> None:
    session_id = getattr(event, 'session_id', '') or ''
    submitted = _sanitize_terminal_display_text(
        getattr(event, 'input', '') or ''
    )
    detail = orch._terminal_card_detail(session_id, submitted)
    orch._upsert_terminal_session_card(
        session_id=session_id,
        verb='Sent',
        detail=detail,
        secondary=_join_secondary_parts(
            orch._terminal_session_label(session_id),
            'awaiting output',
        ),
        secondary_kind='neutral',
        extra_content=f'$ {submitted.rstrip()}' if submitted.strip() else None,
        processing=True,
    )


def _handle_terminal_read_action(
    orch: '_AppRendererEventProcessorMixin', event: TerminalReadAction
) -> None:
    session_id = getattr(event, 'session_id', '') or ''
    orch._upsert_terminal_session_card(
        session_id=session_id,
        verb='Reading',
        detail=orch._terminal_card_detail(session_id),
        secondary=_join_secondary_parts(
            orch._terminal_session_label(session_id),
            'streaming output',
        ),
        secondary_kind='neutral',
        processing=True,
    )


def _handle_terminal_observation(
    orch: '_AppRendererEventProcessorMixin', event: TerminalObservation
) -> None:
    content = event.content or ''
    session_id = getattr(event, 'session_id', '') or ''
    exit_code = getattr(event, 'exit_code', None)
    state = getattr(event, 'state', None)
    secondary = _join_secondary_parts(
        orch._terminal_session_label(session_id),
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
    orch._upsert_terminal_session_card(
        session_id=session_id,
        verb='Output',
        detail=orch._terminal_card_detail(session_id),
        secondary=secondary,
        secondary_kind=secondary_kind,
        extra_content=content or None,
        processing=exit_code is None,
        collapse_after_update=exit_code == 0 and bool(content),
    )


def _handle_agent_condensation_observation(
    orch: '_AppRendererEventProcessorMixin', event: AgentCondensationObservation
) -> None:
    orch._compaction_transcript_active = False
    orch._update_runtime_strip(
        'Context compacted',
        'Context compressed successfully',
        active=False,
    )
    count = max(orch._condensation_count, 1)
    orch._condensation_count = count
    orch._hud.update_condensation_count(count)
    card = ActivityRenderer.condensation(count=count, result=event.content)
    orch._write_card(card)


def _handle_delegate_task_action(
    orch: '_AppRendererEventProcessorMixin', event: DelegateTaskAction
) -> None:
    task = (
        getattr(event, 'task_description', '')
        or getattr(event, 'task', '')
        or ''
    )
    worker = getattr(event, 'worker', '') or ''
    if getattr(event, 'parallel_tasks', None):
        for item in list(getattr(event, 'parallel_tasks', []) or []):
            task_desc = orch._summarize_worker_task(
                str(item.get('task_description') or 'delegated task')
            )
            orch._active_worker_tasks.append(task_desc)
    else:
        orch._active_worker_tasks.append(orch._summarize_worker_task(task))
    orch._sync_worker_strip()
    card = ActivityRenderer.delegation(task, worker)
    widget = orch._write_card(card)
    orch._pending_delegate_card = widget


def _handle_delegate_task_observation(
    orch: '_AppRendererEventProcessorMixin', event: DelegateTaskObservation
) -> None:
    content = (event.content or '').strip()
    success = bool(getattr(event, 'success', True))
    error_message = (getattr(event, 'error_message', '') or '').strip()
    resolved_task = (
        orch._active_worker_tasks.pop(0)
        if orch._active_worker_tasks
        else 'delegated task'
    )
    if success:
        orch._worker_completed += 1
        if resolved_task:
            orch._worker_recent_results.append(f'ok: {resolved_task}')
    else:
        orch._worker_failed += 1
        if resolved_task:
            orch._worker_recent_results.append(f'fail: {resolved_task}')
    orch._sync_worker_strip()
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
    pending = orch._pending_delegate_card
    if pending is not None:
        orch._update_activity_card_outcome(
            pending,
            status='ok' if success else 'err',
            outcome='completed' if success else 'failed',
            extra_content=preview,
            operation_label=f'Delegated {resolved_task}'.strip(),
        )
        orch._pending_delegate_card = None
    else:
        orch._write_card(card)


def _handle_task_tracking_observation(
    orch: '_AppRendererEventProcessorMixin', event: TaskTrackingObservation
) -> None:
    if orch._should_replace_task_list_from_event(event):
        orch._task_list = list(getattr(event, 'task_list', []) or [])
        orch._refresh_display()


def _handle_task_tracking_action(
    orch: '_AppRendererEventProcessorMixin', event: TaskTrackingAction
) -> None:
    if orch._should_replace_task_list_from_event(event):
        orch._task_list = list(getattr(event, 'task_list', []) or [])
        orch._refresh_display()


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------


def _process_event(orch: '_AppRendererEventProcessorMixin', event: Any) -> None:
    orch._update_metrics(event)
    if isinstance(event, NullAction) or isinstance(event, NullObservation):
        return
    if isinstance(event, ChangeAgentStateAction):
        return

    source = getattr(event, 'source', None)
    if isinstance(event, MessageAction) and orch._is_user_source(source):
        orch._last_thinking_text_hash = ''
        orch._last_thinking_artifact_hash = ''

    if not orch._in_agent_turn and not isinstance(
        event, (MessageAction, StreamingChunkAction, AgentStateChangedObservation)
    ):
        orch._in_agent_turn = True
        orch._turn_count += 1
        orch._tools_in_turn = 0
        orch._turn_start_time = time.monotonic()

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
    if orch._in_agent_turn and is_tool_execution_event:
        orch._tools_in_turn += 1

    if not orch._is_live_thinking_event(event) and not getattr(
        orch, '_streaming_active', False
    ):
        orch._finalize_live_thinking()

    if not isinstance(event, (MessageAction, StreamingChunkAction)):
        if orch._live_response_dirty:
            if is_tool_execution_event:
                orch.clear_live_response()
            else:
                orch._commit_final_response(orch._live_response)
        else:
            orch.clear_live_response()

    _dispatch_event(orch, event)


def _dispatch_event(
    orch: '_AppRendererEventProcessorMixin', event: Any
) -> None:
    event_type = type(event)
    handler = _EVENT_HANDLERS.get(event_type)
    if handler is not None:
        handler(orch, event)
        return

    if isinstance(event, RecallAction):
        pass
    elif isinstance(event, CondensationRequestAction):
        _show_compaction_started_card(orch)
    elif isinstance(event, RecallObservation):
        pass
    elif isinstance(event, RecallFailureObservation):
        pass
    elif isinstance(event, CondensationAction):
        _show_compaction_started_card(orch)
    elif isinstance(event, StreamingChunkAction):
        orch._handle_streaming_chunk(event)
    elif isinstance(event, AgentStateChangedObservation):
        orch._handle_state_change(event)
    elif isinstance(event, ClarificationRequestAction):
        orch._tui.add_communicate_clarification(event)
    elif isinstance(event, ConfirmRequestAction):
        if not _is_full_autonomy(orch):
            orch._tui.add_communicate_confirm(event)
    elif isinstance(event, InformAction):
        orch._tui.add_communicate_inform(event)
    elif isinstance(event, UncertaintyAction):
        orch._tui.add_communicate_uncertainty(event)
    elif isinstance(event, ProposalAction):
        orch._tui.add_communicate_proposal(event)
    elif isinstance(event, EscalateToHumanAction):
        orch._tui.add_communicate_escalate(event)
    elif isinstance(event, UserRejectObservation):
        card = ActivityRenderer.user_reject()
        orch._write_card(card)
    elif isinstance(event, ServerReadyObservation):
        url = getattr(event, 'url', '')
        port = getattr(event, 'port', '')
        card = ActivityRenderer.server_ready(url, port)
        orch._write_card(card)
    elif isinstance(event, FileDownloadObservation):
        url = getattr(event, 'url', '') or ''
        orch._tui._write_log(
            Text(f'  [bold #91abec]Downloaded[/] {url}', style=NAVY_TEXT_PRIMARY)
        )
    else:
        name = type(event).__name__
        orch._tui._write_log(Text(f'  [{name}]', style=NAVY_TEXT_MUTED))


_EVENT_HANDLERS: dict[type, Any] = {
    MessageAction: _handle_message_action,
    FileReadAction: _handle_file_read_action,
    FileEditAction: _handle_file_edit_action,
    FileWriteAction: _handle_file_write_action,
    FileReadObservation: _handle_file_read_observation,
    FileEditObservation: _handle_file_edit_observation,
    FileWriteObservation: _handle_file_write_observation,
    MCPAction: _handle_mcp_action,
    CmdRunAction: _handle_cmd_run_action,
    MCPObservation: _handle_mcp_observation,
    CmdOutputObservation: _handle_cmd_output_observation,
    ErrorObservation: _handle_error_observation,
    SuccessObservation: _handle_success_observation,
    StatusObservation: _handle_status_observation,
    AgentThinkAction: _handle_agent_think_action,
    AgentThinkObservation: _handle_agent_think_observation,
    BrowserToolAction: _handle_browser_tool_action,
    BrowseInteractiveAction: _handle_browse_interactive_action,
    BrowserScreenshotObservation: _handle_browser_screenshot_observation,
    LspQueryAction: _handle_lsp_query_action,
    LspQueryObservation: _handle_lsp_query_observation,
    TerminalRunAction: _handle_terminal_run_action,
    TerminalInputAction: _handle_terminal_input_action,
    TerminalReadAction: _handle_terminal_read_action,
    TerminalObservation: _handle_terminal_observation,
    AgentCondensationObservation: _handle_agent_condensation_observation,
    DelegateTaskAction: _handle_delegate_task_action,
    DelegateTaskObservation: _handle_delegate_task_observation,
    TaskTrackingObservation: _handle_task_tracking_observation,
    TaskTrackingAction: _handle_task_tracking_action,
}
