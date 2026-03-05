"""Event routing service for AgentController.

Routes incoming events from the EventStream to appropriate handlers. Centralizes
all event dispatch logic that was previously inline in AgentController._on_event.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from backend.core.schemas import AgentState
from backend.events import EventSource, RecallType
from backend.events import EventStream
from backend.events.action import (
    Action,
    AgentRejectAction,
    ChangeAgentStateAction,
    MessageAction,
    PlaybookFinishAction,
    TaskTrackingAction,
)
from backend.events.action.agent import (
    ClarificationRequestAction,
    DelegateTaskAction,
    EscalateToHumanAction,
    ProposalAction,
    QueryToolboxAction,
    RecallAction,
    UncertaintyAction,
)
from backend.events.action.message import StreamingChunkAction
from backend.events.observation import (
    Observation,
)
from backend.events.observation.agent import DelegateTaskObservation

if TYPE_CHECKING:
    from backend.controller.agent_controller import AgentController
    from backend.events.event import Event


class EventRouterService:
    """Routes events to the correct handler on AgentController.

    Separates the *what-to-do-with-events* concern from the controller's
    step-execution and lifecycle management.
    """

    def __init__(self, controller: AgentController) -> None:
        self._ctrl = controller

    # ── public entry point ────────────────────────────────────────────

    async def route_event(self, event: Event) -> None:
        """Dispatch a single event to the appropriate handler.

        Hidden events are silently dropped.  Plugin hooks fire first.
        """
        if hasattr(event, "hidden") and event.hidden:
            return

        # Plugin hook: event_emitted
        try:
            from backend.core.plugin import get_plugin_registry

            await get_plugin_registry().dispatch_event(event)
        except Exception:
            pass

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
                    "warning",
                    "Received unknown agent state '%s', ignoring.",
                    extra={"agent_state": action.agent_state},
                )
            else:
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
        elif isinstance(action, QueryToolboxAction):
            await self._handle_query_toolbox_action(action)
        elif isinstance(
            action,
            (ClarificationRequestAction, ProposalAction, UncertaintyAction, EscalateToHumanAction),
        ):
            await self._handle_meta_cognition_action(action)

    async def _handle_task_tracking_action(self, action: TaskTrackingAction) -> None:
        """Handle task tracking action to update active plan."""
        from backend.controller.state.state import ActivePlan, PlanStep

        try:
            # Recursive helper to build steps
            def _build_step(d: dict) -> PlanStep:
                return PlanStep(
                    id=d.get("id", ""),
                    description=d.get("description", d.get("title", "")),
                    status=d.get("status", "pending"),
                    result=d.get("result", d.get("notes")),
                    tags=d.get("tags", []),
                    subtasks=[_build_step(s) for s in d.get("subtasks", [])],
                )

            current_plan = self._ctrl.state.plan
            current_title = current_plan.title if current_plan else "Current Plan"

            steps = [_build_step(t) for t in action.task_list]
            self._ctrl.state.plan = ActivePlan(
                steps=steps,
                title=current_title,
            )
            self._ctrl.log("info", f"Plan updated with {len(steps)} steps.")
        except Exception as e:
            self._ctrl.log("error", f"Failed to update plan: {e}")

    async def _handle_finish_action(self, action: PlaybookFinishAction) -> None:
        """Handle agent finish action with completion validation."""
        if not await self._ctrl.task_validation_service.handle_finish(action):
            return
        self._ctrl.state.set_outputs(action.outputs, source="EventRouterService.finish")
        await self._ctrl.set_agent_state_to(AgentState.FINISHED)
        await self._ctrl.log_task_audit(status="success")

    async def _handle_reject_action(self, action: AgentRejectAction) -> None:
        """Handle agent reject action."""
        self._ctrl.state.set_outputs(action.outputs, source="EventRouterService.reject")
        await self._ctrl.set_agent_state_to(AgentState.REJECTED)

    async def _handle_message_action(self, action: MessageAction) -> None:
        """Handle message actions from users or agents."""
        if action.source == EventSource.USER:
            await self._handle_user_message(action)
        elif action.source == EventSource.AGENT:
            if action.wait_for_response:
                await self._ctrl.set_agent_state_to(AgentState.AWAITING_USER_INPUT)

    async def _handle_user_message(self, action: MessageAction) -> None:
        """Handle user message: log, create recall, set pending, start agent."""
        log_level = "info" if os.getenv("LOG_ALL_EVENTS") in ("true", "1") else "debug"
        self._ctrl.log(
            log_level,
            str(action),
            extra={"msg_type": "ACTION", "event_source": EventSource.USER},
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

        pending_service = getattr(self._ctrl, "pending_action_service", None)
        if pending_service is not None:
            pending_service.set(recall_action)
        else:
            action_service = getattr(self._ctrl, "action_service", None)
            if action_service is not None:
                action_service.set_pending_action(recall_action)
        self._ctrl.event_stream.add_event(recall_action, EventSource.USER)
        if self._ctrl.get_agent_state() != AgentState.RUNNING:
            await self._ctrl.set_agent_state_to(AgentState.RUNNING)

    async def _handle_delegate_task_action(self, action: DelegateTaskAction) -> None:
        """Handle delegating a subtask to a worker agent."""
        import uuid
        from backend.utils.async_utils import run_or_schedule
        from backend.api.services.conversation_stats import ConversationStats
        from backend.controller.agent import Agent
        from backend.controller.agent_controller import AgentController
        from backend.controller.controller_config import ControllerConfig
        from backend.controller.blackboard import Blackboard
        from backend.core.config.agent_config import AgentConfig

        blackboard = Blackboard()

        # Background task so we don't block the routing loop
        async def _execute_single_worker(
            task_description: str, files: list, shared_blackboard: Blackboard | None = None
        ) -> tuple[bool, str, str]:
            """Run one worker agent and return (success, content, error_message)."""
            try:
                # Get the base agent config but clear history
                parent_config = self._ctrl.config
                worker_id = f"{parent_config.sid}_sub_{uuid.uuid4().hex[:8]}"

                file_store = (
                    parent_config.file_store
                    or getattr(self._ctrl.event_stream, "file_store", None)
                )
                if file_store is None:
                    raise RuntimeError("No file_store available for worker event stream")

                user_id = getattr(parent_config, "user_id", None)

                # Find the agent config for 'coder' or fallback to the parent's agent config
                agent_configs = getattr(parent_config, "agent_configs", None) or {}
                worker_agent_config = agent_configs.get("coder")
                if worker_agent_config is None:
                    # Fall back to the currently running agent's config.
                    worker_agent_config = getattr(self._ctrl.agent, "config", None)

                if worker_agent_config is None:
                    # Last-ditch: try to construct a minimal config targeting Orchestrator.
                    worker_agent_config = AgentConfig(name="Orchestrator")

                # Ensure config is a proper AgentConfig instance.
                if not isinstance(worker_agent_config, AgentConfig):
                    try:
                        worker_agent_config = AgentConfig.model_validate(worker_agent_config)
                    except Exception as exc:
                        raise RuntimeError(
                            f"Invalid worker agent config type: {type(worker_agent_config)}"
                        ) from exc

                # Prefer a dedicated LLM config if provided in agent_to_llm_config.
                agent_to_llm_config = (
                    getattr(parent_config, "agent_to_llm_config", None) or {}
                )
                llm_cfg = agent_to_llm_config.get("coder") or agent_to_llm_config.get(
                    worker_agent_config.name
                )
                if llm_cfg is not None:
                    worker_agent_config = worker_agent_config.model_copy(
                        deep=True, update={"llm_config": llm_cfg}
                    )

                # Setup isolated event stream
                worker_stream = EventStream(worker_id, file_store=file_store, user_id=user_id)
                self._ctrl.log(
                    "info",
                    f"Spawning worker agent {worker_id} for task: {task_description[:50]}...",
                )

                # Send the initial user message/directive to the worker.
                # Inject parent's working memory, notes, and task plan so the
                # sub-agent has full context without needing to rediscover it.
                parent_context_lines: list[str] = [
                    f"You are a worker agent delegated the following task:\n\n{task_description}\n\nFocus ONLY on this task. Once completed, finish."
                ]
                if shared_blackboard is not None:
                    parent_context_lines.append(
                        "\n\nSHARED BLACKBOARD: Use the blackboard tool (get/set/keys) to coordinate with other parallel workers. Publish contracts, status, or shared data there."
                    )

                # --- inherit parent working memory ---
                try:
                    from backend.engines.orchestrator.tools.working_memory import (
                        get_full_working_memory,
                    )
                    wm = get_full_working_memory()
                    if wm:
                        parent_context_lines.append(
                            f"\n\nPARENT WORKING MEMORY (read-only context):\n{wm}"
                        )
                except Exception:
                    pass

                # --- inherit parent notes ---
                try:
                    from backend.engines.orchestrator.tools.note import (
                        _load_notes,
                    )
                    notes = _load_notes()
                    if notes:
                        notes_text = "\n".join(
                            f"  {k}: {v}" for k, v in list(notes.items())[:20]
                        )
                        parent_context_lines.append(
                            f"\n\nPARENT NOTES (key-value context):\n{notes_text}"
                        )
                except Exception:
                    pass

                # --- inherit parent task plan ---
                try:
                    from backend.engines.orchestrator.tools.task_tracker import (
                        TaskTracker,
                    )
                    tasks = TaskTracker().load_from_file()
                    if tasks:
                        task_lines = ["PARENT TASK PLAN (for context):"]
                        for t in tasks:
                            status_icon = {"completed": "✓", "in_progress": "O", "failed": "X"}.get(
                                t.get("status", ""), "-"
                            )
                            task_lines.append(
                                f"  [{status_icon}] {t.get('id', '?')} — {t.get('description', t.get('title', ''))}"
                                f" ({t.get('status', 'pending')})"
                            )
                        parent_context_lines.append("\n\n" + "\n".join(task_lines))
                except Exception:
                    pass

                # We need to reuse the same file store/workspace as the parent
                llm_registry = getattr(self._ctrl.agent, "llm_registry", None)
                if llm_registry is None:
                    raise RuntimeError("Parent agent does not expose llm_registry")

                try:
                    agent_cls = Agent.get_cls(worker_agent_config.name)
                except Exception as exc:
                    raise RuntimeError(
                        f"Worker agent class not registered: {worker_agent_config.name}"
                    ) from exc

                worker_agent = agent_cls(config=worker_agent_config, llm_registry=llm_registry)
                if shared_blackboard is not None:
                    worker_agent.blackboard = shared_blackboard  # type: ignore[attr-defined]
                    worker_agent.tools = worker_agent.planner.build_toolset()  # type: ignore[attr-defined]

                conversation_stats = ConversationStats(
                    file_store=file_store,
                    conversation_id=worker_id,
                    user_id=user_id,
                )

                worker_config = ControllerConfig(
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
                )

                worker_controller = AgentController(worker_config)

                init_msg = MessageAction(content="\n".join(parent_context_lines))
                worker_controller.event_stream.add_event(init_msg, EventSource.USER)

                # Ensure the worker starts running
                await worker_controller.set_agent_state_to(AgentState.RUNNING)

                # Emulate the main execution loop for the headless worker.
                # We reuse the controller's own step() logic.
                max_steps = max(10, int(getattr(parent_config, "iteration_delta", 50) or 50))
                for _ in range(max_steps):
                    if worker_controller.get_agent_state() not in (
                        AgentState.RUNNING,
                        AgentState.AWAITING_USER_INPUT,
                        AgentState.PAUSED,
                    ):
                        break
                    worker_controller.step()
                    step_task = getattr(worker_controller, "_step_task", None)
                    if step_task is not None:
                        await step_task

                # Cleanup the worker
                await worker_controller.close(set_stop_state=False)

                final_state = worker_controller.get_agent_state()
                self._ctrl.log(
                    "info",
                    f"Worker agent {worker_id} finished with state {final_state.value}",
                )

                success = final_state == AgentState.FINISHED

                # Check for output data
                outputs = worker_controller.state.outputs
                extracted_outputs = None
                if outputs:
                    extracted_outputs = outputs

                content = str(extracted_outputs) if extracted_outputs else f"Worker completed with status: {final_state.value}"
                error_message = "" if success else f"Agent did not finish gracefully (State: {final_state.value})."
                return success, content, error_message

            except Exception as e:
                self._ctrl.log("error", f"Worker execution failed: {e}")
                return False, "", f"Worker execution crashed: {e}"

        async def _run_subagent():
            """Dispatch single or parallel workers and post the final observation."""
            import asyncio

            parallel_tasks = getattr(action, "parallel_tasks", [])
            if parallel_tasks:
                # Parallel mode — run all workers concurrently
                self._ctrl.log(
                    "info",
                    f"Running {len(parallel_tasks)} sub-agents in parallel",
                )
                results = await asyncio.gather(
                    *[
                        _execute_single_worker(
                            t.get("task_description", ""),
                            t.get("files", []),
                            blackboard,
                        )
                        for t in parallel_tasks
                    ],
                    return_exceptions=False,
                )
                all_success = all(r[0] for r in results)
                parts = []
                for i, (s, c, e) in enumerate(results):
                    label = parallel_tasks[i].get("task_description", f"Task {i+1}")[:40]
                    status = "OK" if s else "FAILED"
                    parts.append(f"[{status}] {label}\n{c or e}")
                combined_content = "\n\n".join(parts)
                if blackboard is not None and blackboard.snapshot():
                    combined_content += "\n\n[SHARED BLACKBOARD SNAPSHOT]\n" + "\n".join(
                        f"  {k}: {v}" for k, v in blackboard.snapshot().items()
                    )
                obs = DelegateTaskObservation(
                    success=all_success,
                    content=combined_content,
                    error_message="" if all_success else "One or more parallel workers failed.",
                )
            else:
                # Single worker mode
                success, content, error_message = await _execute_single_worker(
                    action.task_description, getattr(action, "files", []), blackboard
                )
                if blackboard is not None and blackboard.snapshot():
                    content += "\n\n[SHARED BLACKBOARD SNAPSHOT]\n" + "\n".join(
                        f"  {k}: {v}" for k, v in blackboard.snapshot().items()
                    )
                obs = DelegateTaskObservation(
                    success=success,
                    content=content,
                    error_message=error_message,
                )

            # Ensure the observation maps to the exact action that requested it
            obs.cause = None if getattr(action, "run_in_background", False) else action.id
            obs.tool_call_metadata = action.tool_call_metadata
            self._ctrl.event_stream.add_event(obs, EventSource.ENVIRONMENT)

        if getattr(action, "run_in_background", False):
            early_obs = DelegateTaskObservation(
                success=True,
                content="Worker(s) started in background. Use the blackboard to coordinate.",
                error_message="",
            )
            early_obs.cause = action.id
            early_obs.tool_call_metadata = action.tool_call_metadata
            self._ctrl.event_stream.add_event(early_obs, EventSource.ENVIRONMENT)

        # Run the subagent without blocking
        run_or_schedule(_run_subagent())

    async def _handle_meta_cognition_action(self, action: Action) -> None:
        """Handle meta-cognition actions (clarification, proposal, uncertainty, escalation).

        In FULL autonomy mode, the agent continues without pausing.
        In BALANCED or SUPERVISED mode, the agent pauses and waits for user input.
        """
        from backend.controller.autonomy import AutonomyLevel

        autonomy_ctrl = getattr(self._ctrl, "autonomy_controller", None)
        autonomy_level = (
            getattr(autonomy_ctrl, "autonomy_level", AutonomyLevel.BALANCED.value)
            if autonomy_ctrl
            else AutonomyLevel.BALANCED.value
        )

        if autonomy_level != AutonomyLevel.FULL.value:
            self._ctrl.log(
                "info",
                "Meta-cognition action requires user input, pausing agent.",
                extra={"action_type": type(action).__name__},
            )
            await self._ctrl.set_agent_state_to(AgentState.AWAITING_USER_INPUT)

    async def _handle_query_toolbox_action(self, action: QueryToolboxAction) -> None:
        """Handle query_toolbox: return available tools matching the query."""
        from backend.events.observation import NullObservation

        query = (action.capability_query or "").lower()
        agent = self._ctrl.agent

        results: list[str] = []
        for tool in getattr(agent, "tools", []):
            fn = tool.get("function", {})
            name = fn.get("name", "")
            desc = fn.get("description", "")
            if not query or query in name.lower() or query in desc.lower():
                results.append(f"- {name}: {desc[:120]}")

        mcp_tools = getattr(agent, "mcp_tools", {})
        if mcp_tools:
            for name, tool in mcp_tools.items():
                fn = tool.get("function", {})
                desc = fn.get("description", "")
                if not query or query in name.lower() or query in desc.lower():
                    results.append(f"- {name} [MCP]: {desc[:120]}")

        content = (
            f"Found {len(results)} tool(s) matching '{action.capability_query}':\n"
            + "\n".join(results)
            if results
            else f"No tools found matching '{action.capability_query}'."
        )

        obs = NullObservation(content=content)
        obs.tool_call_metadata = action.tool_call_metadata
        self._ctrl.event_stream.add_event(obs, EventSource.ENVIRONMENT)

    # ── observation dispatch ──────────────────────────────────────────

    async def _handle_observation(self, observation: Observation) -> None:
        """Delegate observation handling to the observation service."""
        await self._ctrl.observation_service.handle_observation(observation)
