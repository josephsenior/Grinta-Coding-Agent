"""Event routing service for SessionOrchestrator.

Routes incoming events from the EventStream to appropriate handlers. Centralizes
all event dispatch logic that was previously inline in SessionOrchestrator._on_event.
"""

from __future__ import annotations

import asyncio
import os as _os
from typing import TYPE_CHECKING

from backend.core.schemas import AgentState
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
    SignalProgressAction,
    TaskTrackingAction,
)
from backend.ledger.action.agent import (
    ClarificationRequestAction,
    DelegateTaskAction,
    EscalateToHumanAction,
    ProposalAction,
    RecallAction,
    UncertaintyAction,
)
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


_CHECKPOINT_INTERMEDIATE_TOOLS = frozenset({'checkpoint', 'revert_to_checkpoint'})
_DELEGATE_PROGRESS_STATUS = 'delegate_progress'


def _truncate_delegate_progress(text: str, limit: int = 120) -> str:
    collapsed = ' '.join((text or '').split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(limit - 1, 0)].rstrip() + '…'


def _summarize_delegate_worker_event(
    event: Action | Observation,
) -> tuple[str, str] | None:
    """Return a compact worker-progress summary for parent-side swarm UI."""
    if isinstance(event, FileReadAction):
        return 'running', f'Viewed {event.path}'

    if isinstance(event, FileWriteAction):
        return 'running', f'Created {event.path}'

    if isinstance(event, FileEditAction):
        command = getattr(event, 'command', '') or ''
        if command == 'create_file':
            return 'running', f'Created {event.path}'
        if command == 'read_file':
            return 'running', f'Read {event.path}'
        return 'running', f'Edited {event.path}'

    if isinstance(event, CmdRunAction):
        label = getattr(event, 'display_label', '') or getattr(event, 'command', '')
        label = _truncate_delegate_progress(label, limit=96)
        return 'running', f'Ran {label}' if label else 'Ran command'

    if isinstance(event, MCPAction):
        tool_name = getattr(event, 'name', '') or 'MCP tool'
        return 'running', f'Called {tool_name}'

    if isinstance(event, SignalProgressAction):
        note = _truncate_delegate_progress(getattr(event, 'progress_note', '') or '')
        return 'running', note or 'Reported progress'

    if isinstance(event, PlaybookFinishAction):
        summary = _truncate_delegate_progress(
            (event.message or '').splitlines()[0], 140
        )
        return 'done', summary or 'Completed'

    if isinstance(event, AgentRejectAction):
        reason = _truncate_delegate_progress(
            str(event.outputs.get('reason', '') or ''), 140
        )
        return 'failed', reason or 'Rejected delegated task'

    if isinstance(event, ErrorObservation):
        first_line = _truncate_delegate_progress(
            (event.content or '').splitlines()[0], 140
        )
        return 'failed', first_line or 'Worker error'

    if isinstance(event, AgentStateChangedObservation):
        state = str(getattr(event, 'agent_state', '') or '').lower()
        if state == AgentState.ERROR.value:
            return 'failed', 'Worker entered error state'
        if state == AgentState.FINISHED.value:
            return 'done', 'Completed'

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
            try:
                target_state = AgentState(action.agent_state)
            except ValueError:
                self._ctrl.log(
                    'warning',
                    "Received unknown agent state '%s', ignoring.",
                    extra={'agent_state': action.agent_state},
                )
            else:
                # Guard: discard a stale startup AWAITING_USER_INPUT signal that
                # was queued on the ENVIRONMENT background queue before the user
                # message arrived.  If the agent is already RUNNING (meaning a
                # user message was processed inline), an ENVIRONMENT-sourced
                # AWAITING_USER_INPUT would race to override the active RUNNING
                # state and permanently freeze the agent loop.
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
        elif isinstance(action, MessageAction):
            await self._handle_message_action(action)
        elif isinstance(action, PlaybookFinishAction):
            await self._handle_finish_action(action)
        elif isinstance(action, AgentRejectAction):
            await self._handle_reject_action(action)
        elif isinstance(action, TaskTrackingAction):
            await self._handle_task_tracking_action(action)
        elif isinstance(action, DelegateTaskAction):
            await self._handle_delegate_task_action(action)
        elif isinstance(
            action,
            (
                ClarificationRequestAction,
                ProposalAction,
                UncertaintyAction,
                EscalateToHumanAction,
            ),
        ):
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
                if await self._intercept_incomplete_checkpoint_handoff(action):
                    return
                await self._ctrl.set_agent_state_to(AgentState.AWAITING_USER_INPUT)

    async def _intercept_incomplete_checkpoint_handoff(
        self, action: MessageAction
    ) -> bool:
        recent_tool_result = self._recent_checkpoint_tool_result()
        if recent_tool_result is None:
            return False

        tool_name = str(recent_tool_result.get('tool') or 'checkpoint')
        next_best_action = str(recent_tool_result.get('next_best_action') or '').strip()
        guidance_lines = [
            f'{tool_name} is an intermediate control tool, not a terminal reply.',
        ]
        if next_best_action:
            guidance_lines.append(f'Latest tool guidance: {next_best_action}')
        guidance_lines.extend(
            [
                'Continue in the same turn: execute the next step, or if a plan step changed state call task_tracker update first.',
                'If the overall task is complete, call finish with a short user-facing summary and concrete next_steps.',
                'Only wait for user input when you genuinely need clarification or confirmation.',
            ]
        )

        state = getattr(self._ctrl, 'state', None)
        if state is not None and hasattr(state, 'set_planning_directive'):
            state.set_planning_directive(
                '\n'.join(guidance_lines),
                source='EventRouterService._intercept_incomplete_checkpoint_handoff',
            )
        else:
            observation = ErrorObservation(
                content='\n'.join(guidance_lines),
                error_id='CHECKPOINT_FLOW_INCOMPLETE',
            )
            attach_observation_cause(
                observation,
                action,
                context='EventRouterService._intercept_incomplete_checkpoint_handoff',
            )
            self._ctrl.event_stream.add_event(observation, EventSource.ENVIRONMENT)
        if self._ctrl.get_agent_state() != AgentState.RUNNING:
            await self._ctrl.set_agent_state_to(AgentState.RUNNING)
        # Mark the MessageAction as suppressed in the CLI — it's an internal
        # mid-task message that should not appear in the user-facing transcript.
        action.suppress_cli = True
        return True

    def _recent_checkpoint_tool_result(self) -> dict[str, object] | None:
        history = getattr(self._ctrl.state, 'history', None) or []
        if not history:
            return None

        prior_events = history[:-1] if history and history[-1] is not None else history
        for event in reversed(prior_events):
            if isinstance(event, MessageAction) and event.source == EventSource.USER:
                break
            tool_result = getattr(event, 'tool_result', None)
            if not isinstance(tool_result, dict):
                continue
            tool_name = str(tool_result.get('tool') or '').strip()
            if tool_name in _CHECKPOINT_INTERMEDIATE_TOOLS:
                return tool_result
        return None

    async def _handle_user_message(self, action: MessageAction) -> None:
        """Handle user message: log, create recall, set pending, start agent."""
        log_level = 'info' if _os.getenv('LOG_ALL_EVENTS') in ('true', '1') else 'debug'
        self._ctrl.log(
            log_level,
            str(action),
            extra={'msg_type': 'ACTION', 'event_source': EventSource.USER},
        )
        first_user_message = next(
            (
                e
                for e in self._ctrl.event_stream.search_events(
                    start_id=self._ctrl.state.start_id
                )
                if isinstance(e, MessageAction) and e.source == EventSource.USER
            ),
            None,
        )
        is_first = action.id == first_user_message.id if first_user_message else False
        recall_type = RecallType.WORKSPACE_CONTEXT if is_first else RecallType.KNOWLEDGE
        recall_action = RecallAction(query=action.content, recall_type=recall_type)

        # Assign stream id before pending so pending always references a stable id.
        self._ctrl.event_stream.add_event(recall_action, EventSource.USER)

        # Only block the agent loop on WORKSPACE_CONTEXT recall (first message).
        # KNOWLEDGE recalls (follow-up messages) run in the background while the
        # agent steps — can_step() already returns True for them. Setting them as
        # pending causes an ID mismatch when the next real action gets a new ID
        # before the RecallObservation arrives.
        pending_service = getattr(self._ctrl, 'pending_action_service', None)
        if recall_type == RecallType.WORKSPACE_CONTEXT:
            if pending_service is not None:
                pending_service.set(recall_action)
            else:
                action_service = getattr(self._ctrl, 'action_service', None)
                if action_service is not None:
                    action_service.set_pending_action(recall_action)
        else:
            # KNOWLEDGE recall (second+ messages): the previous turn's MessageAction
            # is still pending (it was set in _finalize_action but never cleared by
            # an observation because AGENT_LEVEL_ACTIONS skip runtime execution).
            # Clear it now so can_step() returns True for this new turn.
            if pending_service is not None:
                pending_service.set(None)

        if self._ctrl.get_agent_state() != AgentState.RUNNING:
            await self._ctrl.set_agent_state_to(AgentState.RUNNING)

    async def _handle_delegate_task_action(self, action: DelegateTaskAction) -> None:
        """Handle delegating a subtask to a worker agent."""
        import uuid

        from backend.core.config.agent_config import AgentConfig
        from backend.orchestration.agent import Agent
        from backend.orchestration.blackboard import Blackboard
        from backend.orchestration.conversation_stats import ConversationStats
        from backend.orchestration.orchestration_config import OrchestrationConfig
        from backend.orchestration.session_orchestrator import SessionOrchestrator
        from backend.utils.async_utils import run_or_schedule

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
        ) -> tuple[bool, str, str]:
            """Run one worker agent and return (success, content, error_message)."""
            worker_id = f'pending_worker_{worker_order}'
            worker_marked_terminal = False

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
                parent_context_lines: list[str] = [
                    f'You are a worker agent delegated the following task:\n\n{task_description}\n\nFocus ONLY on this task. Once completed, finish.'
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
                    confirmation_mode=False,
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

                    def _worker_runtime_bridge(event):
                        if not isinstance(event, Action):
                            return
                        if not getattr(event, 'runnable', False):
                            return

                        async def _execute():
                            try:
                                parent_runtime._set_action_timeout(event)
                                observation = await parent_runtime._execute_action(
                                    event
                                )
                            except Exception as exc:
                                observation = ErrorObservation(
                                    content=(
                                        f'Worker action error: '
                                        f'{type(exc).__name__}: {exc}'
                                    )
                                )
                            attach_observation_cause(
                                observation, event, context='worker_runtime_bridge'
                            )
                            observation.tool_call_metadata = event.tool_call_metadata
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

                init_msg = MessageAction(content='\n'.join(parent_context_lines))
                worker_controller.event_stream.add_event(init_msg, EventSource.USER)
                await worker_controller.set_agent_state_to(AgentState.RUNNING)

                # Drain all background tasks from bootstrap events.
                for _drain in range(50):
                    pending = {t for t in _background_tasks if not t.done()}
                    if not pending:
                        break
                    await asyncio.gather(*pending, return_exceptions=True)

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

                max_steps = max(
                    10, int(getattr(parent_config, 'iteration_delta', 50) or 50)
                )
                for _ in range(max_steps):
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
                    for _drain in range(50):
                        new_tasks = _background_tasks - pre_tasks
                        pending = {t for t in new_tasks if not t.done()}
                        if not pending:
                            break
                        await asyncio.gather(*pending, return_exceptions=True)

                # Final settle: give any remaining scheduled callbacks a
                # chance to complete.
                for _ in range(20):
                    pending = {t for t in _background_tasks if not t.done()}
                    if not pending:
                        break
                    await asyncio.gather(*pending, return_exceptions=True)

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

                # Cleanup the worker after capturing final state and outputs.
                await worker_controller.close(set_stop_state=False)

                if success and not worker_marked_terminal:
                    _emit_worker_progress('done', 'Completed')
                elif not success and not worker_marked_terminal:
                    _emit_worker_progress('failed', error_message)
                return success, content, error_message

            except Exception as e:
                self._ctrl.log('error', f'Worker execution failed: {e}')
                _emit_worker_progress('failed', f'Worker execution crashed: {e}')
                return False, '', f'Worker execution crashed: {e}'

        async def _run_subagent():
            """Dispatch single or parallel workers and post the final observation."""
            import asyncio

            parallel_tasks = getattr(action, 'parallel_tasks', [])
            if parallel_tasks:
                # Parallel mode — run all workers concurrently
                self._ctrl.log(
                    'info',
                    f'Running {len(parallel_tasks)} sub-agents in parallel',
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
                        )
                        for i, t in enumerate(parallel_tasks)
                    ],
                    return_exceptions=False,
                )
                all_success = all(r[0] for r in results)
                parts = []
                for i, (s, c, e) in enumerate(results):
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
                success, content, error_message = await _execute_single_worker(
                    action.task_description,
                    getattr(action, 'files', []),
                    blackboard,
                    worker_label='Worker',
                    worker_order=1,
                    batch_id=action.id if action.id > 0 else None,
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

            # Final delegate result: omit cause when background (early obs already cleared pending).
            attach_observation_cause(
                obs,
                None if getattr(action, 'run_in_background', False) else action,
                context='event_router.delegate_task',
            )
            obs.tool_call_metadata = action.tool_call_metadata
            self._ctrl.event_stream.add_event(obs, EventSource.ENVIRONMENT)

        if getattr(action, 'run_in_background', False):
            early_obs = DelegateTaskObservation(
                success=True,
                content='Worker(s) started in background. Use the blackboard to coordinate.',
                error_message='',
            )
            attach_observation_cause(
                early_obs, action, context='event_router.delegate_task_early'
            )
            early_obs.tool_call_metadata = action.tool_call_metadata
            self._ctrl.event_stream.add_event(early_obs, EventSource.ENVIRONMENT)
        else:
            # Foreground delegation: register the action as pending so the
            # parent agent blocks (can_step → False) until _run_subagent()
            # emits a DelegateTaskObservation with cause=action.id that
            # clears the pending slot.  Without this, _step_inner() sees no
            # pending action and immediately calls the LLM again — before
            # workers have finished — producing a hallucinated response.
            pending_service = getattr(
                getattr(self._ctrl, 'services', None), 'pending_action', None
            )
            if pending_service is not None:
                pending_service.set(action)
            else:
                self._ctrl._pending_action = action

        # Run the subagent without blocking
        run_or_schedule(_run_subagent())

    async def _handle_meta_cognition_action(self, action: Action) -> None:
        """Handle meta-cognition actions (clarification, proposal, uncertainty, escalation).

        In FULL autonomy mode, the agent continues without pausing.
        In BALANCED or SUPERVISED mode, the agent pauses and waits for user input.
        """
        from backend.orchestration.autonomy import AutonomyLevel

        autonomy_ctrl = getattr(self._ctrl, 'autonomy_controller', None)
        autonomy_level = (
            getattr(autonomy_ctrl, 'autonomy_level', AutonomyLevel.BALANCED.value)
            if autonomy_ctrl
            else AutonomyLevel.BALANCED.value
        )

        if autonomy_level != AutonomyLevel.FULL.value:
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
