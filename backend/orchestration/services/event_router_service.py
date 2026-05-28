"""Event routing service for SessionOrchestrator.

Routes incoming events from the EventStream to appropriate handlers. Centralizes
all event dispatch logic that was previously inline in SessionOrchestrator._on_event.
"""

from __future__ import annotations

import asyncio
import os as _os
from typing import TYPE_CHECKING

from backend.core.interaction_modes import (
    CHAT_MODE_NAMES,
    normalize_interaction_mode,
)
from backend.core.schemas import AgentState
from backend.core.task_status import ACTIVE_TASK_STATUSES
from backend.ledger import EventSource, EventStream, EventStreamSubscriber, RecallType
from backend.ledger.action import (
    Action,
    AgentRejectAction,
    ChangeAgentStateAction,
    CmdRunAction,
    FileEditAction,
    FileReadAction,
    FileWriteAction,
    MCPAction,
    MessageAction,
    PlaybookFinishAction,
    TaskTrackingAction,
)
from backend.ledger.action.agent import (
    AgentThinkAction,
    ClarificationRequestAction,
    DelegateTaskAction,
    EscalateToHumanAction,
    ProposalAction,
    RecallAction,
    UncertaintyAction,
)
from backend.ledger.action.browse import BrowseInteractiveAction
from backend.ledger.action.browser_tool import BrowserToolAction
from backend.ledger.action.message import StreamingChunkAction
from backend.ledger.observation import (
    ErrorObservation,
    Observation,
    StatusObservation,
)
from backend.ledger.observation.agent import (
    AgentStateChangedObservation,
    DelegateTaskObservation,
)
from backend.ledger.observation_cause import attach_observation_cause

if TYPE_CHECKING:
    from backend.ledger.event import Event
    from backend.orchestration.session_orchestrator import SessionOrchestrator


_DELEGATE_PROGRESS_STATUS = 'delegate_progress'
_TEXT_TOOL_CALL_MARKERS = (
    '<minimax:tool_call',
    '</minimax:tool_call>',
    '<tool_call',
    '</tool_call>',
)


def _truncate_delegate_progress(text: str, limit: int = 120) -> str:
    collapsed = ' '.join((text or '').split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(limit - 1, 0)].rstrip() + '…'


def _looks_like_text_tool_call_handoff(text: str) -> bool:
    low = (text or '').lower()
    return any(marker in low for marker in _TEXT_TOOL_CALL_MARKERS)


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

    if isinstance(event, FileWriteAction):
        return 'running', f'Created {event.path}'

    if not isinstance(event, FileEditAction):
        return None

    command = getattr(event, 'command', '') or ''
    if command == 'read_file':
        region = ''
        vr = getattr(event, 'view_range', None)
        if vr and len(vr) == 2:
            region = f' L{vr[0]}:L{vr[1]}'
        return 'running', f'Read {event.path}{region}'
    return 'running', f'Edited {event.path}'


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
    if not isinstance(event, PlaybookFinishAction):
        return None
    summary = _truncate_delegate_progress((event.message or '').splitlines()[0], 140)
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


