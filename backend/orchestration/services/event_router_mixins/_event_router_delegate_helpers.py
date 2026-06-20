"""Module-level helper functions for delegate task progress events.

Extracted from backend/orchestration/services/event_router_service.py
to keep the parent module under the per-file LOC budget. These are
pure functions used by the _EventRouterDelegateMixin to build
progress observations from worker events.
"""

from __future__ import annotations

from backend.core.tools.tool_transport import contains_tool_transport_markup
from backend.core.schemas import AgentState
from backend.ledger.action import (
    Action,
    AgentRejectAction,
    CmdRunAction,
    FileEditAction,
    FileReadAction,
    MCPAction,
    MessageAction,
    TaskTrackingAction,
)
from backend.ledger.action.agent import (
    AgentThinkAction,
    RecallAction,
)
from backend.ledger.action.browse import BrowseInteractiveAction
from backend.ledger.action.browser_tool import BrowserToolAction
from backend.ledger.observation import (
    ErrorObservation,
    Observation,
    StatusObservation,
)
from backend.ledger.observation.agent import (
    AgentStateChangedObservation,
)

_DELEGATE_PROGRESS_STATUS = 'delegate_progress'


def _truncate_delegate_progress(text: str, limit: int = 120) -> str:
    collapsed = ' '.join((text or '').split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(limit - 1, 0)].rstrip() + '…'


def _looks_like_text_tool_call_handoff(text: str) -> bool:
    return contains_tool_transport_markup(text)


def _summarize_delegate_file_action(
    event: Action | Observation,
) -> tuple[str, str] | None:
    if isinstance(event, FileReadAction):
        view_range = getattr(event, 'view_range', None)
        loc = (
            f' L{view_range[0]}:L{view_range[1]}'
            if view_range and len(view_range) == 2
            else ''
        )
        return 'running', f'Read {event.path}{loc}'

    if isinstance(event, FileEditAction):
        command = getattr(event, 'command', '') or ''
        if command == 'create_file':
            return 'running', f'Created {event.path}'
        if command == 'read_file':
            region = ''
            vr = getattr(event, 'view_range', None)
            if vr and len(vr) == 2:
                region = f' L{vr[0]}:L{vr[1]}'
            return 'running', f'Read {event.path}{region}'
        return 'running', f'Edited {event.path}'

    return None


def _summarize_delegate_command_action(
    event: Action | Observation,
) -> tuple[str, str] | None:
    if not isinstance(event, CmdRunAction):
        return None
    label = getattr(event, 'display_label', '') or getattr(event, 'command', '')
    label = _truncate_delegate_progress(label, limit=96)
    return 'running', f'Ran {label}' if label else 'Ran command'


def _summarize_delegate_mcp_action(
    event: Action | Observation,
) -> tuple[str, str] | None:
    if not isinstance(event, MCPAction):
        return None
    tool_name = getattr(event, 'name', '') or 'MCP tool'
    return 'running', f'Called {tool_name}'


def _summarize_delegate_think_action(
    event: Action | Observation,
) -> tuple[str, str] | None:
    """Forward worker reasoning/thought as a progress detail."""
    if not isinstance(event, AgentThinkAction):
        return None
    suppress = bool(getattr(event, 'suppress_cli', False))
    if suppress:
        return None
    thought = (
        getattr(event, 'thought', '') or getattr(event, 'content', '') or ''
    ).strip()
    if not thought:
        return None
    # Only forward first line of reasoning to keep it compact
    first_line = thought.splitlines()[0].strip()
    first_line = _truncate_delegate_progress(first_line, limit=80)
    if not first_line:
        return None
    return 'running', first_line


def _summarize_delegate_recall_action(
    event: Action | Observation,
) -> tuple[str, str] | None:
    if not isinstance(event, RecallAction):
        return None
    query = getattr(event, 'query', '') or ''
    query = _truncate_delegate_progress(query, limit=60)
    return 'running', f'Searched: {query}' if query else 'Searched context'


def _summarize_delegate_task_tracking_action(
    event: Action | Observation,
) -> tuple[str, str] | None:
    if not isinstance(event, TaskTrackingAction):
        return None
    cmd = str(getattr(event, 'command', '') or '').strip().lower()
    task_list = getattr(event, 'task_list', None)
    if cmd == 'update' and isinstance(task_list, list):
        return 'running', f'Updated {len(task_list)} task(s)'
    return None


