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

import backend.engines.orchestrator.function_calling as orchestrator_function_calling
from backend.controller.agent import Agent
from backend.controller.state.state import State
from backend.core.config import AgentConfig
from backend.core.errors import (
    AgentRuntimeError,
    ContextLimitError,
    ModelProviderError,
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


def _escape_ps_path(path: str) -> str:
    """Escape a file path for safe use in a PowerShell double-quoted string."""
    # Backtick-escape characters special to PowerShell double-quoted strings.
    return path.replace('`', '``').replace('"', '`"').replace('$', '`$')


def _build_full_file_read_command(path: str, is_windows: bool) -> str:
    """Build command to read entire file."""
    if is_windows:
        safe = _escape_ps_path(path)
        return f'Write-Output "=== FILE: {safe} ===" ; Get-Content "{safe}" -Encoding UTF8'
    return f'echo "=== FILE: {path} ===" && cat "{path}"'


def _build_partial_file_read_command(
    path: str, start: int, end: int, is_windows: bool
) -> str:
    """Build command to read file lines [start, end). end=-1 means to end."""
    header = f'lines {start + 1}-{end}' if end != -1 else f'lines {start + 1}+'
    if is_windows:
        safe = _escape_ps_path(path)
        win_header = f'Write-Output "=== FILE: {safe} ({header}) ===" ; '
        if end == -1:
            return win_header + f'Get-Content "{safe}" -Encoding UTF8 | Select-Object -Skip {start}'
        count = end - start
        return win_header + f'Get-Content "{safe}" -Encoding UTF8 | Select-Object -Skip {start} -First {count}'
    unix_header = f'echo "=== FILE: {path} ({header}) ===" && '
    if end == -1:
        return unix_header + f'tail -n +{start + 1} "{path}"'
    return unix_header + f'sed -n "{start + 1},{end}p" "{path}"'


def _build_file_read_command(fr: FileReadAction, is_windows: bool) -> str:
    """Build a shell command for one file read (full or partial, Windows or Unix)."""
    path = fr.path
    start, end = fr.start, fr.end
    if fr.view_range:
        start = fr.view_range[0] - 1 if len(fr.view_range) > 0 else 0
        end = fr.view_range[1] if len(fr.view_range) > 1 else -1

    if start == 0 and end == -1 and not fr.view_range:
        return _build_full_file_read_command(path, is_windows)
    return _build_partial_file_read_command(path, start, end, is_windows)


def _format_reflection_progress(state: State) -> str:
    """Format progress line from iteration_flag."""
    iter_flag = getattr(state, "iteration_flag", None)
    current = getattr(iter_flag, "current_value", 0) if iter_flag else 0
    max_val = getattr(iter_flag, "max_value", 0) if iter_flag else 0
    if not current:
        return ""
    progress = f"Turn {current}"
    if max_val:
        progress += f"/{max_val} ({int(current / max_val * 100)}% of budget)"
    return f"  • Progress: {progress}"


def _format_reflection_metrics(state: State) -> list[str]:
    """Format context usage and cost lines from metrics."""
    parts: list[str] = []
    metrics = getattr(state, "metrics", None)
    if not metrics:
        return parts
    atu = getattr(metrics, "accumulated_token_usage", None)
    if atu:
        prompt_tok = getattr(atu, "prompt_tokens", 0)
        ctx_window = getattr(atu, "context_window", 0)
        if prompt_tok and ctx_window:
            pct = int(prompt_tok / ctx_window * 100)
            parts.append(f"  • Context usage: {pct}% ({prompt_tok}/{ctx_window} tokens)")
    cost = getattr(metrics, "accumulated_cost", 0.0)
    if cost > 0:
        parts.append(f"  • Cost so far: ${cost:.4f}")
    return parts


def _format_reflection_modified_files(modified_files: list[str]) -> str:
    """Format modified files line."""
    if not modified_files:
        return ""
    files_str = ", ".join(modified_files[-5:])
    if len(modified_files) > 5:
        files_str += f" (+{len(modified_files) - 5} more)"
    return f"  • Files modified: {files_str}"


def _format_reflection_initial_request(
    memory_manager: Any, history: list
) -> str:
    """Format original request line from initial user message."""
    try:
        initial_msg = memory_manager.get_initial_user_message(history)
        task_text = getattr(initial_msg, "content", "")[:200]
        return f'  • Original request: "{task_text}"' if task_text else ""
    except Exception:
        return ""


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
        if self.conversation_memory is not None:
            orchestrator_function_calling.register_semantic_recall(
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

        except ModelProviderError:
            raise

        except Exception as e:
            logger.error("Critical Failure in Orchestrator.step: %s", e, exc_info=True)
            # Wrap generic exceptions in AgentRuntimeError for standardized handling upstream
            raise AgentRuntimeError(f"Critical agent failure: {str(e)}") from e

    async def astep(self, state: State) -> Action:
        """Async version of step() that uses real LLM streaming."""
        try:
            exit_action = self._check_exit_command(state)
            if exit_action:
                return exit_action

            pending = self._consume_pending_action()
            if pending:
                self._steps_since_reflection += 1
                return pending

            reflection = self._maybe_inject_reflection(state)
            if reflection:
                return reflection

            condensed = self.memory_manager.condense_history(state)
            self._steps_since_reflection += 1
            return await self._execute_llm_step_async(state, condensed)

        except ContextLimitError:
            logger.warning(
                "Auto-Healing: Context limit reached. Attempting condensation + retry."
            )
            try:
                condensed = self.memory_manager.condense_history(state)
                return await self._execute_llm_step_async(state, condensed)
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

        except ModelProviderError:
            raise

        except Exception as e:
            logger.error("Critical Failure in Orchestrator.astep: %s", e, exc_info=True)
            raise AgentRuntimeError(f"Critical agent failure: {str(e)}") from e

    def _handle_pending_action_from_condensation(
        self, state: State, condensed: Any
    ) -> Action | None:
        """If condensed has pending_action, queue recovery and return it. Else None."""
        if not condensed.pending_action:
            return None
        task_text = ""
        try:
            initial_msg = self.memory_manager.get_initial_user_message(state.history)
            task_text = (getattr(initial_msg, "content", "") or "")[:200]
        except Exception:
            pass
        self._queue_post_condensation_recovery(task_text=task_text)
        return condensed.pending_action

    def _set_prompt_tier_from_recent_history(self, state: State) -> None:
        """Escalate to debug tier when recent errors or file ops exist."""
        try:
            from backend.events.observation import ErrorObservation
            from backend.events.action import FileEditAction, FileWriteAction
            recent = state.history[-12:] if len(state.history) > 12 else state.history
            tier = "debug" if (
                any(isinstance(e, ErrorObservation) for e in recent)
                or any(isinstance(e, (FileEditAction, FileWriteAction)) for e in recent)
            ) else "base"
            self.prompt_manager.set_prompt_tier(tier)
        except Exception:
            pass

    def _execute_llm_step(self, state: State, condensed: Any) -> Action:
        """Core logic to prepare messages, call LLM, and return the first action."""
        pending = self._handle_pending_action_from_condensation(state, condensed)
        if pending is not None:
            return pending

        initial_user_message = self.memory_manager.get_initial_user_message(
            state.history
        )
        self._set_prompt_tier_from_recent_history(state)

        messages = self.memory_manager.build_messages(
            condensed_history=condensed.events,
            initial_user_message=initial_user_message,
            llm_config=self.llm.config,
        )
        serialized_messages = self._serialize_messages(messages)
        params = self.planner.build_llm_params(serialized_messages, state, self.tools)
        self._sync_executor_llm()

        result = self.executor.execute(params, self.event_stream)

        try:
            if hasattr(state, "ack_planning_directive"):
                state.ack_planning_directive(source="Orchestrator")
            if hasattr(state, "ack_memory_pressure"):
                state.ack_memory_pressure(source="Orchestrator")
        finally:
            with contextlib.suppress(Exception):
                state.extra_data.pop("planning_directive", None)
                state.extra_data.pop("memory_pressure", None)

        self._last_llm_latency = result.execution_time

        actions = result.actions or []
        if not actions:
            return self._build_fallback_action(result)
        self._queue_additional_actions(actions[1:])
        return actions[0]

    async def _execute_llm_step_async(self, state: State, condensed: Any) -> Action:
        """Async variant of _execute_llm_step using real LLM streaming."""
        pending = self._handle_pending_action_from_condensation(state, condensed)
        if pending is not None:
            return pending

        initial_user_message = self.memory_manager.get_initial_user_message(
            state.history
        )
        self._set_prompt_tier_from_recent_history(state)

        messages = self.memory_manager.build_messages(
            condensed_history=condensed.events,
            initial_user_message=initial_user_message,
            llm_config=self.llm.config,
        )
        serialized_messages = self._serialize_messages(messages)
        params = self.planner.build_llm_params(serialized_messages, state, self.tools)
        self._sync_executor_llm()

        result = await self.executor.async_execute(params, self.event_stream)

        try:
            if hasattr(state, "ack_planning_directive"):
                state.ack_planning_directive(source="Orchestrator")
            if hasattr(state, "ack_memory_pressure"):
                state.ack_memory_pressure(source="Orchestrator")
        finally:
            with contextlib.suppress(Exception):
                state.extra_data.pop("planning_directive", None)
                state.extra_data.pop("memory_pressure", None)

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
        """Create a message action when the LLM returns no tool calls.

        This typically means the LLM returned pure-text (e.g. a final answer
        or a refusal). We surface it as a ``MessageAction`` so the controller
        can decide whether to continue or stop.
        """
        message_text = ""
        if result.response and getattr(result.response, "choices", None):
            first_choice = result.response.choices[0]
            message = getattr(first_choice, "message", None)
            if message is not None:
                message_text = getattr(message, "content", "") or ""

        if not message_text.strip():
            raise ModelProviderError("LLM returned an empty response with no tool calls")

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
        import os
        from backend.events.action.commands import CmdRunAction

        batch = self._collect_file_read_batch()
        if len(batch) < 2:
            return None

        for _ in batch:
            self.pending_actions.popleft()

        is_windows = os.name == "nt"
        parts = [_build_file_read_command(fr, is_windows) for fr in batch]
        sep = " ; " if is_windows else " && "
        return CmdRunAction(command=sep.join(parts), thought="Batched parallel file reads")

    def _collect_file_read_batch(self) -> list[FileReadAction]:
        """Collect leading run of FileReadAction from pending_actions."""
        batch: list[FileReadAction] = []
        for action in self.pending_actions:
            if isinstance(action, FileReadAction):
                batch.append(action)
            else:
                break
        return batch

    def _build_semantic_recall_block(self, task_text: str) -> str:
        """Build semantic recall block from task text. Returns empty on failure."""
        if not task_text:
            return ""
        recall_fn = orchestrator_function_calling.get_semantic_recall_fn()
        if not recall_fn:
            return ""
        try:
            results = recall_fn(task_text, 3)
            if not results:
                return ""
            parts = ["\n\n<SEMANTIC_RECALL_RECOVERY>"]
            for i, item in enumerate(results, 1):
                content = item.get("content_text", item.get("content", ""))
                parts.append(f"  [{i}] {content[:300]}")
            parts.append("</SEMANTIC_RECALL_RECOVERY>")
            return "\n".join(parts)
        except Exception:
            return ""

    def _build_lessons_block(self) -> str:
        """Load lessons.md content for recovery. Returns empty on failure."""
        try:
            import os as _os
            lessons_path = "/memories/repo/lessons.md"
            if not _os.path.exists(lessons_path):
                return ""
            with open(lessons_path, encoding="utf-8") as _f:
                content = _f.read(2000)
            return f"\n\n<LESSONS_MD_RECOVERY>\n{content}\n</LESSONS_MD_RECOVERY>" if content.strip() else ""
        except Exception:
            return ""

    def _build_task_tracker_block(self) -> str:
        """Build task tracker state block. Returns empty on failure."""
        try:
            from backend.engines.orchestrator.tools.task_tracker import TaskTracker
            tracker = TaskTracker()
            tasks = tracker.load_from_file()
            if not tasks:
                return ""
            status_icons = {"completed": "✓", "in_progress": "O", "failed": "X"}
            lines = ["<TASK_TRACKER_RECOVERY>"]
            for t in tasks:
                icon = status_icons.get(t.get("status", ""), "-")
                desc = t.get("description", t.get("title", ""))
                lines.append(f"  [{icon}] {t.get('id', '?')} — {desc} ({t.get('status', 'pending')})")
            lines.append("</TASK_TRACKER_RECOVERY>")
            return "\n\n" + "\n".join(lines)
        except Exception:
            return ""

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
        from backend.engines.orchestrator.tools.working_memory import get_full_working_memory

        restored = self._memory_manager_impl.get_restored_context()
        restored_block = f"\n\n{restored}" if restored else ""
        wm = get_full_working_memory()
        wm_block = f"\n\n{wm}" if wm else ""

        semantic_block = self._build_semantic_recall_block(task_text)
        lessons_block = self._build_lessons_block()
        task_tracker_block = self._build_task_tracker_block()

        recovery_think = AgentThinkAction(
            thought=(
                "⚡ CONTEXT CONDENSED — mandatory recovery sequence complete (system-enforced). "
                "The following context has been automatically restored:"
                f"{restored_block}{wm_block}{semantic_block}{lessons_block}{task_tracker_block}"
            )
        )
        self.pending_actions.append(recovery_think)
        self.pending_actions.append(build_recall_action("all"))

    def _maybe_inject_reflection(self, state: State | None = None) -> Action | None:
        """Inject a structured self-reflection think action every N steps.

        Provides concrete session metrics: turn progress, token usage,
        files modified, error count, and original user request.

        Returns an AgentThinkAction if the interval has elapsed, else None.
        """
        if self._reflection_interval <= 0 or self._steps_since_reflection < self._reflection_interval:
            return None

        self._steps_since_reflection = 0
        data_parts = self._build_reflection_data_parts(state) if state else []
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

    def _build_reflection_data_parts(self, state: State) -> list[str]:
        """Build structured reflection data parts from state."""
        parts: list[str] = []

        progress = _format_reflection_progress(state)
        if progress:
            parts.append(progress)

        metrics_parts = _format_reflection_metrics(state)
        parts.extend(metrics_parts)

        files_part = _format_reflection_modified_files(
            list(self.anti_hallucination._file_modified_turns.keys())
        )
        if files_part:
            parts.append(files_part)

        error_count = self._count_recent_errors(state)
        if error_count:
            parts.append(f"  • Errors encountered: {error_count}")

        request_part = _format_reflection_initial_request(
            self.memory_manager, state.history
        )
        if request_part:
            parts.append(request_part)

        return parts

    def _count_recent_errors(self, state: State) -> int:
        """Count ErrorObservations in recent history, capped at 20."""
        count = 0
        for event in reversed(list(getattr(state, "history", []))):
            if type(event).__name__ == "ErrorObservation":
                count += 1
                if count >= 20:
                    break
        return count

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
        return orchestrator_function_calling.response_to_actions(
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
