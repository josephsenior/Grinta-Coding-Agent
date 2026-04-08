"""Event routing service for SessionOrchestrator.

Routes incoming events from the EventStream to appropriate handlers. Centralizes
all event dispatch logic that was previously inline in SessionOrchestrator._on_event.
"""

from __future__ import annotations

import os as _os
import re

from typing import TYPE_CHECKING

from backend.core.schemas import AgentState
from backend.ledger import EventSource, EventStream, RecallType
from backend.ledger.action import (
    Action,
    AgentRejectAction,
    ChangeAgentStateAction,
    MessageAction,
    PlaybookFinishAction,
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
)
from backend.ledger.observation.agent import DelegateTaskObservation
from backend.ledger.observation_cause import attach_observation_cause

if TYPE_CHECKING:
    from backend.ledger.event import Event
    from backend.orchestration.session_orchestrator import SessionOrchestrator


_CHECKPOINT_INTERMEDIATE_TOOLS = frozenset({'checkpoint', 'revert_to_checkpoint'})
_USER_INPUT_HINTS = (
    re.compile(r'\?\s*$'),
    re.compile(r'\b(?:can|could|would|should|do)\s+you\b'),
    re.compile(r'\b(?:please confirm|clarify|let me know|which option|what would you like)\b'),
)
_COMPLETION_HANDOFF_MARKERS = (
    'next step',
    'next steps',
    "if you'd like",
    'if you want',
    'let me know if',
)


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

        content = (action.content or '').strip()
        if self._message_requests_user_input(content):
            return False
        if self._message_provides_completion_handoff(content):
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

    @staticmethod
    def _message_requests_user_input(content: str) -> bool:
        lowered = content.strip().lower()
        if not lowered:
            return False
        return any(pattern.search(lowered) for pattern in _USER_INPUT_HINTS)

    @staticmethod
    def _message_provides_completion_handoff(content: str) -> bool:
        lowered = content.strip().lower()
        return any(marker in lowered for marker in _COMPLETION_HANDOFF_MARKERS)

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
        from backend.orchestration.conversation_stats import ConversationStats
        from backend.orchestration.agent import Agent
        from backend.orchestration.blackboard import Blackboard
        from backend.orchestration.orchestration_config import OrchestrationConfig
        from backend.orchestration.session_orchestrator import SessionOrchestrator
        from backend.utils.async_utils import run_or_schedule

        blackboard = Blackboard()

        # Background task so we don't block the routing loop
        async def _execute_single_worker(
            task_description: str,
            files: list,
            shared_blackboard: Blackboard | None = None,
        ) -> tuple[bool, str, str]:
            """Run one worker agent and return (success, content, error_message)."""
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

                # Setup isolated event stream
                worker_stream = EventStream(
                    worker_id, file_store=file_store, user_id=user_id
                )
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
                )

                worker_controller = SessionOrchestrator(worker_config)

                init_msg = MessageAction(content='\n'.join(parent_context_lines))
                worker_controller.event_stream.add_event(init_msg, EventSource.USER)

                # Ensure the worker starts running
                await worker_controller.set_agent_state_to(AgentState.RUNNING)

                # Emulate the main execution loop for the headless worker.
                # We reuse the controller's own step() logic.
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
                    worker_controller.step()
                    step_task = getattr(worker_controller, '_step_task', None)
                    if step_task is not None:
                        await step_task

                # Cleanup the worker
                await worker_controller.close(set_stop_state=False)

                final_state = worker_controller.get_agent_state()
                self._ctrl.log(
                    'info',
                    f'Worker agent {worker_id} finished with state {final_state.value}',
                )

                success = final_state == AgentState.FINISHED

                # Check for output data
                outputs = worker_controller.state.outputs
                extracted_outputs = None
                if outputs:
                    extracted_outputs = outputs

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
                return success, content, error_message

            except Exception as e:
                self._ctrl.log('error', f'Worker execution failed: {e}')
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
                        )
                        for t in parallel_tasks
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
                    action.task_description, getattr(action, 'files', []), blackboard
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
