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
from backend.cli.tui._app_renderer_thinking_mixin import ThinkingRenderIntent
from backend.ledger.action import (
    AgentThinkAction,
    AnalyzeProjectStructureAction,
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
    FindSymbolsAction,
    GlobAction,
    GrepAction,
    InformAction,
    LspQueryAction,
    MCPAction,
    MessageAction,
    NullAction,
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
from backend.ledger.action.memory_tools import (
    CheckpointAction,
    MemoryPersistAction,
    MemoryRecallAction,
    ScratchpadNoteAction,
    ScratchpadRecallAction,
    WorkingMemoryAction,
)
from backend.ledger.observation import (
    AgentCondensationObservation,
    AgentStateChangedObservation,
    AgentThinkObservation,
    AnalyzeProjectStructureObservation,
    BrowserScreenshotObservation,
    CmdOutputObservation,
    DelegateTaskObservation,
    ErrorObservation,
    FileDownloadObservation,
    FileEditObservation,
    FileReadObservation,
    FileWriteObservation,
    FindSymbolsObservation,
    GlobObservation,
    GrepObservation,
    LspQueryObservation,
    MCPObservation,
    NullObservation,
    ReadSymbolsObservation,
    RecallFailureObservation,
    RecallObservation,
    ServerReadyObservation,
    StatusObservation,
    SuccessObservation,
    TaskTrackingObservation,
    TerminalObservation,
    UserRejectObservation,
)
from backend.ledger.observation.memory_tools import (
    CheckpointObservation,
    MemoryPersistObservation,
    MemoryRecallObservation,
    ScratchpadNoteObservation,
    ScratchpadRecallObservation,
    WorkingMemoryObservation,
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


def _file_read_range_from_view_range(view_range: Any) -> str | None:
    if view_range and len(view_range) == 2:
        return f'{view_range[0]}:{view_range[1]}'
    return None


def _file_read_range_from_bounds(start: int, end: int) -> str:
    if start not in (0, 1) or end != -1:
        end_str = str(end) if end != -1 else 'end'
        return f'{start}:{end_str}'
    return ''


def _resolve_file_read_line_range(view_range: Any, start: int, end: int) -> str:
    result = _file_read_range_from_view_range(view_range)
    if result is not None:
        return result
    return _file_read_range_from_bounds(start, end)


def _handle_file_read_action(
    orch: '_AppRendererEventProcessorMixin', event: FileReadAction
) -> None:
    path = getattr(event, 'path', '')
    view_range = getattr(event, 'view_range', None)
    start = getattr(event, 'start', 0)
    end = getattr(event, 'end', -1)
    line_range = _resolve_file_read_line_range(view_range, start, end)
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


def _resolve_verb_from_registry(
    orch: '_AppRendererEventProcessorMixin',
    cmd: str,
    insert_line: int | None,
) -> tuple[str, str] | None:
    verb_entry = orch._FILE_EDIT_VERBS.get(cmd)
    if verb_entry is None:
        return None
    verb, include_stats = verb_entry
    if include_stats and insert_line is not None:
        return verb, f'line {insert_line}'
    return verb, ''


def _resolve_edit_mode_range(
    event: FileEditAction,
    start_line: int | None,
    end_line: int | None,
) -> tuple[str, str] | None:
    edit_mode = getattr(event, 'edit_mode', '')
    if edit_mode == 'range' and start_line is not None and end_line is not None:
        return 'Edited', f'{start_line}:{end_line}'
    return None


def _resolve_no_cmd_line_range(start: int, end: int) -> tuple[str, str]:
    end_str = str(end) if end != -1 else 'end'
    return 'Edited', f'{start}:{end_str}'


def _resolve_file_edit_verb_and_range(
    orch: '_AppRendererEventProcessorMixin',
    event: FileEditAction,
    cmd: str,
    insert_line: int | None,
    start: int,
    end: int,
    start_line: int | None,
    end_line: int | None,
) -> tuple[str, str]:
    result = _resolve_verb_from_registry(orch, cmd, insert_line)
    if result is not None:
        return result
    if not cmd:
        return _resolve_no_cmd_line_range(start, end)
    if cmd == 'edit':
        result = _resolve_edit_mode_range(event, start_line, end_line)
        if result is not None:
            return result
    return 'Edited', ''


def _handle_file_edit_create(
    orch: '_AppRendererEventProcessorMixin',
    event: FileEditAction,
    path: str,
) -> None:
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

    verb, line_range = _resolve_file_edit_verb_and_range(
        orch,
        event,
        cmd,
        insert_line,
        start,
        end,
        start_line,
        end_line,
    )

    if cmd == 'create_file':
        _handle_file_edit_create(orch, event, path)
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


def _write_multi_file_edit_card(
    orch: '_AppRendererEventProcessorMixin',
    fp: str,
    file_diff: str,
) -> None:
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


def _write_multi_file_edit_cards(
    orch: '_AppRendererEventProcessorMixin',
    per_file: list,
) -> None:
    for fp, file_diff in per_file:
        _write_multi_file_edit_card(orch, fp, file_diff)


def _handle_file_edit_multi_file(
    orch: '_AppRendererEventProcessorMixin',
    event: FileEditObservation,
    path: str,
) -> None:
    diff_text = orch._extract_file_edit_diff(event)
    if diff_text:
        per_file = _split_combined_diff(diff_text)
        if per_file:
            _write_multi_file_edit_cards(orch, per_file)
        else:
            orch._write_card(ActivityRenderer.file_edit('Edited', path or '?'))
    else:
        orch._write_card(ActivityRenderer.file_edit('Edited', path or '?'))


def _resolve_existing_file_edit_diff(
    orch: '_AppRendererEventProcessorMixin',
    event: FileEditObservation,
    added: int,
    removed: int,
) -> tuple[str | None, int, int]:
    event_id = getattr(event, 'id', -1)
    if event_id >= 0:
        cached = getattr(orch, '_render_prep_cache', {}).get(event_id)
        if cached:
            return cached, added, removed
    encoded_diff = orch._extract_file_edit_group_rows(event)
    if encoded_diff:
        return encoded_diff, added, removed
    diff_text = orch._extract_file_edit_diff(event)
    if not (added or removed):
        added, removed = _count_unified_diff_changes(diff_text)
    encoded_diff = _encode_unified_diff_text(diff_text) if diff_text else None
    return encoded_diff, added, removed


def _write_file_edit_existing_card(
    orch: '_AppRendererEventProcessorMixin',
    path: str,
    encoded_diff: str | None,
    added: int,
    removed: int,
) -> None:
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


def _handle_file_edit_existing(
    orch: '_AppRendererEventProcessorMixin',
    event: FileEditObservation,
    path: str,
    added: int,
    removed: int,
) -> None:
    encoded_diff, added, removed = _resolve_existing_file_edit_diff(
        orch,
        event,
        added,
        removed,
    )
    _write_file_edit_existing_card(orch, path, encoded_diff, added, removed)


def _clean_file_edit_content(event: FileEditObservation) -> None:
    if hasattr(event, 'content') and event.content:
        from backend.cli.transcript import strip_indentation_warnings

        event.content = strip_indentation_warnings(event.content)


def _route_file_edit_observation(
    orch: '_AppRendererEventProcessorMixin',
    event: FileEditObservation,
    path: str,
    added: int,
    removed: int,
) -> None:
    if not getattr(event, 'prev_exist', True):
        _handle_file_edit_new_file(orch, event, path, added)
    elif not path or path == '.':
        _handle_file_edit_multi_file(orch, event, path)
    else:
        _handle_file_edit_existing(orch, event, path, added, removed)


def _handle_file_edit_observation(
    orch: '_AppRendererEventProcessorMixin', event: FileEditObservation
) -> None:
    _clean_file_edit_content(event)
    path = (getattr(event, 'path', '') or '').strip()
    added = event.added
    removed = event.removed
    if _resolve_file_edit_pending_create(orch, event, path, added):
        return
    _route_file_edit_observation(orch, event, path, added, removed)


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
        truncated = event.content[:200] + ('...' if len(event.content) > 200 else '')
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


def _resolve_cmd_output_cwd(event: CmdOutputObservation) -> str | None:
    if hasattr(event, 'metadata') and event.metadata:
        return getattr(event.metadata, 'working_dir', None)
    return None


def _sanitize_cmd_output(output: str) -> str:
    if not output:
        return ''
    return _sanitize_terminal_display_text(
        strip_tool_result_validation_annotations(output)
    ).strip()


def _handle_cmd_output_observation(
    orch: '_AppRendererEventProcessorMixin', event: CmdOutputObservation
) -> None:
    output = (event.content or '').strip()
    exit_code = getattr(event, 'exit_code', None)
    cmd = getattr(event, 'command', '') or ''
    cwd = _resolve_cmd_output_cwd(event)
    output = _sanitize_cmd_output(output)
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
        if error_category and error_category not in _TRANSIENT_HUD_ONLY_CATEGORIES:
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


def _handle_status_retry(
    orch: '_AppRendererEventProcessorMixin',
    status_type: str,
    extras: dict,
) -> None:
    label, last_status, message = orch._format_retry_status_message(status_type, extras)
    orch._hud.update_ledger('Backoff')
    orch._hud.update_agent_state(label)
    orch._tui.set_agent_phase(label)
    orch._update_retry_strip(label, message)


def _handle_status_compaction(
    orch: '_AppRendererEventProcessorMixin',
) -> None:
    orch._clear_retry_strip('Idle')
    orch._hud.update_agent_state('Compacting')
    orch._tui.set_agent_phase('Compacting context...')
    orch._update_runtime_strip(
        'Compacting context',
        'Reducing context to continue the task',
        active=True,
    )
    _show_compaction_started_card(orch)


def _handle_status_notice(
    orch: '_AppRendererEventProcessorMixin',
    event: StatusObservation,
    status_type: str,
) -> None:
    msg = (event.content or '').strip()
    if not msg:
        return
    summary = (
        status_type.replace('_', ' ').strip().title()
        if status_type
        else 'Runtime notice'
    )
    orch._update_runtime_strip(summary, msg, active=False)


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
        _handle_status_retry(orch, status_type, extras)
        return
    if status_type == 'compaction':
        _handle_status_compaction(orch)
        return
    _handle_status_notice(orch, event, status_type)


def _handle_agent_think_action(
    orch: '_AppRendererEventProcessorMixin', event: AgentThinkAction
) -> None:
    from backend.engine.common import arguments_from_tool_call_metadata

    source_tool = getattr(event, 'source_tool', '') or ''
    thought = getattr(event, 'thought', '') or getattr(event, 'content', '')
    kind = getattr(event, 'kind', '') or ''
    tool_args = (
        arguments_from_tool_call_metadata(getattr(event, 'tool_call_metadata', None))
        if source_tool in ('grep', 'glob')
        else None
    )
    orch._render_thinking_payload(
        thought,
        source_tool=source_tool,
        kind=kind,
        tool_args=tool_args,
    )


def _handle_agent_think_observation(
    orch: '_AppRendererEventProcessorMixin', event: AgentThinkObservation
) -> None:
    thought = getattr(event, 'thought', '') or getattr(event, 'content', '')
    kind = getattr(event, 'kind', '') or ''
    orch._render_thinking_payload(thought, kind=kind)


def _browser_navigate_url(event: BrowserToolAction) -> str:
    return (getattr(event, 'params', {}) or {}).get('url', '')


def _browser_click_url(event: BrowserToolAction) -> str:
    selector = (getattr(event, 'params', {}) or {}).get('selector', '')
    return selector[:80] if selector else ''


def _resolve_browser_action_url(action_name: str, event: BrowserToolAction) -> str:
    if action_name == 'navigate':
        return _browser_navigate_url(event)
    if action_name == 'click':
        return _browser_click_url(event)
    return ''


def _handle_browser_tool_action(
    orch: '_AppRendererEventProcessorMixin', event: BrowserToolAction
) -> None:
    action_name = getattr(event, 'command', 'browser') or 'browser'
    url = _resolve_browser_action_url(action_name, event)
    card = ActivityRenderer.browser_action(action_name, url)
    widget = orch._write_card(card)
    orch._last_browser_action_card = widget
    orch._last_browser_cmd = action_name


def _handle_browse_interactive_action(
    orch: '_AppRendererEventProcessorMixin', event: BrowseInteractiveAction
) -> None:
    actions = getattr(event, 'browser_actions', '') or ''
    detail = actions[:80] + ('...' if len(actions) > 80 else '') if actions else ''
    card = ActivityRenderer.browser_action('browse', detail)
    widget = orch._write_card(card)
    orch._last_browser_action_card = widget
    orch._last_browser_cmd = 'browse'


def _build_screenshot_preview(url: str, content: str) -> str | None:
    extra_parts = []
    if url:
        extra_parts.append(f'URL: {url}')
    if content:
        extra_parts.append(content[:200])
    return '\n'.join(extra_parts) if extra_parts else None


def _update_browser_screenshot_card(
    orch: '_AppRendererEventProcessorMixin',
    prev: Any,
    last_cmd: str,
    url: str,
    content: str,
) -> None:
    preview = _build_screenshot_preview(url, content)
    orch._update_activity_card_outcome(
        prev,
        status='ok',
        outcome='done',
        extra_content=preview,
        operation_label=f'Browser {last_cmd}'.strip(),
    )
    orch._last_browser_action_card = None


def _should_update_browser_card(prev: Any, last_cmd: str) -> bool:
    if prev is None:
        return False
    return last_cmd not in ('', 'screenshot')


def _extract_screenshot_details(
    orch: '_AppRendererEventProcessorMixin',
    event: BrowserScreenshotObservation,
) -> tuple[str, str, Any, str]:
    url = getattr(event, 'image_path', '') or ''
    content = (event.content or '').strip()
    prev = getattr(orch, '_last_browser_action_card', None)
    last_cmd = getattr(orch, '_last_browser_cmd', '') or ''
    return url, content, prev, last_cmd


def _handle_browser_screenshot_observation(
    orch: '_AppRendererEventProcessorMixin', event: BrowserScreenshotObservation
) -> None:
    url, content, prev, last_cmd = _extract_screenshot_details(orch, event)
    card = ActivityRenderer.browser_action(
        'screenshot', url, result=content or 'captured'
    )
    if _should_update_browser_card(prev, last_cmd):
        _update_browser_screenshot_card(orch, prev, last_cmd, url, content)
    else:
        orch._write_card(card)


def _handle_grep_action(
    orch: '_AppRendererEventProcessorMixin', event: GrepAction
) -> None:
    card = ActivityRenderer.search_results(
        query=event.pattern or 'code search',
        scope=event.path or '',
        source_tool='grep',
    )
    widget = orch._write_card(card)
    orch._pending_search_card = widget
    orch._pending_search_tool = 'grep'


def _handle_glob_action(
    orch: '_AppRendererEventProcessorMixin', event: GlobAction
) -> None:
    card = ActivityRenderer.search_results(
        query=event.pattern or 'file listing',
        scope=event.path or '',
        source_tool='glob',
    )
    widget = orch._write_card(card)
    orch._pending_search_card = widget
    orch._pending_search_tool = 'glob'


def _handle_lsp_query_action(
    orch: '_AppRendererEventProcessorMixin', event: LspQueryAction
) -> None:
    symbol = getattr(event, 'symbol', '') or getattr(event, 'query', '') or ''
    card = ActivityRenderer.lsp_query(symbol)
    widget = orch._write_card(card)
    orch._pending_lsp_card = widget


def _build_lsp_preview(content: str) -> str | None:
    if not content:
        return None
    truncated = content[:200] + ('...' if len(content) > 200 else '')
    return f'  {truncated}'


def _update_or_write_lsp_card(
    orch: '_AppRendererEventProcessorMixin',
    card: Any,
    symbol: str,
    available: bool,
    preview: str | None,
) -> None:
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


def _handle_grep_observation(
    orch: '_AppRendererEventProcessorMixin', event: GrepObservation
) -> None:
    from backend.cli._tool_display.renderers.search import extract_file_summary

    content = event.error or event.content or ''
    match_count, file_count, file_list = extract_file_summary(content)
    result_lines = [line for line in event.lines if line.strip()]
    if not result_lines and content:
        result_lines = [line for line in content.splitlines() if line.strip()]
    orch._render_search_card(
        query=event.pattern or 'code search',
        content=content,
        match_count=match_count or event.match_count,
        file_count=file_count or event.file_count,
        file_list=file_list,
        result_lines=result_lines,
        source_tool='grep',
        scope=event.path or '',
        pending_attr='_pending_search_card'
        if orch._pending_search_tool == 'grep'
        else None,
    )


def _handle_glob_observation(
    orch: '_AppRendererEventProcessorMixin', event: GlobObservation
) -> None:
    content = event.error or event.content or ''
    files = event.files or [line for line in content.splitlines() if line.strip()]
    orch._render_search_card(
        query=event.pattern or 'file listing',
        content=content,
        match_count=0,
        file_count=event.file_count or len(files),
        file_list=[(path, 1) for path in files[:5]],
        result_lines=files,
        source_tool='glob',
        scope=event.path or '',
        pending_attr='_pending_search_card'
        if orch._pending_search_tool == 'glob'
        else None,
    )


def _handle_lsp_query_observation(
    orch: '_AppRendererEventProcessorMixin', event: LspQueryObservation
) -> None:
    content = (event.content or '').strip()
    symbol = getattr(event, 'symbol', '') or ''
    available = bool(getattr(event, 'available', True))
    card = ActivityRenderer.lsp_query(symbol, result=content, available=available)
    preview = _build_lsp_preview(content)
    _update_or_write_lsp_card(orch, card, symbol, available, preview)


def _search_file_list_from_paths(paths: list[str]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for path in paths:
        if path:
            counts[path] = counts.get(path, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]


def _find_symbols_result_lines(
    event: FindSymbolsObservation,
) -> tuple[list[str], list[tuple[str, int]]]:
    result_lines: list[str] = []
    paths: list[str] = []
    for candidate in event.candidates:
        path = str(candidate.get('path') or '').strip()
        start_line = candidate.get('start_line')
        qualified_name = str(
            candidate.get('qualified_name') or candidate.get('name') or ''
        ).strip()
        if path and start_line:
            result_lines.append(f'{path}:{start_line}:{qualified_name}')
            paths.append(path)
        elif qualified_name:
            result_lines.append(qualified_name)
    return result_lines, _search_file_list_from_paths(paths)


def _handle_find_symbols_action(
    orch: '_AppRendererEventProcessorMixin', event: FindSymbolsAction
) -> None:
    card = ActivityRenderer.search_results(
        query=event.query or 'symbol search',
        scope=event.path or '',
        source_tool='search',
    )
    widget = orch._write_card(card)
    orch._pending_find_symbols_card = widget


def _handle_find_symbols_observation(
    orch: '_AppRendererEventProcessorMixin', event: FindSymbolsObservation
) -> None:
    content = event.error or event.content or ''
    result_lines, file_list = _find_symbols_result_lines(event)
    all_paths = {
        str(candidate.get('path') or '').strip()
        for candidate in event.candidates
        if str(candidate.get('path') or '').strip()
    }
    orch._render_search_card(
        query=event.query or 'symbol search',
        content=content,
        match_count=len(event.candidates),
        file_count=len(all_paths),
        file_list=file_list,
        result_lines=result_lines,
        source_tool='search',
        scope=event.path or '',
        pending_attr='_pending_find_symbols_card',
    )


def _handle_read_symbols_action(
    orch: '_AppRendererEventProcessorMixin', event: ReadSymbolsAction
) -> None:
    label = f'{len(event.targets)} symbol{"s" if len(event.targets) != 1 else ""}'
    card = ActivityRenderer.lsp_query(label)
    widget = orch._write_card(card)
    orch._pending_read_symbols_card = widget


def _read_symbols_preview(event: ReadSymbolsObservation) -> str:
    statuses: dict[str, int] = {}
    lines: list[str] = []
    for item in event.results:
        status = str(item.get('status') or 'unknown')
        statuses[status] = statuses.get(status, 0) + 1
        target = str(
            item.get('qualified_name')
            or item.get('symbol_name')
            or item.get('target')
            or item.get('name')
            or ''
        ).strip()
        path = str(item.get('path') or '').strip()
        if target and path:
            lines.append(f'{status}: {target} ({path})')
        elif target:
            lines.append(f'{status}: {target}')
    summary = ', '.join(
        f'{count} {status}' for status, count in sorted(statuses.items())
    )
    if lines:
        return '\n'.join(([summary] if summary else []) + lines[:4])
    return summary or (event.error or event.content or '')


def _handle_read_symbols_observation(
    orch: '_AppRendererEventProcessorMixin', event: ReadSymbolsObservation
) -> None:
    preview = _read_symbols_preview(event)
    card = ActivityRenderer.lsp_query(
        f'{len(event.results)} symbol{"s" if len(event.results) != 1 else ""}',
        result=preview,
        available=not bool(event.error),
    )
    pending = orch._pending_read_symbols_card
    if pending is not None:
        orch._update_activity_card_outcome(
            pending,
            status='err' if event.error else 'ok',
            outcome=card.secondary or 'completed',
            extra_content=_build_lsp_preview(preview),
            operation_label=f'Read {len(event.results)} symbol{"s" if len(event.results) != 1 else ""}',
        )
        orch._pending_read_symbols_card = None
    else:
        orch._write_card(card)


def _handle_analyze_project_structure_action(
    orch: '_AppRendererEventProcessorMixin', event: AnalyzeProjectStructureAction
) -> None:
    card = ActivityRenderer.lsp_query(
        f'{event.command} {event.path}'.strip() or 'project structure'
    )
    widget = orch._write_card(card)
    orch._pending_analyze_project_structure_card = widget


def _handle_analyze_project_structure_observation(
    orch: '_AppRendererEventProcessorMixin',
    event: AnalyzeProjectStructureObservation,
) -> None:
    content = (event.error or event.content or '').strip()
    preview = _build_lsp_preview(content)
    card = ActivityRenderer.lsp_query(
        f'{event.command} {event.path}'.strip() or 'project structure',
        result=content,
        available=not bool(event.error),
    )
    pending = orch._pending_analyze_project_structure_card
    if pending is not None:
        orch._update_activity_card_outcome(
            pending,
            status='err' if event.error else 'ok',
            outcome=card.secondary or 'completed',
            extra_content=preview,
            operation_label=f'Analyzed {event.command}'.strip(),
        )
        orch._pending_analyze_project_structure_card = None
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
    submitted = _sanitize_terminal_display_text(getattr(event, 'input', '') or '')
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


def _sanitize_terminal_observation_content(content: str) -> str:
    if not content:
        return ''
    return _sanitize_terminal_display_text(
        strip_tool_result_validation_annotations(content)
    ).strip()


def _terminal_secondary_text(
    orch: '_AppRendererEventProcessorMixin',
    session_id: str,
    exit_code: int | None,
    state: str | None,
) -> str:
    label = orch._terminal_session_label(session_id)
    status = f'exit {exit_code}' if exit_code is not None else (state or None)
    return _join_secondary_parts(label, status)


def _terminal_secondary_kind(exit_code: int | None) -> str:
    if exit_code == 0:
        return 'ok'
    if exit_code is not None:
        return 'err'
    return 'neutral'


def _handle_terminal_observation(
    orch: '_AppRendererEventProcessorMixin', event: TerminalObservation
) -> None:
    content = event.content or ''
    session_id = getattr(event, 'session_id', '') or ''
    exit_code = getattr(event, 'exit_code', None)
    state = getattr(event, 'state', None)
    secondary = _terminal_secondary_text(orch, session_id, exit_code, state)
    secondary_kind = _terminal_secondary_kind(exit_code)
    content = _sanitize_terminal_observation_content(content)
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


def _resolve_delegate_task_and_worker(
    event: DelegateTaskAction,
) -> tuple[str, str]:
    task = getattr(event, 'task_description', '') or getattr(event, 'task', '') or ''
    worker = getattr(event, 'worker', '') or ''
    return task, worker


def _register_parallel_worker_tasks(
    orch: '_AppRendererEventProcessorMixin',
    event: DelegateTaskAction,
) -> None:
    for item in list(getattr(event, 'parallel_tasks', []) or []):
        task_desc = orch._summarize_worker_task(
            str(item.get('task_description') or 'delegated task')
        )
        orch._active_worker_tasks.append(task_desc)


def _handle_delegate_task_action(
    orch: '_AppRendererEventProcessorMixin', event: DelegateTaskAction
) -> None:
    task, worker = _resolve_delegate_task_and_worker(event)
    if getattr(event, 'parallel_tasks', None):
        _register_parallel_worker_tasks(orch, event)
    else:
        orch._active_worker_tasks.append(orch._summarize_worker_task(task))
    orch._sync_worker_strip()
    card = ActivityRenderer.delegation(task, worker)
    widget = orch._write_card(card)
    orch._pending_delegate_card = widget


def _record_delegate_result(
    orch: '_AppRendererEventProcessorMixin',
    resolved_task: str,
    success: bool,
) -> None:
    if success:
        orch._worker_completed += 1
    else:
        orch._worker_failed += 1
    if resolved_task:
        prefix = 'ok' if success else 'fail'
        orch._worker_recent_results.append(f'{prefix}: {resolved_task}')
    orch._sync_worker_strip()


def _build_delegate_preview(detail: str) -> str | None:
    if not detail:
        return None
    truncated = detail[:200] + ('...' if len(detail) > 200 else '')
    return f'  {truncated}'


def _resolve_delegate_card_detail(
    event: DelegateTaskObservation,
) -> tuple[str, str]:
    content = (event.content or '').strip()
    error_message = (getattr(event, 'error_message', '') or '').strip()
    return content, error_message


def _update_or_write_delegate_card(
    orch: '_AppRendererEventProcessorMixin',
    card: Any,
    resolved_task: str,
    success: bool,
    preview: str | None,
) -> None:
    pending = orch._pending_delegate_card
    if pending is not None:
        status = 'ok' if success else 'err'
        outcome = 'completed' if success else 'failed'
        orch._update_activity_card_outcome(
            pending,
            status=status,
            outcome=outcome,
            extra_content=preview,
            operation_label=f'Delegated {resolved_task}'.strip(),
        )
        orch._pending_delegate_card = None
    else:
        orch._write_card(card)


def _handle_delegate_task_observation(
    orch: '_AppRendererEventProcessorMixin', event: DelegateTaskObservation
) -> None:
    content, error_message = _resolve_delegate_card_detail(event)
    success = bool(getattr(event, 'success', True))
    resolved_task = (
        orch._active_worker_tasks.pop(0)
        if orch._active_worker_tasks
        else 'delegated task'
    )
    _record_delegate_result(orch, resolved_task, success)
    detail = error_message or content
    card = ActivityRenderer.delegation(
        resolved_task,
        result=detail,
        success=success,
    )
    preview = _build_delegate_preview(detail)
    _update_or_write_delegate_card(orch, card, resolved_task, success, preview)


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


def _render_memory_tool_card(
    orch: '_AppRendererEventProcessorMixin',
    content: str,
    *,
    kind: str,
    source_tool: str = '',
) -> None:
    text = (content or '').strip()
    if not text:
        return
    intent = ThinkingRenderIntent(
        kind=kind,  # type: ignore[arg-type]
        text=text,
        detail=text,
        source_tool=source_tool,
    )
    card = orch._thinking_artifact_card(intent)
    if card is not None:
        orch._write_card(card)


def _handle_checkpoint_observation(
    orch: '_AppRendererEventProcessorMixin', event: CheckpointObservation
) -> None:
    _render_memory_tool_card(
        orch, event.content, kind='checkpoint', source_tool='checkpoint'
    )


def _handle_working_memory_observation(
    orch: '_AppRendererEventProcessorMixin', event: WorkingMemoryObservation
) -> None:
    _render_memory_tool_card(orch, event.content, kind='memory')


def _handle_memory_persist_observation(
    orch: '_AppRendererEventProcessorMixin', event: MemoryPersistObservation
) -> None:
    _render_memory_tool_card(orch, event.content, kind='memory')


def _handle_memory_recall_observation(
    orch: '_AppRendererEventProcessorMixin', event: MemoryRecallObservation
) -> None:
    _render_memory_tool_card(orch, event.content, kind='memory')


def _handle_scratchpad_note_observation(
    orch: '_AppRendererEventProcessorMixin', event: ScratchpadNoteObservation
) -> None:
    _render_memory_tool_card(orch, event.content, kind='memory')


def _handle_scratchpad_recall_observation(
    orch: '_AppRendererEventProcessorMixin', event: ScratchpadRecallObservation
) -> None:
    _render_memory_tool_card(orch, event.content, kind='memory')


def _handle_checkpoint_action(
    orch: '_AppRendererEventProcessorMixin', event: CheckpointAction
) -> None:
    detail = event.label or event.command or 'checkpoint'
    _render_memory_tool_card(orch, detail, kind='checkpoint', source_tool='checkpoint')


def _handle_working_memory_action(
    orch: '_AppRendererEventProcessorMixin', event: WorkingMemoryAction
) -> None:
    detail = f'{event.command} {event.section}'.strip()
    _render_memory_tool_card(orch, detail, kind='memory')


def _handle_memory_persist_action(
    orch: '_AppRendererEventProcessorMixin', event: MemoryPersistAction
) -> None:
    _render_memory_tool_card(orch, event.key or 'persist', kind='memory')


def _handle_memory_recall_action(
    orch: '_AppRendererEventProcessorMixin', event: MemoryRecallAction
) -> None:
    _render_memory_tool_card(orch, event.query or 'recall', kind='memory')


def _handle_scratchpad_note_action(
    orch: '_AppRendererEventProcessorMixin', event: ScratchpadNoteAction
) -> None:
    _render_memory_tool_card(orch, event.key or 'note', kind='memory')


def _handle_scratchpad_recall_action(
    orch: '_AppRendererEventProcessorMixin', event: ScratchpadRecallAction
) -> None:
    _render_memory_tool_card(orch, event.key or 'recall', kind='memory')


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------


_TOOL_EXECUTION_TYPES = (
    FileReadAction,
    FileEditAction,
    FileWriteAction,
    CmdRunAction,
    MCPAction,
    BrowserToolAction,
    BrowseInteractiveAction,
    GrepAction,
    GlobAction,
    FindSymbolsAction,
    ReadSymbolsAction,
    AnalyzeProjectStructureAction,
    LspQueryAction,
    TerminalRunAction,
    TerminalInputAction,
    TerminalReadAction,
    RecallAction,
    DelegateTaskAction,
)


def _process_event_is_noop(event: Any) -> bool:
    if isinstance(event, NullAction) or isinstance(event, NullObservation):
        return True
    return isinstance(event, ChangeAgentStateAction)


def _process_event_check_user_message(
    orch: '_AppRendererEventProcessorMixin', event: Any
) -> None:
    source = getattr(event, 'source', None)
    if isinstance(event, MessageAction) and orch._is_user_source(source):
        orch._last_thinking_text_hash = ''
        orch._last_thinking_artifact_hash = ''


def _process_event_maybe_start_turn(
    orch: '_AppRendererEventProcessorMixin', event: Any
) -> None:
    if orch._in_agent_turn:
        return
    if isinstance(
        event,
        (MessageAction, StreamingChunkAction, AgentStateChangedObservation),
    ):
        return
    orch._in_agent_turn = True
    orch._turn_count += 1
    orch._tools_in_turn = 0
    orch._turn_start_time = time.monotonic()


def _process_event_finalize_thinking(
    orch: '_AppRendererEventProcessorMixin', event: Any
) -> None:
    if orch._is_live_thinking_event(event):
        return
    if getattr(orch, '_streaming_active', False):
        return
    orch._finalize_live_thinking()


def _process_event_commit_response(
    orch: '_AppRendererEventProcessorMixin', event: Any, is_tool: bool
) -> None:
    if isinstance(event, (MessageAction, StreamingChunkAction)):
        return
    if orch._live_response_dirty:
        if is_tool:
            orch.clear_live_response()
        else:
            orch._commit_final_response(orch._live_response)
    else:
        orch.clear_live_response()


def _process_event(orch: '_AppRendererEventProcessorMixin', event: Any) -> None:
    event_id = getattr(event, 'id', -1)
    replay_mode = getattr(orch, '_replay_mode', False)
    if (
        replay_mode
        and event_id >= 0
        and event_id in getattr(orch, '_mounted_event_ids', set())
    ):
        return
    orch._current_event_id = event_id
    if not replay_mode:
        orch._update_metrics(event)
    if _process_event_is_noop(event):
        return
    if not replay_mode:
        _process_event_check_user_message(orch, event)
        _process_event_maybe_start_turn(orch, event)
        is_tool = isinstance(event, _TOOL_EXECUTION_TYPES)
        if orch._in_agent_turn and is_tool:
            orch._tools_in_turn += 1
        _process_event_finalize_thinking(orch, event)
        _process_event_commit_response(orch, event, is_tool)
    _dispatch_event(orch, event)
    if event_id >= 0:
        mounted = getattr(orch, '_mounted_event_ids', None)
        if mounted is not None:
            mounted.add(event_id)
        order = getattr(orch, '_event_order', None)
        if order is not None and event_id not in order:
            order.append(event_id)
    orch._current_event_id = -1
    if not getattr(orch, '_async_drain_active', False):
        flush_sync = getattr(orch, 'flush_pending_final_commits_sync', None)
        if callable(flush_sync):
            flush_sync()


def _handle_noop_event(orch: '_AppRendererEventProcessorMixin', event: Any) -> None:
    pass


def _handle_compaction_trigger(
    orch: '_AppRendererEventProcessorMixin', event: Any
) -> None:
    _show_compaction_started_card(orch)


def _handle_streaming_chunk_dispatch(
    orch: '_AppRendererEventProcessorMixin', event: StreamingChunkAction
) -> None:
    orch._handle_streaming_chunk(event)


def _handle_state_change_dispatch(
    orch: '_AppRendererEventProcessorMixin', event: AgentStateChangedObservation
) -> None:
    orch._handle_state_change(event)


def _handle_clarification_dispatch(
    orch: '_AppRendererEventProcessorMixin', event: ClarificationRequestAction
) -> None:
    orch._tui.add_communicate_clarification(event)


def _handle_confirm_dispatch(
    orch: '_AppRendererEventProcessorMixin', event: ConfirmRequestAction
) -> None:
    if not _is_full_autonomy(orch):
        orch._tui.add_communicate_confirm(event)


def _handle_inform_dispatch(
    orch: '_AppRendererEventProcessorMixin', event: InformAction
) -> None:
    orch._tui.add_communicate_inform(event)


def _handle_uncertainty_dispatch(
    orch: '_AppRendererEventProcessorMixin', event: UncertaintyAction
) -> None:
    orch._tui.add_communicate_uncertainty(event)


def _handle_proposal_dispatch(
    orch: '_AppRendererEventProcessorMixin', event: ProposalAction
) -> None:
    orch._tui.add_communicate_proposal(event)


def _handle_escalate_dispatch(
    orch: '_AppRendererEventProcessorMixin', event: EscalateToHumanAction
) -> None:
    orch._tui.add_communicate_escalate(event)


def _handle_user_reject_dispatch(
    orch: '_AppRendererEventProcessorMixin', event: UserRejectObservation
) -> None:
    card = ActivityRenderer.user_reject()
    orch._write_card(card)


def _handle_server_ready_dispatch(
    orch: '_AppRendererEventProcessorMixin', event: ServerReadyObservation
) -> None:
    url = getattr(event, 'url', '')
    port = getattr(event, 'port', '')
    card = ActivityRenderer.server_ready(url, port)
    orch._write_card(card)


def _handle_file_download_dispatch(
    orch: '_AppRendererEventProcessorMixin', event: FileDownloadObservation
) -> None:
    url = getattr(event, 'url', '') or ''
    orch._tui._write_log(
        Text(f'  [bold #91abec]Downloaded[/] {url}', style=NAVY_TEXT_PRIMARY)
    )


def _handle_unknown_event(orch: '_AppRendererEventProcessorMixin', event: Any) -> None:
    name = type(event).__name__
    orch._tui._write_log(Text(f'  [{name}]', style=NAVY_TEXT_MUTED))


def _dispatch_event(orch: '_AppRendererEventProcessorMixin', event: Any) -> None:
    event_type = type(event)
    handler = _EVENT_HANDLERS.get(event_type)
    if handler is not None:
        handler(orch, event)
        return
    fallback = _FALLBACK_HANDLERS.get(event_type)
    if fallback is not None:
        fallback(orch, event)
        return
    _handle_unknown_event(orch, event)


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
    GrepAction: _handle_grep_action,
    GlobAction: _handle_glob_action,
    FindSymbolsAction: _handle_find_symbols_action,
    ReadSymbolsAction: _handle_read_symbols_action,
    AnalyzeProjectStructureAction: _handle_analyze_project_structure_action,
    LspQueryAction: _handle_lsp_query_action,
    GrepObservation: _handle_grep_observation,
    GlobObservation: _handle_glob_observation,
    FindSymbolsObservation: _handle_find_symbols_observation,
    ReadSymbolsObservation: _handle_read_symbols_observation,
    AnalyzeProjectStructureObservation: _handle_analyze_project_structure_observation,
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
    CheckpointAction: _handle_checkpoint_action,
    WorkingMemoryAction: _handle_working_memory_action,
    MemoryPersistAction: _handle_memory_persist_action,
    MemoryRecallAction: _handle_memory_recall_action,
    ScratchpadNoteAction: _handle_scratchpad_note_action,
    ScratchpadRecallAction: _handle_scratchpad_recall_action,
    CheckpointObservation: _handle_checkpoint_observation,
    WorkingMemoryObservation: _handle_working_memory_observation,
    MemoryPersistObservation: _handle_memory_persist_observation,
    MemoryRecallObservation: _handle_memory_recall_observation,
    ScratchpadNoteObservation: _handle_scratchpad_note_observation,
    ScratchpadRecallObservation: _handle_scratchpad_recall_observation,
}

_FALLBACK_HANDLERS: dict[type, Any] = {
    RecallAction: _handle_noop_event,
    CondensationRequestAction: _handle_compaction_trigger,
    RecallObservation: _handle_noop_event,
    RecallFailureObservation: _handle_noop_event,
    CondensationAction: _handle_compaction_trigger,
    StreamingChunkAction: _handle_streaming_chunk_dispatch,
    AgentStateChangedObservation: _handle_state_change_dispatch,
    ClarificationRequestAction: _handle_clarification_dispatch,
    ConfirmRequestAction: _handle_confirm_dispatch,
    InformAction: _handle_inform_dispatch,
    UncertaintyAction: _handle_uncertainty_dispatch,
    ProposalAction: _handle_proposal_dispatch,
    EscalateToHumanAction: _handle_escalate_dispatch,
    UserRejectObservation: _handle_user_reject_dispatch,
    ServerReadyObservation: _handle_server_ready_dispatch,
    FileDownloadObservation: _handle_file_download_dispatch,
}
