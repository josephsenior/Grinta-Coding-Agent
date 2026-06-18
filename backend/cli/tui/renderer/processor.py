"""Event-dispatch state machine for :class:`RendererEventProcessorMixin`.

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

from backend.cli.tool_display.orient_tools import ORIENT_MCP_TOOL_NAMES
from backend.cli.tui.renderer.handlers.browser import (
    _handle_browse_interactive_action,
    _handle_browser_screenshot_observation,
    _handle_browser_tool_action,
)
from backend.cli.tui.renderer.handlers.compaction import (
    _handle_agent_condensation_observation,
    _handle_compaction_trigger,
    show_compaction_started_card,
)
from backend.cli.tui.renderer.handlers.debugger import (
    _handle_debugger_action,
    _handle_debugger_observation,
)
from backend.cli.tui.renderer.handlers.delegate import (
    _handle_delegate_task_action,
    _handle_delegate_task_observation,
)
from backend.cli.tui.renderer.handlers.exploration import (
    _handle_analyze_project_structure_action,
    _handle_analyze_project_structure_observation,
    _handle_find_symbols_action,
    _handle_find_symbols_observation,
    _handle_glob_action,
    _handle_glob_observation,
    _handle_grep_action,
    _handle_grep_observation,
    _handle_lsp_query_action,
    _handle_lsp_query_observation,
    _handle_read_symbols_action,
    _handle_read_symbols_observation,
)
from backend.cli.tui.renderer.handlers.fallback import (
    _handle_file_download_dispatch,
    _handle_legacy_meta_cognition_dispatch,
    _handle_noop_event,
    _handle_server_ready_dispatch,
    _handle_state_change_dispatch,
    _handle_streaming_chunk_dispatch,
    _handle_unknown_event,
    _handle_user_reject_dispatch,
)
from backend.cli.tui.renderer.handlers.file import (
    _handle_file_edit_action,
    _handle_file_edit_observation,
    _handle_file_read_action,
    _handle_file_read_observation,
)
from backend.cli.tui.renderer.handlers.mcp import (
    _handle_mcp_action,
    _handle_mcp_observation,
)
from backend.cli.tui.renderer.handlers.memory import (
    _handle_checkpoint_action,
    _handle_checkpoint_observation,
    _handle_memory_persist_action,
    _handle_memory_persist_observation,
    _handle_memory_recall_action,
    _handle_memory_recall_observation,
    _handle_scratchpad_note_action,
    _handle_scratchpad_note_observation,
    _handle_scratchpad_recall_action,
    _handle_scratchpad_recall_observation,
    _handle_working_memory_action,
    _handle_working_memory_observation,
)
from backend.cli.tui.renderer.handlers.shell import (
    _handle_cmd_output_observation,
    _handle_cmd_run_action,
)
from backend.cli.tui.renderer.handlers.status import (
    _handle_error_observation,
    _handle_status_observation,
    _handle_success_observation,
)
from backend.cli.tui.renderer.handlers.task_tracking import (
    _handle_task_tracking_action,
    _handle_task_tracking_observation,
)
from backend.cli.tui.renderer.handlers.terminal import (
    _handle_terminal_input_action,
    _handle_terminal_observation,
    _handle_terminal_read_action,
    _handle_terminal_run_action,
)
from backend.cli.tui.renderer.handlers.thinking import (
    _handle_agent_think_action,
    _handle_agent_think_observation,
)
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
    DebuggerAction,
    DelegateTaskAction,
    EscalateToHumanAction,
    FileEditAction,
    FileReadAction,
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
    DebuggerObservation,
    DelegateTaskObservation,
    ErrorObservation,
    FileDownloadObservation,
    FileEditObservation,
    FileReadObservation,
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
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
    )


# Re-export for RendererEventProcessorMixin.
_show_compaction_started_card = show_compaction_started_card


# ---------------------------------------------------------------------------
# Per-event-type handlers
# ---------------------------------------------------------------------------


def _handle_message_action(
    orch: 'RendererEventProcessorMixin', event: MessageAction
) -> None:
    source = getattr(event, 'source', None)
    if orch._is_user_source(source):
        return
    orch._handle_message_action(event)


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------


_TOOL_EXECUTION_TYPES = (
    FileReadAction,
    FileEditAction,
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
    DebuggerAction,
    TerminalRunAction,
    TerminalInputAction,
    TerminalReadAction,
    RecallAction,
    DelegateTaskAction,
)

_ORIENT_EVENT_TYPES = (
    FileReadAction,
    FileReadObservation,
    GrepAction,
    GrepObservation,
    GlobAction,
    GlobObservation,
    FindSymbolsAction,
    FindSymbolsObservation,
    ReadSymbolsAction,
    ReadSymbolsObservation,
    AnalyzeProjectStructureAction,
    AnalyzeProjectStructureObservation,
    LspQueryAction,
    LspQueryObservation,
)

_ORIENT_NEUTRAL_EVENT_TYPES = (
    AgentThinkAction,
    AgentThinkObservation,
    StreamingChunkAction,
    StatusObservation,
    NullAction,
    NullObservation,
)


def _is_orient_event(event: Any) -> bool:
    if isinstance(event, _ORIENT_EVENT_TYPES):
        return True
    if isinstance(event, (MCPAction, MCPObservation)):
        return str(getattr(event, 'name', '') or '') in ORIENT_MCP_TOOL_NAMES
    return False


def _maybe_flush_orient_burst(
    orch: 'RendererEventProcessorMixin',
    event: Any,
) -> None:
    if _is_orient_event(event):
        return
    if isinstance(event, _ORIENT_NEUTRAL_EVENT_TYPES):
        return
    flush = getattr(orch, '_flush_orient_burst', None)
    if callable(flush):
        flush()


def _process_event_is_noop(event: Any) -> bool:
    if isinstance(event, NullAction) or isinstance(event, NullObservation):
        return True
    return isinstance(event, ChangeAgentStateAction)


def _process_event_check_user_message(
    orch: 'RendererEventProcessorMixin', event: Any
) -> None:
    source = getattr(event, 'source', None)
    if isinstance(event, MessageAction) and orch._is_user_source(source):
        orch._last_thinking_text_hash = ''
        orch._last_thinking_artifact_hash = ''


def _process_event_maybe_start_turn(
    orch: 'RendererEventProcessorMixin', event: Any
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
    orch: 'RendererEventProcessorMixin', event: Any
) -> None:
    if orch._is_live_thinking_event(event):
        return
    if getattr(orch, '_streaming_active', False):
        return
    orch._finalize_live_thinking()


def _process_event_commit_response(
    orch: 'RendererEventProcessorMixin', event: Any, is_tool: bool
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


def _process_event(orch: 'RendererEventProcessorMixin', event: Any) -> None:
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
    _maybe_flush_orient_burst(orch, event)
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


def _dispatch_event(orch: 'RendererEventProcessorMixin', event: Any) -> None:
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
    FileReadObservation: _handle_file_read_observation,
    FileEditObservation: _handle_file_edit_observation,
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
    DebuggerAction: _handle_debugger_action,
    GrepObservation: _handle_grep_observation,
    GlobObservation: _handle_glob_observation,
    FindSymbolsObservation: _handle_find_symbols_observation,
    ReadSymbolsObservation: _handle_read_symbols_observation,
    AnalyzeProjectStructureObservation: _handle_analyze_project_structure_observation,
    LspQueryObservation: _handle_lsp_query_observation,
    DebuggerObservation: _handle_debugger_observation,
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
    ClarificationRequestAction: _handle_legacy_meta_cognition_dispatch,
    ConfirmRequestAction: _handle_legacy_meta_cognition_dispatch,
    InformAction: _handle_legacy_meta_cognition_dispatch,
    UncertaintyAction: _handle_legacy_meta_cognition_dispatch,
    ProposalAction: _handle_legacy_meta_cognition_dispatch,
    EscalateToHumanAction: _handle_legacy_meta_cognition_dispatch,
    UserRejectObservation: _handle_user_reject_dispatch,
    ServerReadyObservation: _handle_server_ready_dispatch,
    FileDownloadObservation: _handle_file_download_dispatch,
}
