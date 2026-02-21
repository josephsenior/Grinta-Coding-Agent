"""Orchestrator agent entrypoint wired to modular planner, executor, and memory subsystems.

Architecture notes (preserve these strengths):
- Protocol-first design: Orchestrator depends on ``PlannerProtocol``,
  ``ExecutorProtocol``, ``SafetyManagerProtocol``, ``MemoryManagerProtocol``
  — never on concrete classes.
- Each subsystem is independently testable and swappable.
- Error recovery follows a typed cascade: ContextLimitError → auto-condense
  → retry → ToolExecutionError → diagnostic think → generic → AgentRuntimeError.
- The event stream is the sole communication channel between controller and agent.
"""

from __future__ import annotations

import contextlib
import os
from collections import deque
from typing import TYPE_CHECKING, Any

import backend.engines.orchestrator.function_calling as codeact_function_calling
from backend.controller.agent import Agent
from backend.controller.state.state import State
from backend.core.config import AgentConfig
from backend.core.errors import (
    AgentRuntimeError,
    ContextLimitError,
    ToolExecutionError,
)
from backend.core.logger import forge_logger as logger
from backend.core.message import Message
from backend.events.action import AgentThinkAction, MessageAction, PlaybookFinishAction
from backend.events.action.files import FileReadAction
from backend.events.event import EventSource
from backend.llm.llm_registry import LLMRegistry
from backend.runtime.plugins import (
    PluginRequirement,
)
from backend.runtime.plugins.agent_skills import AgentSkillsRequirement
from backend.utils.prompt import OrchestratorPromptManager, PromptManager

from .contracts import (
    ExecutorProtocol,
    MemoryManagerProtocol,
    PlannerProtocol,
    SafetyManagerProtocol,
)
from .executor import OrchestratorExecutor
from .memory_manager import ConversationMemoryManager
from .planner import OrchestratorPlanner
from .safety import OrchestratorSafetyManager

if TYPE_CHECKING:
    from backend.events.action import Action
    from backend.events.stream import EventStream