def _summarize_delegate_browser_action(
    event: Action | Observation,
) -> tuple[str, str] | None:
    if isinstance(event, BrowserToolAction):
        cmd = getattr(event, 'command', '') or 'browser'
        params = getattr(event, 'params', None) or {}
        url = params.get('url') if isinstance(params, dict) else None
        if url:
            return (
                'running',
                f'Browser {cmd}: {_truncate_delegate_progress(str(url), 60)}',
            )
        return 'running', f'Browser {cmd}'
    if isinstance(event, BrowseInteractiveAction):
        ba = getattr(event, 'browser_actions', '') or ''
        url = next(
            (
                token.strip('\'")]},>')
                for token in ba.split()
                if token.startswith(('http://', 'https://'))
            ),
            '',
        )
        if url:
            url = _truncate_delegate_progress(url, 60)
            return 'running', f'Browsing {url}'
        return 'running', 'Browsing…'  # type: ignore[unreachable]
    return None


def _summarize_delegate_finish_event(
    event: Action | Observation,
) -> tuple[str, str] | None:
    if not (
        isinstance(event, MessageAction)
        and bool(getattr(event, 'final_response', False))
    ):
        return None
    content = str(getattr(event, 'content', '') or '').strip()
    summary = _truncate_delegate_progress(content.splitlines()[0], 140)
    return 'done', summary or 'Completed'


def _summarize_delegate_reject_event(
    event: Action | Observation,
) -> tuple[str, str] | None:
    if not isinstance(event, AgentRejectAction):
        return None
    reason = _truncate_delegate_progress(
        str(event.outputs.get('reason', '') or ''), 140
    )
    return 'failed', reason or 'Rejected delegated task'


def _summarize_delegate_error_event(
    event: Action | Observation,
) -> tuple[str, str] | None:
    if not isinstance(event, ErrorObservation):
        return None
    first_line = _truncate_delegate_progress((event.content or '').splitlines()[0], 140)
    return 'failed', first_line or 'Worker error'


def _summarize_delegate_state_event(
    event: Action | Observation,
) -> tuple[str, str] | None:
    if not isinstance(event, AgentStateChangedObservation):
        return None
    state = str(getattr(event, 'agent_state', '') or '').lower()
    if state == AgentState.ERROR.value:
        return 'failed', 'Worker entered error state'
    if state == AgentState.FINISHED.value:
        return 'done', 'Completed'
    return None


def _summarize_delegate_terminal_event(
    event: Action | Observation,
) -> tuple[str, str] | None:
    for summarizer in (
        _summarize_delegate_finish_event,
        _summarize_delegate_reject_event,
        _summarize_delegate_error_event,
        _summarize_delegate_state_event,
    ):
        if result := summarizer(event):
            return result
    return None


def _summarize_delegate_worker_event(
    event: Action | Observation,
) -> tuple[str, str] | None:
    """Return a compact worker-progress summary for parent-side swarm UI."""
    for summarizer in (
        _summarize_delegate_file_action,
        _summarize_delegate_command_action,
        _summarize_delegate_think_action,
        _summarize_delegate_recall_action,
        _summarize_delegate_task_tracking_action,
        _summarize_delegate_browser_action,
        _summarize_delegate_mcp_action,
        _summarize_delegate_terminal_event,
    ):
        if result := summarizer(event):
            return result
    return None


def _build_delegate_progress_observation(
    *,
    worker_id: str,
    worker_label: str,
    task_description: str,
    status: str,
    detail: str,
    order: int,
    batch_id: int | None = None,
) -> StatusObservation:
    """Create a CLI-only hidden status observation for delegated worker progress."""
    task_text = _truncate_delegate_progress(task_description, 96)
    detail_text = _truncate_delegate_progress(detail, 140)
    content = f'{worker_label} · {detail_text or task_text or status}'
    obs = StatusObservation(
        content=content,
        status_type=_DELEGATE_PROGRESS_STATUS,
        extras={
            'worker_id': worker_id,
            'worker_label': worker_label,
            'task_description': task_text,
            'worker_status': status,
            'detail': detail_text,
            'order': order,
            'batch_id': batch_id,
        },
    )
    obs.hidden = True
    return obs
