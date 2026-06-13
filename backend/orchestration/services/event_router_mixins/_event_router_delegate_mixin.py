"""Delegate methods for EventRouterService.

Delegate task action handling and observation dispatch.

Extracted from backend/orchestration/services/event_router_service.py
to keep the parent module under the per-file LOC budget. All methods
rely on attributes/methods defined on EventRouterService; this mixin
is meant to be combined with that class via multiple inheritance.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from backend.core.schemas import AgentState
from backend.ledger import EventSource, EventStream, EventStreamSubscriber
from backend.ledger.action import (
    Action,
    MessageAction,
)
from backend.ledger.action.agent import (
    DelegateTaskAction,
)
from backend.ledger.observation import (
    ErrorObservation,
    Observation,
)
from backend.ledger.observation.agent import (
    DelegateTaskObservation,
)
from backend.ledger.observation_cause import attach_observation_cause

if TYPE_CHECKING:
    from backend.orchestration.services.event_router_service import EventRouterService

logger = logging.getLogger(__name__)


# Re-export delegate helpers for use by method bodies below (each is
# referenced inside `_handle_delegate_task_action` etc.). They were moved
# out of event_router_service.py to keep that file under the per-file
# LOC budget.
from backend.orchestration.services.event_router_mixins._event_router_delegate_helpers import (  # noqa: E402
    _build_delegate_progress_observation,  # noqa: F401
    _looks_like_text_tool_call_handoff,  # noqa: F401
    _summarize_delegate_browser_action,  # noqa: F401
    _summarize_delegate_command_action,  # noqa: F401
    _summarize_delegate_error_event,  # noqa: F401
    _summarize_delegate_file_action,  # noqa: F401
    _summarize_delegate_finish_event,  # noqa: F401
    _summarize_delegate_mcp_action,  # noqa: F401
    _summarize_delegate_recall_action,  # noqa: F401
    _summarize_delegate_reject_event,  # noqa: F401
    _summarize_delegate_state_event,  # noqa: F401
    _summarize_delegate_task_tracking_action,  # noqa: F401
    _summarize_delegate_terminal_event,  # noqa: F401
    _summarize_delegate_think_action,  # noqa: F401
    _summarize_delegate_worker_event,  # noqa: F401
    _truncate_delegate_progress,  # noqa: F401
)


class _EventRouterDelegateMixin:
    """Mixin class — see module docstring."""

    if TYPE_CHECKING:
        _ctrl: Any  # Actually EventRouterService control interface


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
                    f'You are a worker agent (depth {worker_depth}/{MAX_DELEGATION_DEPTH}) delegated the following task:\n\n{task_description}\n\nFocus ONLY on this task. Once completed, write a final response.\n\n'
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
                    from backend.core.task_tracker import TaskTracker

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

    async def _handle_observation(self, observation: Observation) -> None:
        """Delegate observation handling to the observation service.

        Bounded with ``asyncio.wait_for(..., timeout=10s)`` so a hung
        observation handler cannot wedge the agent.  If the handler
        times out, we log at WARNING and force-emit the post-resolution
        step so the next ``astep`` can run.  This is the recovery path
        that complements the LLM step timeout (Layer 1) and the
        runtime action timeout.
        """
        import asyncio as _asyncio

        from backend.core.constants import (
            DEFAULT_OBSERVATION_HANDLER_TIMEOUT_SECONDS,
        )

        observation_id = getattr(observation, 'id', '?')
        observation_type = type(observation).__name__
        logger.debug(
            '[_handle_observation] ENTER %s (id=%s)',
            observation_type,
            observation_id,
            extra={'msg_type': 'OBSERVATION_HANDLER_ENTER'},
        )
        try:
            await _asyncio.wait_for(
                self._ctrl.observation_service.handle_observation(observation),
                timeout=DEFAULT_OBSERVATION_HANDLER_TIMEOUT_SECONDS,
            )
        except _asyncio.TimeoutError:
            logger.warning(
                'Observation handler timed out after %.1fs for %s (id=%s); '
                'forcing post-resolution step to avoid wedging the agent',
                DEFAULT_OBSERVATION_HANDLER_TIMEOUT_SECONDS,
                observation_type,
                observation_id,
                extra={'msg_type': 'OBSERVATION_HANDLER_TIMEOUT'},
            )
            # Force-clear any stuck pending state so the next step can run.
            try:
                pending_service = getattr(
                    getattr(self._ctrl, 'services', None),
                    'pending_action',
                    None,
                )
                if pending_service is not None:
                    pending_service.clear_all()
            except Exception:
                logger.debug(
                    'Failed to force-clear pending state after handler timeout',
                    exc_info=True,
                )
            # Schedule the next step directly.
            try:
                trigger = getattr(self._ctrl, 'step', None)
                if callable(trigger):
                    trigger()
            except Exception:
                logger.debug(
                    'Failed to trigger step after handler timeout',
                    exc_info=True,
                )
        except Exception as exc:
            logger.error(
                '[_handle_observation] exception in %s (id=%s): %s: %s',
                observation_type,
                observation_id,
                type(exc).__name__,
                exc,
                exc_info=True,
                extra={'msg_type': 'OBSERVATION_HANDLER_EXCEPTION'},
            )
            raise
        finally:
            logger.debug(
                '[_handle_observation] EXIT %s (id=%s)',
                observation_type,
                observation_id,
                extra={'msg_type': 'OBSERVATION_HANDLER_EXIT'},
            )