class Orchestrator(Agent):
    """Production orchestrator agent with modular planner–executor–memory architecture."""

    VERSION = "2.2"
    runtime_plugins: list[PluginRequirement] = [
        AgentSkillsRequirement(name="agent_skills"),
    ]

    def __init__(
        self,
        config: AgentConfig,
        llm_registry: LLMRegistry,
        plugin_requirements: list[PluginRequirement] | None = None,
    ) -> None:
        super().__init__(config=config, llm_registry=llm_registry)
        self.plugin_requirements = plugin_requirements or []

        self.pending_actions: deque[Action] = deque()
        self.event_stream: EventStream | None = None

        # Safety / hallucination systems
        from backend.engines.orchestrator.file_verification_guard import (
            FileVerificationGuard,
        )
        from backend.engines.orchestrator.hallucination_detector import (
            HallucinationDetector,
        )

        self.hallucination_detector = HallucinationDetector()
        self.anti_hallucination = FileVerificationGuard()
        self.safety_manager: SafetyManagerProtocol = OrchestratorSafetyManager(
            anti_hallucination=self.anti_hallucination,
            hallucination_detector=self.hallucination_detector,
        )

        # Prompt manager + memory subsystems
        self._prompt_manager: PromptManager = self._create_prompt_manager()
        self._memory_manager_impl = ConversationMemoryManager(config, llm_registry)
        self._memory_manager_impl.initialize(self.prompt_manager)
        # Expose conversation_memory for direct test and utility access
        self.conversation_memory = self._memory_manager_impl.conversation_memory
        # Protocol-typed reference for step() logic
        self.memory_manager: MemoryManagerProtocol = self._memory_manager_impl

        # Register vector-memory callback for the semantic_recall tool
        codeact_function_calling.register_semantic_recall(
            self.conversation_memory.recall_from_memory
        )

        # Planner/executor wiring
        self.planner: PlannerProtocol = OrchestratorPlanner(
            config=self.config,
            llm=self.llm,
            safety_manager=self.safety_manager,
        )
        self.tools = self.planner.build_toolset()

        # Tool registry self-check: ensure every tool exposed to the LLM has a
        # corresponding dispatch handler.
        from backend.engines.orchestrator.tool_registry import validate_internal_toolset

        validate_internal_toolset(
            self.tools,
            strict=bool(getattr(self.config, "strict_tool_registry_check", True)),
        )
        self.executor: ExecutorProtocol = OrchestratorExecutor(
            llm=self.llm,
            safety_manager=self.safety_manager,
            planner=self.planner,
            mcp_tool_name_provider=lambda: self.mcp_tools.keys(),
        )

        # Production health checks
        self.production_health_check_enabled = bool(
            getattr(self.config, "production_health_check", False)
            and getattr(self.config, "health_check_prompts", None)
        )
        self._last_llm_latency: float = 0.0
        self._reflection_interval: int = int(
            getattr(self.config, "reflection_interval", 10)
        )
        self._steps_since_reflection: int = 0
        self._run_production_health_check()

    # ------------------------------------------------------------------ #
    # Initialization helpers
    # ------------------------------------------------------------------ #
    def _create_prompt_manager(self) -> PromptManager:
        prompt_dir = os.path.join(os.path.dirname(__file__), "prompts")
        system_prompt = self.config.resolved_system_prompt_filename
        if not os.path.exists(os.path.join(prompt_dir, system_prompt)):
            system_prompt = "system_prompt.j2"

        return OrchestratorPromptManager(
            prompt_dir=prompt_dir,
            system_prompt_filename=system_prompt,
            config=self.config,
        )

    def _run_production_health_check(self) -> None:
        try:
            from backend.engines.orchestrator.tools.health_check import (
                run_production_health_check,
            )

            run_production_health_check(raise_on_failure=True)
        except ImportError:
            logger.warning(
                "Health check module not found - skipping dependency validation"
            )
        except RuntimeError as exc:
            logger.error("Production health check failed: %s", exc)
            raise

    # ------------------------------------------------------------------ #
    # Core agent operations
    # ------------------------------------------------------------------ #
    def reset(self, state: State | None = None) -> None:
        super().reset()
        self.pending_actions.clear()

    def step(self, state: State) -> Action:
        try:
            exit_action = self._check_exit_command(state)
            if exit_action:
                return exit_action

            pending = self._consume_pending_action()
            if pending:
                self._steps_since_reflection += 1
                return pending

            # Periodic self-reflection checkpoint
            reflection = self._maybe_inject_reflection(state)
            if reflection:
                return reflection

            condensed = self.memory_manager.condense_history(state)
            self._steps_since_reflection += 1
            return self._execute_llm_step(state, condensed)

        except ContextLimitError:
            # Auto-heal: condense once and retry before giving up
            logger.warning(
                "Auto-Healing: Context limit reached. Attempting condensation + retry."
            )
            try:
                condensed = self.memory_manager.condense_history(state)
                return self._execute_llm_step(state, condensed)
            except Exception:
                logger.warning(
                    "Auto-Healing retry failed after condensation. Falling back to think action."
                )
                return AgentThinkAction(
                    thought="I have reached the context limit. I must condense my memory before proceeding.",
                )

        except ToolExecutionError as e:
            logger.warning("Auto-Healing: Tool Execution Error: %s", e)
            return AgentThinkAction(
                thought=f"I encountered a tool error: {str(e)}. I will analyze the last tool call and retry.",
            )

        except Exception as e:
            logger.error("Critical Failure in Orchestrator.step: %s", e, exc_info=True)
            # Wrap generic exceptions in AgentRuntimeError for standardized handling upstream
            raise AgentRuntimeError(f"Critical agent failure: {str(e)}") from e

    def _execute_llm_step(self, state: State, condensed: Any) -> Action:
        """Core logic to prepare messages, call LLM, and return the first action."""
        if condensed.pending_action:
            # Extract initial task text for semantic recall during recovery
            try:
                initial_msg = self.memory_manager.get_initial_user_message(
                    state.history
                )
                task_text = (
                    getattr(initial_msg, "content", "")[:200] if initial_msg else ""
                )
            except Exception:
                task_text = ""
            self._queue_post_condensation_recovery(task_text=task_text)
            return condensed.pending_action

        initial_user_message = self.memory_manager.get_initial_user_message(
            state.history
        )

        # Prompt tiers: avoid injecting large, rarely-needed blocks every turn.
        # Escalate to "debug" when we recently touched files or saw tool errors.
        try:
            from backend.events.observation import ErrorObservation
            from backend.events.action import FileEditAction, FileWriteAction

            recent = state.history[-12:] if len(state.history) > 12 else state.history
            has_recent_error = any(isinstance(e, ErrorObservation) for e in recent)
            has_recent_file_op = any(
                isinstance(e, (FileEditAction, FileWriteAction)) for e in recent
            )
            tier = "debug" if (has_recent_error or has_recent_file_op) else "base"
            self.prompt_manager.set_prompt_tier(tier)
        except Exception:
            pass

        messages = self.memory_manager.build_messages(
            condensed_history=condensed.events,
            initial_user_message=initial_user_message,
            llm_config=self.llm.config,
        )
        serialized_messages = self._serialize_messages(messages)
        params = self.planner.build_llm_params(serialized_messages, state, self.tools)
        self._sync_executor_llm()

        result = self.executor.execute(params, self.event_stream)

        # Ack turn-scoped directives only after a successful LLM call.
        # This makes retries (context-limit, transient tool errors, etc.)
        # deterministic: signals persist until an actual successful model response.
        try:
            if hasattr(state, "ack_planning_directive"):
                state.ack_planning_directive(source="Orchestrator")
            if hasattr(state, "ack_memory_pressure"):
                state.ack_memory_pressure(source="Orchestrator")
        finally:
            # Backward-compatible cleanup
            with contextlib.suppress(Exception):
                state.extra_data.pop("planning_directive", None)
                state.extra_data.pop("memory_pressure", None)

        # Track LLM latency for adaptive rate governing
        self._last_llm_latency = result.execution_time

        actions = result.actions or []
        if not actions:
            return self._build_fallback_action(result)

        self._queue_additional_actions(actions[1:])
        return actions[0]

    # ------------------------------------------------------------------ #
    # Test/mocking helpers
    # ------------------------------------------------------------------ #
    def set_llm(self, llm) -> None:  # pragma: no cover - used in tests
        """Replace the active LLM and propagate to planner/executor.

        Some unit tests inject a mock LLM after agent construction. The
        executor and planner capture the original reference at init time,
        so we provide an explicit helper to keep their internal references
        in sync to avoid unintended real network calls.
        """
        self.llm = llm
        if hasattr(self, "planner") and hasattr(self.planner, "_llm"):
            try:
                self.planner._llm = llm  # type: ignore[attr-defined]
            except Exception:
                pass
        if hasattr(self, "executor") and hasattr(self.executor, "_llm"):
            try:
                self.executor._llm = llm  # type: ignore[attr-defined]
            except Exception:
                pass

    def _consume_pending_action(self) -> Action | None:
        if not self.pending_actions:
            return None
        # Try to batch consecutive read-only file reads into one action
        batched = self._try_batch_file_reads()
        if batched:
            return batched
        return self.pending_actions.popleft()

    def _serialize_messages(self, messages: list[Message]) -> list[dict]:
        serialized: list[dict] = []
        for msg in messages:
            serialized.append(self._serialize_single_message(msg))
        return serialized

    def _serialize_single_message(self, msg: Message) -> dict:
        raw = self._serialize_message_with_fallback(msg)
        content_val = raw.get("content", "")
        if isinstance(content_val, list):
            raw["content"] = self._flatten_content_list(content_val)
        return raw

    def _serialize_message_with_fallback(self, msg: Message) -> dict:
        try:
            return msg.serialize_model()  # type: ignore[attr-defined]
        except Exception:
            fallback_lines = self._extract_text_chunks(msg)
            return {
                "role": msg.role,
                "content": "\n".join(fallback_lines),
            }

    def _extract_text_chunks(self, msg: Message) -> list[str]:
        fallback_lines: list[str] = []
        for chunk in getattr(msg, "content", []) or []:
            value = getattr(chunk, "text", None)
            if value is None and isinstance(chunk, dict):
                value = chunk.get("text")
            if value:
                fallback_lines.append(str(value))
        return fallback_lines

    def _flatten_content_list(self, content_val: list[Any]) -> str:
        texts = [
            str(item["text"])
            for item in content_val
            if isinstance(item, dict) and "text" in item
        ]
        return "\n".join(texts)

    def _sync_executor_llm(self) -> None:
        if (
            hasattr(self, "executor")
            and getattr(self.executor, "_llm", None) is not self.llm
        ):
            try:  # pragma: no cover - defensive assignment
                self.executor._llm = self.llm  # type: ignore[attr-defined]
            except Exception:
                pass

    def _build_fallback_action(self, result) -> Action:
        """Create a fallback action when the LLM produces no tool calls.

        This typically means the LLM returned pure-text (e.g. a final answer
        or a refusal).  We surface it as a ``MessageAction`` so the
        controller can decide whether to continue or stop.

        If the LLM returned an entirely empty response we inject a
        diagnostic ``AgentThinkAction`` so the loop doesn't silently
        stall.
        """
        message_text = ""
        if result.response and getattr(result.response, "choices", None):
            first_choice = result.response.choices[0]
            message = getattr(first_choice, "message", None)
            if message is not None:
                message_text = getattr(message, "content", "") or ""

        if not message_text.strip():
            logger.warning(
                "LLM returned an empty response with no tool calls — injecting diagnostic think action"
            )
            return AgentThinkAction(
                thought=(
                    "The LLM returned an empty response with no actions. "
                    "I will re-evaluate the current state and try again."
                )
            )

        fallback = MessageAction(content=message_text)
        fallback.source = EventSource.AGENT
        return fallback

    def _queue_additional_actions(self, actions: list[Action]) -> None:
        for pending in actions:
            self.pending_actions.append(pending)

    def _try_batch_file_reads(self) -> Action | None:
        """Batch consecutive read-only actions into a single CmdRunAction.

        When the LLM emits multiple file reads or search actions in one
        response, executing them one-per-step is wasteful.  This collapses
        them into a single command that processes all requested operations,
        cutting round-trips.
        """
        if len(self.pending_actions) < 2:
            return None

        # Collect the leading run of FileReadAction entries
        batch: list[FileReadAction] = []
        for action in self.pending_actions:
            if isinstance(action, FileReadAction):
                batch.append(action)
            else:
                break

        if len(batch) < 2:
            return None

        # Pop them from the queue
        for _ in batch:
            self.pending_actions.popleft()

        import os
        from backend.events.action.commands import CmdRunAction

        is_windows = os.name == "nt"

        # Build a single command that prints each file with a clear header
        parts: list[str] = []
        for fr in batch:
            path = fr.path
            if fr.start == 0 and fr.end == -1 and not fr.view_range:
                # Full file read
                if is_windows:
                    parts.append(
                        f'Write-Output "=== FILE: {path} ===" ; Get-Content "{path}"'
                    )
                else:
                    parts.append(
                        f'echo "=== FILE: {path} ===" && cat "{path}"'
                    )
            else:
                # Partial read with line range
                start = fr.start
                end = fr.end
                if fr.view_range:
                    start = fr.view_range[0] - 1 if len(fr.view_range) > 0 else 0
                    end = fr.view_range[1] if len(fr.view_range) > 1 else -1
                if is_windows:
                    if end == -1:
                        parts.append(
                            f'Write-Output "=== FILE: {path} (lines {start + 1}+) ===" ; '
                            f'Get-Content "{path}" | Select-Object -Skip {start}'
                        )
                    else:
                        count = end - start
                        parts.append(
                            f'Write-Output "=== FILE: {path} (lines {start + 1}-{end}) ===" ; '
                            f'Get-Content "{path}" | Select-Object -Skip {start} -First {count}'
                        )
                else:
                    if end == -1:
                        parts.append(
                            f'echo "=== FILE: {path} (lines {start + 1}+) ===" && '
                            f'tail -n +{start + 1} "{path}"'
                        )
                    else:
                        count = end - start
                        parts.append(
                            f'echo "=== FILE: {path} (lines {start + 1}-{end}) ===" && '
                            f'sed -n "{start + 1},{end}p" "{path}"'
                        )

        if is_windows:
            combined_cmd = " ; ".join(parts)
        else:
            combined_cmd = " && ".join(parts)
        return CmdRunAction(command=combined_cmd, thought="Batched parallel file reads")

    def _queue_post_condensation_recovery(self, task_text: str = "") -> None:
        """Inject recovery actions after condensation so the agent re-orients.

        This enforces the recovery sequence described in SELF_REGULATION.
        All steps are system-injected — the agent does NOT need to call them
        explicitly, removing reliance on prompt-compliance:
        1. Inject restored context from pre-condensation snapshot
        2. Inject working memory (structured cognitive workspace)
        3. Auto semantic recall against the task description
        4. Recall all scratchpad notes
        5. Auto-inject task_tracker state (system-enforced, not prompt-reliant)
        6. Inject lessons.md content if available
        """
        from backend.engines.orchestrator.tools.note import build_recall_action
        from backend.engines.orchestrator.tools.working_memory import (
            get_full_working_memory,
        )
        from backend.engines.orchestrator.tools.task_tracker import TaskTracker

        # Load the auto-extracted context snapshot
        restored = self._memory_manager_impl.get_restored_context()
        restored_block = f"\n\n{restored}" if restored else ""

        # Load structured working memory
        wm = get_full_working_memory()
        wm_block = f"\n\n{wm}" if wm else ""

        # Auto semantic recall — query vector memory with the task description
        semantic_block = ""
        if task_text:
            recall_fn = codeact_function_calling.get_semantic_recall_fn()
            if recall_fn:
                try:
                    results = recall_fn(task_text, 3)
                    if results:
                        parts = ["\n\n<SEMANTIC_RECALL_RECOVERY>"]
                        for i, item in enumerate(results, 1):
                            content = item.get("content_text", item.get("content", ""))
                            parts.append(f"  [{i}] {content[:300]}")
                        parts.append("</SEMANTIC_RECALL_RECOVERY>")
                        semantic_block = "\n".join(parts)
                except Exception:
                    pass  # Non-critical — don't block recovery on recall failure

        # Auto-inject lessons.md (cross-session learning) — system-enforced read
        lessons_block = ""
        try:
            lessons_path = "/memories/repo/lessons.md"
            import os as _os
            if _os.path.exists(lessons_path):
                with open(lessons_path, encoding="utf-8") as _f:
                    lessons_content = _f.read(2000)  # Cap at 2000 chars
                if lessons_content.strip():
                    lessons_block = f"\n\n<LESSONS_MD_RECOVERY>\n{lessons_content}\n</LESSONS_MD_RECOVERY>"
        except Exception:
            pass  # Non-critical

        # Auto-inject task tracker state — system-enforced, reads plan file directly
        task_tracker_block = ""
        try:
            tracker = TaskTracker()
            tasks = tracker.load_from_file()
            if tasks:
                task_lines = ["<TASK_TRACKER_RECOVERY>"]
                for t in tasks:
                    status_icon = {"completed": "✓", "in_progress": "O", "failed": "X"}.get(
                        t.get("status", ""), "-"
                    )
                    task_lines.append(
                        f"  [{status_icon}] {t.get('id', '?')} — {t.get('description', t.get('title', ''))}"
                        f" ({t.get('status', 'pending')})"
                    )
                task_lines.append("</TASK_TRACKER_RECOVERY>")
                task_tracker_block = "\n\n" + "\n".join(task_lines)
        except Exception:
            pass  # Non-critical

        recovery_think = AgentThinkAction(
            thought=(
                "⚡ CONTEXT CONDENSED — mandatory recovery sequence complete (system-enforced). "
                "The following context has been automatically restored:"
                f"{restored_block}"
                f"{wm_block}"
                f"{semantic_block}"
                f"{lessons_block}"
                f"{task_tracker_block}"
            )
        )
        recall_action = build_recall_action({"key": "all"})

        self.pending_actions.append(recovery_think)
        self.pending_actions.append(recall_action)

    def _maybe_inject_reflection(self, state: State | None = None) -> Action | None:
        """Inject a structured self-reflection think action every N steps.

        Unlike the previous version which asked vague questions, this version
        provides concrete session metrics for the LLM to reflect on:
        - Turn count and remaining budget
        - Files modified this session
        - Error count from recent history
        - Token usage percentage
        - The original user request (re-injected for goal alignment)

        Returns an AgentThinkAction if the interval has elapsed, else None.
        The counter resets after each reflection.
        """
        if self._reflection_interval <= 0:
            return None
        if self._steps_since_reflection < self._reflection_interval:
            return None

        self._steps_since_reflection = 0

        # Build structured reflection data
        data_parts: list[str] = []

        if state is not None:
            # Turn progress
            iter_flag = getattr(state, "iteration_flag", None)
            current = getattr(iter_flag, "current_value", 0) if iter_flag else 0
            max_val = getattr(iter_flag, "max_value", 0) if iter_flag else 0
            if current:
                progress = f"Turn {current}"
                if max_val:
                    progress += (
                        f"/{max_val} ({int(current / max_val * 100)}% of budget)"
                    )
                data_parts.append(f"  • Progress: {progress}")

            # Token usage
            metrics = getattr(state, "metrics", None)
            if metrics:
                atu = getattr(metrics, "accumulated_token_usage", None)
                if atu:
                    prompt_tok = getattr(atu, "prompt_tokens", 0)
                    ctx_window = getattr(atu, "context_window", 0)
                    if prompt_tok and ctx_window:
                        pct = int(prompt_tok / ctx_window * 100)
                        data_parts.append(
                            f"  • Context usage: {pct}% ({prompt_tok}/{ctx_window} tokens)"
                        )

                cost = getattr(metrics, "accumulated_cost", 0.0)
                if cost > 0:
                    data_parts.append(f"  • Cost so far: ${cost:.4f}")

            # Files modified (from file verification guard)
            modified_files = list(self.anti_hallucination._file_modified_turns.keys())
            if modified_files:
                files_str = ", ".join(modified_files[-5:])  # last 5
                if len(modified_files) > 5:
                    files_str += f" (+{len(modified_files) - 5} more)"
                data_parts.append(f"  • Files modified: {files_str}")

            # Error count
            error_count = 0
            for event in reversed(list(getattr(state, "history", []))):
                cls_name = type(event).__name__
                if cls_name == "ErrorObservation":
                    error_count += 1
                if error_count >= 20:
                    break
            if error_count:
                data_parts.append(f"  • Errors encountered: {error_count}")

            # Original user request
            try:
                initial_msg = self.memory_manager.get_initial_user_message(
                    state.history
                )
                task_text = getattr(initial_msg, "content", "")[:200]
                if task_text:
                    data_parts.append(f'  • Original request: "{task_text}"')
            except Exception:
                pass

        data_block = "\n".join(data_parts) if data_parts else "  (no metrics available)"

        return AgentThinkAction(
            thought=(
                "🔍 SELF-REFLECTION CHECKPOINT — Session metrics:\n"
                f"{data_block}\n\n"
                "Based on these metrics, assess:\n"
                "1. Am I making progress toward the original goal?\n"
                "2. Should I change strategy (too many errors, repeated edits)?\n"
                "3. Should I update the task tracker with current progress?\n"
                "4. Is there a simpler path I'm overlooking?"
            )
        )

    # ------------------------------------------------------------------ #
    # Convenience helpers
    # ------------------------------------------------------------------ #
    def _check_exit_command(self, state: State) -> Action | None:
        latest_user_message = state.get_last_user_message()
        if latest_user_message and latest_user_message.content.strip() == "/exit":
            return PlaybookFinishAction()
        return None

    def response_to_actions(self, response) -> list[Action]:
        """Convert an LLM response into executable actions."""
        return codeact_function_calling.response_to_actions(
            response, 
            mcp_tool_names=list(self.mcp_tools.keys()),
            mcp_tools=self.mcp_tools
        )

    def set_mcp_tools(self, mcp_tools: list[dict]) -> None:
        """Set MCP tools and sync names to prompt manager for dynamic discovery."""
        super().set_mcp_tools(mcp_tools)

        # Warn early if MCP tool names collide with internal tool names.
        from backend.engines.orchestrator.tool_registry import (
            validate_mcp_tool_name_collisions,
        )

        validate_mcp_tool_name_collisions(
            self.tools,
            self.mcp_tools.keys(),
            strict=bool(getattr(self.config, "strict_mcp_tool_name_collision", False)),
        )
        # Sync connected tool names and descriptions so the system prompt reflects reality
        pm = getattr(self, "_prompt_manager", None)
        if pm and hasattr(pm, "mcp_tool_names"):
            pm.mcp_tool_names = list(self.mcp_tools.keys())
            descriptions: dict[str, str] = {}
            for tool_dict in mcp_tools:
                name = tool_dict.get("name", "")
                desc = tool_dict.get("description", "")
                if name and desc:
                    first_line = desc.split("\n")[0][:120]
                    descriptions[name] = first_line
            if hasattr(pm, "mcp_tool_descriptions"):
                pm.mcp_tool_descriptions = descriptions
        # Surface any MCP connection failures before the first user response so the
        # agent immediately knows which tools are unavailable, avoiding wasted turns
        # diagnosing connectivity issues at call-time.
        from backend.mcp_integration.error_collector import mcp_error_collector

        errors = mcp_error_collector.get_errors()
        if errors:
            lines = [
                "WARNING: Some MCP servers failed to connect. "
                "The following tools may be unavailable:",
            ]
            for err in errors:
                lines.append(
                    f"  - {err.server_name} ({err.server_type}): {err.error_message}"
                )
            lines.append("Do not attempt to call these tools. Plan accordingly.")
            think = AgentThinkAction(thought="\n".join(lines))
            self.pending_actions.appendleft(think)