class EventRouterService:
    """Routes events to the correct handler on SessionOrchestrator.

    Separates the *what-to-do-with-events* concern from the controller's
    step-execution and lifecycle management.
    """

    def __init__(self, controller: SessionOrchestrator) -> None:
        self._ctrl = controller

    async def _handle_change_state_action(self, action: ChangeAgentStateAction) -> None:
        try:
            target_state = AgentState(action.agent_state)
        except ValueError:
            self._ctrl.log(
                'warning',
                "Received unknown agent state '%s', ignoring.",
                extra={'agent_state': action.agent_state},
            )
            return

        if (
            target_state == AgentState.AWAITING_USER_INPUT
            and action.source == EventSource.ENVIRONMENT
            and self._ctrl.get_agent_state() == AgentState.RUNNING
        ):
            self._ctrl.log(
                'debug',
                'Discarding stale startup ChangeAgentStateAction(AWAITING_USER_INPUT) '
                '— agent is already RUNNING',
            )
            return

        await self._ctrl.set_agent_state_to(target_state)

    @staticmethod
    def _is_meta_cognition_action(action: Action) -> bool:
        return isinstance(
            action,
            (
                ClarificationRequestAction,
                ProposalAction,
                UncertaintyAction,
                EscalateToHumanAction,
            ),
        )

    def _first_user_message(self) -> MessageAction | None:
        return next(
            (
                event
                for event in self._ctrl.event_stream.search_events(
                    start_id=self._ctrl.state.start_id
                )
                if isinstance(event, MessageAction) and event.source == EventSource.USER
            ),
            None,
        )

    def _recall_type_for_user_message(self, action: MessageAction) -> RecallType:
        first_user_message = self._first_user_message()
        is_first = action.id == first_user_message.id if first_user_message else False
        return RecallType.WORKSPACE_CONTEXT if is_first else RecallType.KNOWLEDGE

    def _set_pending_recall(
        self, recall_action: RecallAction, recall_type: RecallType
    ) -> None:
        pending_service = getattr(self._ctrl, 'pending_action_service', None)
        if recall_type == RecallType.WORKSPACE_CONTEXT:
            if pending_service is not None:
                pending_service.set(recall_action)
                return

            action_service = getattr(self._ctrl, 'action_service', None)
            if action_service is not None:
                action_service.set_pending_action(recall_action)
            return

        if pending_service is not None:
            pending_service.set(None)

        cb_svc = getattr(self._ctrl, 'circuit_breaker_service', None)
        if cb_svc is not None:
            cb_svc.reset_for_new_turn()

        state = getattr(self._ctrl, 'state', None)
        if state is not None:
            state.extra_data.pop('__step_guard_warning_trip_counts', None)

    async def _ensure_running_for_user_message(self) -> None:
        if self._ctrl.get_agent_state() != AgentState.RUNNING:
            await self._ctrl.set_agent_state_to(AgentState.RUNNING)

    # ── public entry point ────────────────────────────────────────────

    async def route_event(self, event: Event) -> None:
        """Dispatch a single event to the appropriate handler.

        Hidden events are silently dropped.  Plugin hooks fire first.
        """
        if hasattr(event, 'hidden') and event.hidden:
            return

        # Plugin hook: event_emitted
        try:
            from backend.core.plugin import get_plugin_registry

            await get_plugin_registry().dispatch_event(event)
        except Exception as exc:
            self._ctrl.log(
                'warning',
                f'Plugin event_emitted hook failed for {type(event).__name__}: {exc}',
                extra={'msg_type': 'PLUGIN_EVENT_HOOK'},
            )

        # StreamingChunkAction events are transient display hints — they
        # must NOT be added to the history that the LLM sees on the next
        # step, otherwise the context window fills up with chunk noise.
        if not isinstance(event, StreamingChunkAction):
            self._ctrl.state_tracker.add_history(event)

        if isinstance(event, Action):
            await self._handle_action(event)
        elif isinstance(event, Observation):
            await self._handle_observation(event)

    # ── action dispatch ───────────────────────────────────────────────

    async def _handle_action(self, action: Action) -> None:
        """Route an Action to its specific handler."""
        if isinstance(action, ChangeAgentStateAction):
            await self._handle_change_state_action(action)
            return

        for action_type, handler in (
            (MessageAction, self._handle_message_action),
            (PlaybookFinishAction, self._handle_finish_action),
            (AgentRejectAction, self._handle_reject_action),
            (TaskTrackingAction, self._handle_task_tracking_action),
            (DelegateTaskAction, self._handle_delegate_task_action),
        ):
            if isinstance(action, action_type):
                await handler(action)  # type: ignore[arg-type]
                return

        if self._is_meta_cognition_action(action):
            await self._handle_meta_cognition_action(action)

    async def _handle_task_tracking_action(self, action: TaskTrackingAction) -> None:
        """Handle task tracking action to update active plan."""
        from backend.orchestration.state.state import build_active_plan_from_payload

        try:
            current_plan = self._ctrl.state.plan
            current_title = current_plan.title if current_plan else 'Current Plan'
            self._ctrl.state.plan = build_active_plan_from_payload(
                action.task_list,
                title=current_title,
            )
            self._ctrl.log('info', f'Plan updated with {len(action.task_list)} steps.')
        except Exception as e:
            self._ctrl.log('error', f'Failed to update plan: {e}')

    async def _handle_finish_action(self, action: PlaybookFinishAction) -> None:
        """Handle agent finish action with completion validation."""
        if not await self._ctrl.task_validation_service.handle_finish(action):
            return
        self._ctrl.state.set_outputs(action.outputs, source='EventRouterService.finish')
        self._ctrl.state.extra_data.pop('active_run_mode', None)
        await self._ctrl.set_agent_state_to(AgentState.FINISHED)
        await self._ctrl.log_task_audit(status='success')
        await self._run_critics()

    async def _run_critics(self) -> None:
        """Retained lifecycle hook after finish; review critics were removed."""
        return

    async def _handle_reject_action(self, action: AgentRejectAction) -> None:
        """Handle agent reject action."""
        self._ctrl.state.set_outputs(action.outputs, source='EventRouterService.reject')
        await self._ctrl.set_agent_state_to(AgentState.REJECTED)

    async def _handle_message_action(self, action: MessageAction) -> None:
        """Handle message actions from users or agents."""
        if action.source == EventSource.USER:
            await self._handle_user_message(action)
        elif action.source == EventSource.AGENT:
            if action.wait_for_response:
                if await self._intercept_text_tool_call_handoff(action):
                    return
                if self._task_tracker_has_unfinished_tasks():
                    if await self._intercept_protocol_message_handoff(action):
                        return
                await self._ctrl.set_agent_state_to(AgentState.AWAITING_USER_INPUT)

    def _task_tracker_has_unfinished_tasks(self) -> bool:
        state = getattr(self._ctrl, 'state', None)
        return self._plan_has_active_steps(getattr(state, 'plan', None))

    def _plan_has_active_steps(self, plan: object | None) -> bool:
        if plan is None:
            return False
        steps = getattr(plan, 'steps', None) or []
        return self._steps_have_active_status(steps)

    def _steps_have_active_status(self, steps: object) -> bool:
        if not isinstance(steps, list):
            return False
        for step in steps:
            if isinstance(step, dict):
                status = step.get('status')
                subtasks = step.get('subtasks')
            else:
                status = getattr(step, 'status', None)
                subtasks = getattr(step, 'subtasks', None)
            if str(status or '').strip().lower() in ACTIVE_TASK_STATUSES:
                return True
            if self._steps_have_active_status(subtasks or []):
                return True
        return False

    async def _intercept_text_tool_call_handoff(self, action: MessageAction) -> bool:
        content = str(getattr(action, 'content', '') or '')
        if not _looks_like_text_tool_call_handoff(content):
            return False

        guidance = (
            'Protocol error: provider-specific text tool-call markup was returned '
            'instead of a valid Grinta tool action.'
        )
        await self._reject_agent_message_handoff(
            action,
            guidance,
            source='EventRouterService._intercept_text_tool_call_handoff',
            error_id='TEXT_TOOL_CALL_FORMAT_INCOMPLETE',
        )
        return True

    async def _intercept_protocol_message_handoff(self, action: MessageAction) -> bool:
        guidance = (
            'Protocol error: assistant message returned during active task execution.'
        )
        await self._reject_agent_message_handoff(
            action,
            guidance,
            source='EventRouterService._intercept_protocol_message_handoff',
            error_id='ASSISTANT_MESSAGE_PROTOCOL_ERROR',
        )
        return True

    async def _reject_agent_message_handoff(
        self,
        action: MessageAction,
        guidance: str,
        *,
        source: str,
        error_id: str,
    ) -> None:
        state = getattr(self._ctrl, 'state', None)
        if state is not None and hasattr(state, 'set_planning_directive'):
            state.set_planning_directive(
                guidance,
                source=source,
            )
        else:
            observation = ErrorObservation(
                content=guidance,
                error_id=error_id,
            )
            attach_observation_cause(
                observation,
                action,
                context=source,
            )
            self._ctrl.event_stream.add_event(observation, EventSource.ENVIRONMENT)
        if self._ctrl.get_agent_state() != AgentState.RUNNING:
            await self._ctrl.set_agent_state_to(AgentState.RUNNING)
        action.suppress_cli = True
        action.wait_for_response = False

    async def _handle_user_message(self, action: MessageAction) -> None:
        """Handle user message: log, create recall, set pending, start agent."""
        log_level = 'info' if _os.getenv('LOG_ALL_EVENTS') in ('true', '1') else 'debug'
        self._ctrl.log(
            log_level,
            str(action),
            extra={'msg_type': 'ACTION', 'event_source': EventSource.USER},
        )
        recall_type = self._recall_type_for_user_message(action)
        recall_action = RecallAction(query=action.content, recall_type=recall_type)
        agent = getattr(self._ctrl, 'agent', None)
        config = getattr(agent, 'config', None)
        mode = normalize_interaction_mode(getattr(config, 'mode', 'agent'))
        if mode in CHAT_MODE_NAMES:
            self._ctrl.state.extra_data.pop('active_run_mode', None)
        else:
            self._ctrl.state.set_extra(
                'active_run_mode',
                mode,
                source='EventRouterService.user_message',
            )

        # Assign stream id before pending so pending always references a stable id.
        self._ctrl.event_stream.add_event(recall_action, EventSource.USER)
        self._set_pending_recall(recall_action, recall_type)
        await self._ensure_running_for_user_message()

    async def _handle_delegate_task_action(self, action: DelegateTaskAction) -> None:
        """Handle delegating a subtask to a worker agent."""
        import asyncio
        import uuid

        from backend.core.config.agent_config import AgentConfig
        from backend.core.constants import (
            DELEGATE_WORKER_TIMEOUT_SECONDS,
            MAX_DELEGATION_DEPTH,
        )
        from backend.orchestration.agent import Agent
        from backend.orchestration.blackboard import Blackboard
        from backend.orchestration.conversation_stats import ConversationStats
        from backend.orchestration.orchestration_config import OrchestrationConfig
        from backend.orchestration.session_orchestrator import SessionOrchestrator
        from backend.utils.async_utils import run_or_schedule

        # Check delegation depth limit
        current_depth = getattr(action, 'depth', 0)
        if current_depth >= MAX_DELEGATION_DEPTH:
            self._ctrl.log(
                'warning',
                f'Delegation depth limit reached ({MAX_DELEGATION_DEPTH}). '
                f'Cannot delegate further (current depth: {current_depth}).',
            )
            obs = DelegateTaskObservation(
                success=False,
                content='',
                error_message=(
                    f'Delegation depth limit exceeded (max {MAX_DELEGATION_DEPTH}). '
                    f'Current depth: {current_depth}. Complete the task directly instead.'
                ),
            )
            attach_observation_cause(
                obs,
                action,
                context='event_router.delegate_task.depth_limit',
            )
            obs.tool_call_metadata = action.tool_call_metadata
            self._ctrl.event_stream.add_event(obs, EventSource.ENVIRONMENT)
            return

        blackboard = Blackboard()

        # Background task so we don't block the routing loop
        async def _execute_single_worker(
            task_description: str,
            files: list,
            shared_blackboard: Blackboard | None = None,
            *,
            worker_label: str = 'Worker',
            worker_order: int = 1,
            batch_id: int | None = None,
            depth: int = 0,
            timeout_seconds: float = DELEGATE_WORKER_TIMEOUT_SECONDS,
        ) -> tuple[bool, str, str]:
            """Run one worker agent and return (success, content, error_message)."""
            worker_id = f'pending_worker_{worker_order}'
            worker_marked_terminal = False
            worker_controller = None
            worker_stream = None

            def _emit_worker_progress(status: str, detail: str) -> None:
                progress = _build_delegate_progress_observation(
                    worker_id=worker_id,
                    worker_label=worker_label,
                    task_description=task_description,
                    status=status,
                    detail=detail,
                    order=worker_order,
                    batch_id=batch_id,
                )
                self._ctrl.event_stream.add_event(progress, EventSource.ENVIRONMENT)

            try:
                # Get the base agent config but clear history
                parent_config = self._ctrl.config
                worker_id = f'{parent_config.sid}_sub_{uuid.uuid4().hex[:8]}'

                file_store = parent_config.file_store or getattr(
                    self._ctrl.event_stream, 'file_store', None
                )
                if file_store is None:
                    raise RuntimeError(
                        'No file_store available for worker event stream'
                    )

                user_id = getattr(parent_config, 'user_id', None)

                agent_configs = getattr(parent_config, 'agent_configs', None) or {}
                worker_agent_config = getattr(self._ctrl.agent, 'config', None)
                if worker_agent_config is None:
                    worker_agent_config = agent_configs.get('Orchestrator')
                if worker_agent_config is None:
                    worker_agent_config = AgentConfig(name='Orchestrator')

                # Ensure config is a proper AgentConfig instance.
                if not isinstance(worker_agent_config, AgentConfig):
                    try:
                        worker_agent_config = AgentConfig.model_validate(
                            worker_agent_config
                        )
                    except Exception as exc:
                        raise RuntimeError(
                            f'Invalid worker agent config type: {type(worker_agent_config)}'
                        ) from exc

                # Prefer a dedicated LLM config if provided in agent_to_llm_config.
                agent_to_llm_config = (
                    getattr(parent_config, 'agent_to_llm_config', None) or {}
                )
                llm_cfg = agent_to_llm_config.get(worker_agent_config.name)
                if llm_cfg is not None:
                    worker_agent_config = worker_agent_config.model_copy(
                        deep=True, update={'llm_config': llm_cfg}
                    )

                # Delegated workers need inline delivery so finish/reject state
                # transitions land before the parent inspects worker state.
                worker_stream = EventStream(
                    worker_id,
                    file_store=file_store,
                    user_id=user_id,
                    worker_count=0,
                )

                def _forward_worker_event(event: Action | Observation) -> None:
                    nonlocal worker_marked_terminal
                    if isinstance(event, Action) and event.source != EventSource.AGENT:
                        return
                    summary = _summarize_delegate_worker_event(event)
                    if summary is None:
                        return
                    status, detail = summary
                    if status in {'done', 'failed'}:
                        worker_marked_terminal = True
                    _emit_worker_progress(status, detail)

                worker_stream.subscribe(
                    EventStreamSubscriber.MAIN,
                    _forward_worker_event,  # type: ignore
                    f'delegate_progress_{worker_id}',
                )
                _emit_worker_progress('starting', 'Starting delegated worker')

                self._ctrl.log(
                    'info',
                    f'Spawning worker agent {worker_id} for task: {task_description[:50]}...',
                )

                # Send the initial user message/directive to the worker.
                # Inject parent's working memory, notes, and task plan so the
                # sub-agent has full context without needing to rediscover it.
                worker_depth = depth + 1
                parent_context_lines: list[str] = [
                    f'You are a worker agent (depth {worker_depth}/{MAX_DELEGATION_DEPTH}) delegated the following task:\n\n{task_description}\n\nFocus ONLY on this task. Once completed, finish.\n\n'
                    f'DELEGATION LIMIT: You can delegate sub-tasks up to depth {MAX_DELEGATION_DEPTH}. '
                    f'Your current depth is {worker_depth}. '
                    f'If you need to delegate further, you can go up to depth {MAX_DELEGATION_DEPTH}.'
                ]
                if shared_blackboard is not None:
                    parent_context_lines.append(
                        '\n\nSHARED BLACKBOARD: Use the blackboard tool (get/set/keys) to coordinate with other parallel workers. Publish contracts, status, or shared data there.'
                    )

                # --- inherit parent working memory ---
                try:
                    from backend.engine.tools.working_memory import (
                        get_full_working_memory,
                    )

                    wm = get_full_working_memory()
                    if wm:
                        parent_context_lines.append(
                            f'\n\nPARENT WORKING MEMORY (read-only context):\n{wm}'
                        )
                except Exception as e:
                    self._ctrl.log(
                        'warning', f'Failed to inherit parent working memory: {e}'
                    )

                # --- inherit parent notes ---
                try:
                    from backend.engine.tools.note import (
                        _load_notes,
                    )

                    notes = _load_notes()
                    if notes:
                        notes_text = '\n'.join(
                            f'  {k}: {v}' for k, v in list(notes.items())[:20]
                        )
                        parent_context_lines.append(
                            f'\n\nPARENT NOTES (key-value context):\n{notes_text}'
                        )
                except Exception as e:
                    self._ctrl.log('warning', f'Failed to inherit parent notes: {e}')

                # --- inherit parent task plan ---
                try:
                    from backend.core.task_status import (
                        TASK_STATUS_PLAN_ICONS,
                        TASK_STATUS_TODO,
                    )
                    from backend.engine.tools.task_tracker import (
                        TaskTracker,
                    )

                    tasks = TaskTracker().load_from_file()
                    if tasks:
                        task_lines = ['PARENT TASK PLAN (for context):']
                        for t in tasks:
                            status = str(t.get('status') or TASK_STATUS_TODO)
                            status_icon = TASK_STATUS_PLAN_ICONS.get(status, '-')
                            task_lines.append(
                                f'  [{status_icon}] {t.get("id", "?")} — {t.get("description", "")}'
                                f' ({status})'
                            )
                        parent_context_lines.append('\n\n' + '\n'.join(task_lines))
                except Exception as e:
                    self._ctrl.log(
                        'warning', f'Failed to inherit parent task plan: {e}'
                    )

                # We need to reuse the same file store/workspace as the parent
                llm_registry = getattr(self._ctrl.agent, 'llm_registry', None)
                if llm_registry is None:
                    raise RuntimeError('Parent agent does not expose llm_registry')

                try:
                    agent_cls = Agent.get_cls(worker_agent_config.name)
                except Exception as exc:
                    raise RuntimeError(
                        f'Worker agent class not registered: {worker_agent_config.name}'
                    ) from exc

                worker_agent = agent_cls(
                    config=worker_agent_config, llm_registry=llm_registry
                )
                if shared_blackboard is not None:
                    worker_agent.blackboard = shared_blackboard  # type: ignore[attr-defined]
                    worker_agent.tools = worker_agent.planner.build_toolset()  # type: ignore[attr-defined]

                conversation_stats = ConversationStats(
                    file_store=file_store,
                    conversation_id=worker_id,
                    user_id=user_id,
                )

                worker_config = OrchestrationConfig(
                    sid=worker_id,
                    event_stream=worker_stream,
                    agent=worker_agent,
                    conversation_stats=conversation_stats,
                    iteration_delta=parent_config.iteration_delta,
                    budget_per_task_delta=parent_config.budget_per_task_delta,
                    user_id=user_id,
                    file_store=file_store,  # Share workspace!
                    headless_mode=True,  # No UI for sub-agent
                    agent_to_llm_config=agent_to_llm_config,
                    agent_configs=agent_configs,
                    security_analyzer=parent_config.security_analyzer,
                    blackboard=shared_blackboard,
                    pending_action_timeout=parent_config.pending_action_timeout,
                    enable_parallel_tool_scheduling=bool(
                        getattr(parent_config, 'enable_parallel_tool_scheduling', False)
                    ),
                )

                worker_controller = SessionOrchestrator(worker_config)

                # ── Wire runtime bridge for the worker ──
                #
                # The worker controller has its own EventStream but no
                # Runtime subscribed.  Without a runtime, tool actions
                # (FileWrite, CmdRun, …) are emitted but nobody executes
                # them — no observation is ever produced, the pending
                # action never clears, and the worker hangs.
                #
                # We bridge the gap by subscribing a lightweight callback
                # to the worker stream.  When a runnable Action arrives,
                # the bridge delegates to the parent runtime's executor
                # and emits the resulting Observation back on the worker
                # stream.
                parent_runtime = getattr(self._ctrl, 'runtime', None)
                if parent_runtime is not None:
                    from backend.utils.async_utils import run_or_schedule

                    _worker_stream_ref = worker_stream  # capture for closure

                    async def _ensure_worker_pipeline_allowed(event: Action) -> bool:
                        """Ensure manually bridged worker actions pass middleware."""
                        mapping = getattr(
                            worker_controller,
                            '_action_contexts_by_event_id',
                            {},
                        )
                        if getattr(event, 'id', None) in mapping:
                            return True
                        pipeline = getattr(
                            worker_controller, 'operation_pipeline', None
                        )
                        if pipeline is None:
                            pipeline = getattr(worker_controller, 'tool_pipeline', None)
                        if pipeline is None:
                            return True
                        ctx = pipeline.create_context(event, worker_controller.state)
                        ctx.action_id = event.id
                        if hasattr(worker_controller, '_action_contexts_by_event_id'):
                            worker_controller._action_contexts_by_event_id[event.id] = (
                                ctx
                            )
                        await pipeline.run_execute(ctx)
                        if getattr(ctx, 'blocked', False):
                            worker_controller.handle_blocked_invocation(event, ctx)
                            return False
                        return True

                    def _worker_runtime_bridge(event):
                        if not isinstance(event, Action):
                            return
                        if not getattr(event, 'runnable', False):
                            return

                        async def _execute():
                            try:
                                if not await _ensure_worker_pipeline_allowed(event):
                                    return
                                parent_runtime._set_action_timeout(event)
                                observation = await parent_runtime._execute_action(
                                    event
                                )
                            except Exception as exc:
                                self._ctrl.log(
                                    'error',
                                    f'Worker runtime bridge execution failed: {type(exc).__name__}: {exc}',
                                    extra={'msg_type': 'WORKER_RUNTIME_ERROR'},
                                )
                                observation = ErrorObservation(
                                    content=(
                                        f'Worker action error: '
                                        f'{type(exc).__name__}: {exc}'
                                    )
                                )
                            process_observation = getattr(
                                parent_runtime, '_process_observation', None
                            )
                            should_emit = True
                            if callable(process_observation):
                                should_emit = bool(
                                    process_observation(observation, event)
                                )
                            else:
                                attach_observation_cause(
                                    observation,
                                    event,
                                    context='worker_runtime_bridge',
                                )
                                observation.tool_call_metadata = (
                                    event.tool_call_metadata
                                )
                            if not should_emit:
                                return
                            source = event.source or EventSource.AGENT
                            _worker_stream_ref.add_event(observation, source)

                        run_or_schedule(_execute())

                    worker_stream.subscribe(
                        EventStreamSubscriber.RUNTIME,
                        _worker_runtime_bridge,
                        worker_stream.sid,
                    )

                # Disable auto-stepping: we drive the worker loop manually
                # via _step_inner().  Without this, event callbacks
                # (on_event → should_step → step()) would schedule
                # concurrent step tasks that interfere with our loop.
                worker_controller.step = lambda: None  # type: ignore[assignment]

                # Bootstrap the worker: send the initial user message and
                # set state to RUNNING.  Both add_event() and
                # set_agent_state_to() trigger on_event callbacks that
                # schedule background tasks (via run_or_schedule).  We must
                # drain those tasks so that state.history contains the
                # initial message before the first _step_inner() call, and
                # so the AgentStateChangedObservation is processed.
                from backend.utils.async_utils import _background_tasks

                worker_task_baseline = set(_background_tasks)

                async def _drain_new_worker_tasks(
                    baseline: set[asyncio.Task],
                    *,
                    max_rounds: int,
                ) -> None:
                    for _drain in range(max_rounds):
                        pending = {
                            t
                            for t in _background_tasks
                            if t not in baseline and not t.done()
                        }
                        if not pending:
                            break
                        await asyncio.gather(*pending, return_exceptions=True)

                init_msg = MessageAction(content='\n'.join(parent_context_lines))
                worker_controller.event_stream.add_event(init_msg, EventSource.USER)
                await worker_controller.set_agent_state_to(AgentState.RUNNING)

                await _drain_new_worker_tasks(worker_task_baseline, max_rounds=50)

                # Drive the worker step loop directly.
                #
                # We cannot use the public step() API because it schedules
                # work via call_soon_threadsafe / run_or_schedule, which
                # creates background asyncio.Tasks.  In the server path
                # those tasks are consumed by the event-loop naturally, but
                # here we are the *only* consumer — so those tasks would
                # never run and the state transition (RUNNING → FINISHED)
                # would never land.
                #
                # Instead we call _step_inner() directly (we're already
                # async) and after each step we drain every background task
                # that event-stream callbacks spawned via run_or_schedule().

                async def _run_worker_steps():
                    """Run worker steps with timeout enforcement."""
                    import time

                    start_time = time.monotonic()
                    max_steps = max(
                        10, int(getattr(parent_config, 'iteration_delta', 50) or 50)
                    )
                    for step_num in range(max_steps):
                        # Check timeout
                        elapsed = time.monotonic() - start_time
                        if elapsed >= timeout_seconds:
                            self._ctrl.log(
                                'warning',
                                f'Worker {worker_id} timed out after {elapsed:.0f}s '
                                f'(limit: {timeout_seconds}s)',
                            )
                            _emit_worker_progress(
                                'failed',
                                f'Worker timed out after {elapsed:.0f}s (limit: {timeout_seconds}s)',
                            )
                            return False, '', f'Worker timed out after {elapsed:.0f}s'

                        if worker_controller.get_agent_state() not in (
                            AgentState.RUNNING,
                            AgentState.AWAITING_USER_INPUT,
                            AgentState.PAUSED,
                        ):
                            break

                        # Snapshot tasks before step so we can identify new ones.
                        pre_tasks = set(_background_tasks)

                        await worker_controller._step_inner()

                        # Drain all background tasks that were spawned during the
                        # step (typically _on_event coroutines from event-stream
                        # inline dispatch → on_event → run_or_schedule).  Keep
                        # draining until no new tasks appear, because each task
                        # may itself schedule further tasks (e.g. the state-change
                        # observation triggers another on_event cycle).
                        await _drain_new_worker_tasks(pre_tasks, max_rounds=50)

                    # Final settle: give any remaining scheduled callbacks a
                    # chance to complete.
                    await _drain_new_worker_tasks(worker_task_baseline, max_rounds=20)
                    return True, '', ''

                timed_out = False
                try:
                    steps_success, _, timeout_msg = await asyncio.wait_for(
                        _run_worker_steps(),
                        timeout=timeout_seconds + 10,  # Small buffer
                    )
                except asyncio.TimeoutError:
                    timed_out = True
                    self._ctrl.log(
                        'warning',
                        f'Worker {worker_id} timed out (limit: {timeout_seconds}s)',
                    )
                    _emit_worker_progress(
                        'failed',
                        f'Worker timed out (limit: {timeout_seconds}s)',
                    )

                if timed_out:
                    return False, '', f'Worker timed out after {timeout_seconds}s'

                final_state = worker_controller.get_agent_state()
                self._ctrl.log(
                    'info',
                    f'Worker agent {worker_id} finished with state {final_state.value}',
                )

                # Check for output data
                outputs = worker_controller.state.outputs
                extracted_outputs = None
                if outputs:
                    extracted_outputs = outputs

                success = final_state == AgentState.FINISHED
                if (
                    not success
                    and extracted_outputs is not None
                    and final_state
                    in (
                        AgentState.RUNNING,
                        AgentState.AWAITING_USER_INPUT,
                        AgentState.PAUSED,
                    )
                ):
                    success = True
                    final_state = AgentState.FINISHED

                content = (
                    str(extracted_outputs)
                    if extracted_outputs
                    else f'Worker completed with status: {final_state.value}'
                )
                error_message = (
                    ''
                    if success
                    else f'Agent did not finish gracefully (State: {final_state.value}).'
                )

                if success and not worker_marked_terminal:
                    _emit_worker_progress('done', 'Completed')
                elif not success and not worker_marked_terminal:
                    _emit_worker_progress('failed', error_message)
                return success, content, error_message

            except Exception as e:
                self._ctrl.log('error', f'Worker execution failed: {e}')
                _emit_worker_progress('failed', f'Worker execution crashed: {e}')
                return False, '', f'Worker execution crashed: {e}'
            finally:
                try:
                    if worker_controller is not None:
                        await worker_controller.close(set_stop_state=False)
                    elif worker_stream is not None:
                        worker_stream.close()
                except Exception:
                    pass

        async def _run_subagent():
            """Dispatch single or parallel workers and post the final observation."""
            import asyncio

            parallel_tasks = getattr(action, 'parallel_tasks', [])
            worker_depth = current_depth + 1
            if parallel_tasks:
                # Parallel mode — run all workers concurrently
                self._ctrl.log(
                    'info',
                    f'Running {len(parallel_tasks)} sub-agents in parallel (depth {worker_depth})',
                )
                results = await asyncio.gather(
                    *[
                        _execute_single_worker(
                            t.get('task_description', ''),
                            t.get('files', []),
                            blackboard,
                            worker_label=f'Worker {i + 1}',
                            worker_order=i + 1,
                            batch_id=action.id if action.id > 0 else None,
                            depth=worker_depth,
                        )
                        for i, t in enumerate(parallel_tasks)
                    ],
                    return_exceptions=True,
                )
                normalized_results: list[tuple[bool, str, str]] = []
                for result in results:
                    if isinstance(result, BaseException):
                        normalized_results.append(
                            (
                                False,
                                '',
                                f'Worker execution crashed: {type(result).__name__}: {result}',
                            )
                        )
                    else:
                        normalized_results.append(result)
                all_success = all(r[0] for r in normalized_results)
                parts = []
                for i, (s, c, e) in enumerate(normalized_results):
                    label = parallel_tasks[i].get('task_description', f'Task {i + 1}')[
                        :40
                    ]
                    status = 'OK' if s else 'FAILED'
                    parts.append(f'[{status}] {label}\n{c or e}')
                combined_content = '\n\n'.join(parts)
                if blackboard is not None and blackboard.snapshot():
                    combined_content += (
                        '\n\n[SHARED BLACKBOARD SNAPSHOT]\n'
                        + '\n'.join(
                            f'  {k}: {v}' for k, v in blackboard.snapshot().items()
                        )
                    )
                obs = DelegateTaskObservation(
                    success=all_success,
                    content=combined_content,
                    error_message=''
                    if all_success
                    else 'One or more parallel workers failed.',
                )
            else:
                # Single worker mode
                self._ctrl.log(
                    'info',
                    f'Running sub-agent (depth {worker_depth}): {action.task_description[:50]}...',
                )
                success, content, error_message = await _execute_single_worker(
                    action.task_description,
                    getattr(action, 'files', []),
                    blackboard,
                    worker_label='Worker',
                    worker_order=1,
                    batch_id=action.id if action.id > 0 else None,
                    depth=worker_depth,
                )
                if blackboard is not None and blackboard.snapshot():
                    content += '\n\n[SHARED BLACKBOARD SNAPSHOT]\n' + '\n'.join(
                        f'  {k}: {v}' for k, v in blackboard.snapshot().items()
                    )
                obs = DelegateTaskObservation(
                    success=success,
                    content=content,
                    error_message=error_message,
                )

            attach_observation_cause(
                obs,
                action,
                context='event_router.delegate_task',
            )
            obs.tool_call_metadata = action.tool_call_metadata
            self._ctrl.event_stream.add_event(obs, EventSource.ENVIRONMENT)

        # Handle background vs foreground execution
        run_in_background = getattr(action, 'run_in_background', False)

        if run_in_background:
            # Background mode: Schedule worker and return immediately.
            # Parent agent continues working while worker runs.
            # Parent can monitor progress via shared_task_board.
            self._ctrl.log(
                'info',
                'Spawning background worker(s). Parent agent continues immediately.',
                extra={'msg_type': 'DELEGATE_BACKGROUND'},
            )
            # Don't register as pending - parent should continue immediately
            run_or_schedule(_run_subagent())
        else:
            # Foreground mode: Register as pending so parent blocks until worker completes.
            pending_service = getattr(
                getattr(self._ctrl, 'services', None), 'pending_action', None
            )
            if pending_service is not None:
                pending_service.set(action)
            else:
                self._ctrl._pending_action = action

            # Run the subagent without blocking the routing loop
            run_or_schedule(_run_subagent())

    async def _handle_meta_cognition_action(self, action: Action) -> None:
        """Handle meta-cognition actions (clarification, proposal, uncertainty, escalation).

        In FULL autonomy mode, the agent continues without pausing.
        In BALANCED or CONSERVATIVE mode, the agent pauses and waits for user input.
        """
        from backend.orchestration.autonomy import AutonomyLevel

        autonomy_ctrl = getattr(self._ctrl, 'autonomy_controller', None)
        autonomy_level = (
            getattr(autonomy_ctrl, 'autonomy_level', AutonomyLevel.BALANCED.value)
            if autonomy_ctrl
            else AutonomyLevel.BALANCED.value
        )

        agent = getattr(self._ctrl, 'agent', None)
        config = getattr(agent, 'config', None)
        mode = normalize_interaction_mode(getattr(config, 'mode', 'agent'))
        should_pause = mode == 'plan' or autonomy_level != AutonomyLevel.FULL.value

        if should_pause:
            self._ctrl.log(
                'info',
                'Meta-cognition action requires user input, pausing agent.',
                extra={'action_type': type(action).__name__},
            )
            await self._ctrl.set_agent_state_to(AgentState.AWAITING_USER_INPUT)

    # ── observation dispatch ──────────────────────────────────────────

    async def _handle_observation(self, observation: Observation) -> None:
        """Delegate observation handling to the observation service."""
        await self._ctrl.observation_service.handle_observation(observation)
