from __future__ import annotations

import inspect
import os
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from backend.controller.tool_telemetry import ToolTelemetry
from backend.core.constants import LOG_ALL_EVENTS
from backend.core.logger import forge_logger as logger

if TYPE_CHECKING:
    from backend.controller.agent_controller import AgentController
    from backend.controller.state.state import State
    from backend.events.action import Action
    from backend.events.observation import Observation


@dataclass
class ToolInvocationContext:
    """Context shared across middleware stages during a tool invocation."""

    controller: AgentController
    action: Action
    state: State
    metadata: dict[str, Any] = field(default_factory=dict)
    blocked: bool = False
    block_reason: str | None = None
    action_id: int | None = None

    def block(self, reason: str | None = None) -> None:
        """Mark the invocation as blocked to stop subsequent stages."""
        self.blocked = True
        if reason:
            self.block_reason = reason


class ToolInvocationMiddleware:
    """Base middleware with optional lifecycle hooks."""

    async def plan(
        self, ctx: ToolInvocationContext
    ) -> None:  # pragma: no cover - default no-op
        return None

    async def verify(
        self, ctx: ToolInvocationContext
    ) -> None:  # pragma: no cover - default no-op
        return None

    async def execute(
        self, ctx: ToolInvocationContext
    ) -> None:  # pragma: no cover - default no-op
        return None

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:  # pragma: no cover - default no-op
        return None


class ToolInvocationPipeline:
    """Runs middleware stages (plan → verify → execute → observe) for tool calls."""

    def __init__(
        self,
        controller: AgentController,
        middlewares: Iterable[ToolInvocationMiddleware],
    ) -> None:
        self.controller = controller
        self.middlewares = list(middlewares)

    def create_context(self, action: Action, state: State) -> ToolInvocationContext:
        """Create a new invocation context for the given action."""
        return ToolInvocationContext(
            controller=self.controller,
            action=action,
            state=state,
        )

    async def run_plan(self, ctx: ToolInvocationContext) -> None:
        await self._run_stage("plan", ctx)

    async def run_verify(self, ctx: ToolInvocationContext) -> None:
        if ctx.blocked:
            return
        await self._run_stage("verify", ctx)

    async def run_execute(self, ctx: ToolInvocationContext) -> None:
        if ctx.blocked:
            return
        await self._run_stage("execute", ctx)

    async def run_observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        ctx.metadata["observation"] = observation
        await self._run_stage("observe", ctx, observation=observation)

    async def _run_stage(
        self,
        stage: str,
        ctx: ToolInvocationContext,
        **kwargs: Any,
    ) -> None:
        handler_name = stage
        for middleware in self.middlewares:
            if ctx.blocked:
                break
            handler = getattr(middleware, handler_name, None)
            if handler is None:
                continue
            try:
                result = handler(ctx, **kwargs) if kwargs else handler(ctx)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception(
                    "Tool middleware %s failed during stage %s: %s",
                    middleware.__class__.__name__,
                    stage,
                    exc,
                )
                ctx.block(reason=f"{middleware.__class__.__name__}:{stage}_error")
                break


class SafetyValidatorMiddleware(ToolInvocationMiddleware):
    """Runs the optional safety validator during the verify stage."""

    def __init__(self, controller: AgentController) -> None:
        self.controller = controller

    async def verify(self, ctx: ToolInvocationContext) -> None:
        if not ctx.action.runnable:
            return
        validator = getattr(self.controller, "safety_validator", None)
        if not validator:
            return

        from backend.controller.safety_validator import ExecutionContext
        from backend.events.event import EventSource
        from backend.events.observation import ErrorObservation

        context = ExecutionContext(
            session_id=self.controller.id or "",
            iteration=self.controller.state.iteration_flag.current_value,
            agent_state=self.controller.state.agent_state.value,
            recent_errors=[self.controller.state.last_error]
            if self.controller.state.last_error
            else [],
            is_autonomous=bool(
                getattr(self.controller.autonomy_controller, "autonomy_level", "")
                == "full"
            ),
        )

        validation = await validator.validate(ctx.action, context)
        # Store audit_id so downstream middleware can update the entry
        if validation.audit_id:
            ctx.metadata["audit_id"] = validation.audit_id
        if validation.allowed:
            return

        # Block execution and notify stream.
        ctx.block("safety_validator_blocked")
        ctx.metadata["handled"] = True
        error_obs = ErrorObservation(
            content=f"ACTION BLOCKED FOR SAFETY:\n{validation.blocked_reason}",
            error_id="SAFETY_VALIDATOR_BLOCKED",
        )
        error_obs.cause = getattr(ctx.action, "id", None)
        self.controller.event_stream.add_event(error_obs, EventSource.ENVIRONMENT)
        self.controller._pending_action = None


class CircuitBreakerMiddleware(ToolInvocationMiddleware):
    """Records circuit breaker telemetry across execute/observe stages."""

    def __init__(self, controller: AgentController) -> None:
        self.controller = controller

    async def execute(self, ctx: ToolInvocationContext) -> None:
        service = getattr(self.controller, "circuit_breaker_service", None)
        security_risk = getattr(ctx.action, "security_risk", None)
        if service:
            service.record_high_risk_action(security_risk)
            return
        circuit_breaker = getattr(self.controller, "circuit_breaker", None)
        if circuit_breaker and security_risk is not None:
            circuit_breaker.record_high_risk_action(security_risk)

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        service = getattr(self.controller, "circuit_breaker_service", None)
        if service and observation is not None:
            from backend.events.observation import ErrorObservation

            if isinstance(observation, ErrorObservation):
                service.record_error(RuntimeError(observation.content))
            else:
                service.record_success()
            return
        circuit_breaker = getattr(self.controller, "circuit_breaker", None)
        if not circuit_breaker or observation is None:
            return
        from backend.events.observation import ErrorObservation

        if isinstance(observation, ErrorObservation):
            circuit_breaker.record_error(RuntimeError(observation.content))
        else:
            circuit_breaker.record_success()


class CostQuotaMiddleware(ToolInvocationMiddleware):
    """Records LLM spend deltas to the quota middleware."""

    def __init__(self, controller: AgentController) -> None:
        self.controller = controller

    async def plan(self, ctx: ToolInvocationContext) -> None:
        llm = getattr(self.controller.agent, "llm", None)
        metrics = getattr(llm, "metrics", None)
        if metrics is None:
            return
        ctx.metadata["cost_snapshot"] = metrics.accumulated_cost

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        llm = getattr(self.controller.agent, "llm", None)
        metrics = getattr(llm, "metrics", None)
        snapshot = ctx.metadata.get("cost_snapshot")
        if metrics is None or snapshot is None:
            return

        delta = metrics.accumulated_cost - snapshot
        if delta <= 0:
            return

        user_key = ctx.metadata.get("quota_user_key")
        if not user_key:
            user_key = (
                f"user:{self.controller.user_id}"
                if self.controller.user_id
                else f"session:{self.controller.id}"
            )
            ctx.metadata["quota_user_key"] = user_key

        try:
            from backend.telemetry.cost_recording import record_llm_cost
        except ImportError:  # pragma: no cover - quota optional
            return

        try:
            record_llm_cost(user_key, delta)
        except Exception as exc:  # pragma: no cover - defensive
            self.controller.log(
                "warning",
                f"Failed to record LLM cost delta for {user_key}: {exc}",
                extra={"msg_type": "PIPELINE_COST"},
            )
        finally:
            ctx.metadata["cost_snapshot"] = metrics.accumulated_cost

        # Annotate the observation so the LLM can see its per-action cost
        # inline. Skipped for micro-costs (<$0.0001) to avoid noise.
        if observation is not None and delta >= 0.0001:
            self._annotate_cost(observation, delta, metrics)

    @staticmethod
    def _annotate_cost(
        observation: Observation, delta: float, metrics: Any
    ) -> None:
        """Append a compact cost footprint tag to the observation content."""
        content = getattr(observation, "content", None)
        if not isinstance(content, str):
            return
        total = metrics.accumulated_cost
        max_budget = getattr(metrics, "max_budget_per_task", None)
        if max_budget and max_budget > 0:
            remaining = max_budget - total
            budget_part = f"  |  budget_remaining: ${remaining:.4f}"
        else:
            budget_part = ""
        annotation = (
            f"\n<COST_FOOTPRINT>"
            f"step: ${delta:.4f}  |  session: ${total:.4f}{budget_part}"
            f"</COST_FOOTPRINT>"
        )
        setattr(observation, "content", content + annotation)


class ContextWindowMiddleware(ToolInvocationMiddleware):
    """Emits proactive context-window utilization warnings at 70 % and 90 %.

    Mirrors the cost-threshold pattern used by ``BudgetGuardService`` but
    tracks token utilisation instead of dollar spend.  Fires at most once
    per threshold per session to avoid alert fatigue.

    Why this matters: without proactive warnings the LLM only learns the
    context window is full *after* the API returns an error — at which point
    Forge must trigger emergency condensation.  This middleware gives the LLM
    a chance to call ``request_condensation()`` voluntarily before overflow.
    """

    _THRESHOLDS: tuple[float, ...] = (0.70, 0.90)

    def __init__(self, controller: AgentController) -> None:
        self.controller = controller
        self._alerted_thresholds: set[float] = set()

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        llm = getattr(self.controller.agent, "llm", None)
        metrics = getattr(llm, "metrics", None)
        if metrics is None:
            return
        token_usages = getattr(metrics, "token_usages", [])
        if not token_usages:
            return
        last = token_usages[-1]
        context_window = getattr(last, "context_window", 0)
        if context_window <= 0:
            return
        prompt_tokens = getattr(last, "prompt_tokens", 0)
        pct = prompt_tokens / context_window
        for threshold in self._THRESHOLDS:
            if pct >= threshold and threshold not in self._alerted_thresholds:
                self._alerted_thresholds.add(threshold)
                self._emit_alert(threshold, prompt_tokens, context_window, pct)

    def _emit_alert(
        self,
        threshold: float,
        prompt_tokens: int,
        context_window: int,
        pct: float,
    ) -> None:
        pct_int = int(threshold * 100)
        content = (
            f"⚠️ Context window {pct_int}% full: "
            f"{prompt_tokens:,}/{context_window:,} tokens used. "
            "Call request_condensation() to free context space before overflow."
        )
        logger.warning(
            "Context window threshold %d%% crossed for session %s — %d/%d tokens",
            pct_int,
            self.controller.id,
            prompt_tokens,
            context_window,
            extra={"session_id": self.controller.id},
        )
        try:
            from backend.events.event import EventSource
            from backend.events.observation.status import StatusObservation

            obs = StatusObservation(
                content=content,
                status_type="context_window_alert",
                extras={
                    "threshold": threshold,
                    "pct_used": round(pct, 4),
                    "prompt_tokens": prompt_tokens,
                    "context_window": context_window,
                },
            )
            self.controller.event_stream.add_event(obs, EventSource.ENVIRONMENT)
        except Exception:
            logger.debug(
                "Failed to emit context window alert for session %s",
                self.controller.id,
                exc_info=True,
            )


class LoggingMiddleware(ToolInvocationMiddleware):
    """Emits structured logs for each pipeline stage."""

    def __init__(self, controller: AgentController) -> None:
        self.controller = controller

    async def plan(self, ctx: ToolInvocationContext) -> None:
        self.controller.log(
            "debug",
            f"[PLAN] {type(ctx.action).__name__}",
            extra={"msg_type": "PIPELINE_PLAN"},
        )

    async def execute(self, ctx: ToolInvocationContext) -> None:
        self.controller.log(
            "debug",
            f"[EXECUTE] {type(ctx.action).__name__}",
            extra={"msg_type": "PIPELINE_EXECUTE"},
        )

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        if observation is None:
            return
        log_level = "info" if LOG_ALL_EVENTS else "debug"
        self.controller.log(
            log_level,
            f"[OBSERVE] {observation}",
            extra={"msg_type": "PIPELINE_OBSERVE"},
        )


class PlanningMiddleware(ToolInvocationMiddleware):
    """Automatically decomposes complex tasks before execution."""

    def __init__(self, controller: AgentController) -> None:
        self.controller = controller
        self._planning_injected = False

    async def plan(self, ctx: ToolInvocationContext) -> None:
        """Analyze task complexity and trigger planning if needed."""
        if not ctx.action.runnable:
            return

        # Only inject planning once per session
        if self._planning_injected:
            return

        agent = getattr(self.controller, "agent", None)
        if not agent or not hasattr(agent, "task_complexity_analyzer"):
            return

        # Get the initial user message
        state = ctx.state
        initial_message = self._get_initial_user_message(state)
        if not initial_message:
            return

        # Check if task should be planned
        analyzer = agent.task_complexity_analyzer
        should_plan = analyzer.should_plan(initial_message, state)

        if should_plan:
            # Store complexity score for iteration management
            complexity = analyzer.analyze_complexity(initial_message, state)
            ctx.metadata["task_complexity"] = complexity
            ctx.metadata["should_plan"] = True
            self._planning_injected = True

            logger.info(
                "📋 Planning middleware: Task complexity %.1f - "
                "injecting planning directive",
                complexity,
            )

            # Adapt circuit breaker thresholds for complex tasks
            cb_service = getattr(self.controller, "circuit_breaker_service", None)
            max_iter = getattr(state.iteration_flag, "max_value", 500) or 500
            if cb_service:
                cb_service.adapt(complexity, max_iter)

            # Inject a planning directive into state extra_data so the
            # orchestrator's next turn sees an instruction to plan first
            state.set_planning_directive(
                (
                    f"[AUTO-PLAN] Task complexity={complexity:.1f}. "
                    "Before executing any tool calls, use think() to create "
                    "a step-by-step plan, then use task_tracker(command='plan') "
                    "to register your plan. Only then begin execution."
                ),
                source="PlanningMiddleware",
            )

    def _get_initial_user_message(self, state: State) -> str:
        """Get the initial user message from state history."""
        if not state or not hasattr(state, "history"):
            return ""

        for event in state.history:
            if hasattr(event, "source") and hasattr(event, "content"):
                from backend.events.event import EventSource

                if event.source == EventSource.USER:
                    return event.content
        return ""


class ReflectionMiddleware(ToolInvocationMiddleware):
    """Enables self-reflection before executing actions."""

    def __init__(self, controller: AgentController) -> None:
        self.controller = controller

    async def verify(self, ctx: ToolInvocationContext) -> None:
        """Verify action correctness before execution."""
        if not ctx.action.runnable:
            return

        agent = getattr(self.controller, "agent", None)
        if not agent:
            return

        config = getattr(agent, "config", None)
        if not self._is_reflection_enabled(config):
            return

        from backend.events.action import FileEditAction, FileWriteAction, CmdRunAction

        # For file edits, verify syntax and logic
        if isinstance(ctx.action, (FileEditAction, FileWriteAction)):
            await self._verify_file_action(ctx, agent)

        # For commands, verify safety
        if isinstance(ctx.action, CmdRunAction):
            await self._verify_command_action(ctx, agent)

    async def _verify_file_action(self, ctx: ToolInvocationContext, agent) -> None:
        """Verify file edit action before execution."""
        action = ctx.action
        if not hasattr(action, "path") or not hasattr(action, "content"):
            return

        # Basic verification: check for common errors
        content = getattr(action, "content", "")
        if not content:
            return

        # Check for syntax errors in common file types
        path = getattr(action, "path", "")
        if path.endswith((".py", ".js", ".ts", ".json")):
            # Basic validation - could be extended with actual parsers
            if path.endswith(".json") and content:
                try:
                    import json

                    json.loads(content)
                except json.JSONDecodeError:
                    logger.warning(
                        "⚠️ Reflection: Potential JSON syntax error in %s", path
                    )
                    # Don't block, but log warning

        logger.debug("✅ Reflection: File action verified for %s", path)

    async def _verify_command_action(self, ctx: ToolInvocationContext, agent) -> None:
        """Verify command action before execution."""
        action = ctx.action
        if not hasattr(action, "command"):
            return

        command = getattr(action, "command", "")
        if not command:
            return

        # Check for destructive operations
        destructive_patterns = [
            r"\brm\s+-rf\s+/",
            r"\bdd\s+if=",
            r"\bmkfs\s+",
            r"\bformat\s+",
            r">\s+/dev/",
        ]

        import re

        for pattern in destructive_patterns:
            if re.search(pattern, command):
                from backend.events.event import EventSource
                from backend.events.observation import ErrorObservation

                logger.warning(
                    "Reflection blocked destructive command: %s",
                    command,
                )
                ctx.block("reflection_blocked_destructive_command")
                ctx.metadata["handled"] = True
                error_obs = ErrorObservation(
                    content=(
                        "ACTION BLOCKED: Reflection middleware detected a potentially destructive command.\n"
                        f"Command: {command}"
                    ),
                    error_id="REFLECTION_BLOCKED_DESTRUCTIVE_COMMAND",
                )
                error_obs.cause = getattr(ctx.action, "id", None)
                self.controller.event_stream.add_event(error_obs, EventSource.ENVIRONMENT)
                self.controller._pending_action = None
                return

        logger.debug("✅ Reflection: Command action verified: %s", command)

    @staticmethod
    def _is_reflection_enabled(config: Any) -> bool:
        if not config:
            return False
        return bool(
            getattr(config, "enable_reflection", True)
            and getattr(config, "enable_reflection_middleware", False)
        )


class TelemetryMiddleware(ToolInvocationMiddleware):
    """Emit telemetry events for tool invocations."""

    def __init__(self, controller: AgentController) -> None:
        self.controller = controller
        self.telemetry = ToolTelemetry.get_instance()

    async def plan(self, ctx: ToolInvocationContext) -> None:
        self.telemetry.on_plan(ctx)

    async def execute(self, ctx: ToolInvocationContext) -> None:
        if ctx.blocked:
            return
        self.telemetry.on_execute(ctx)

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        self.telemetry.on_observe(ctx, observation)


class ErrorPatternMiddleware(ToolInvocationMiddleware):
    """Auto-queries the error_patterns DB when an ErrorObservation arrives.

    Eliminates the need for the LLM to remember to call error_patterns(query)
    every time it hits an error.  If a known fix exists, it is appended
    directly to the observation so the LLM sees it on the next turn.
    """

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        if observation is None:
            return
        from backend.events.observation import ErrorObservation

        if not isinstance(observation, ErrorObservation):
            return

        content = getattr(observation, "content", "") or ""
        if not content:
            return

        try:
            from backend.engines.orchestrator.tools.error_patterns import _query_patterns

            result_action = _query_patterns(content)
            result_text = getattr(result_action, "thought", "")
            # Only append if a known pattern was found
            if "No known patterns" not in result_text and result_text:
                observation.content = (
                    content
                    + "\n\n<KNOWN_FIX>"
                    + "\n" + result_text
                    + "\n</KNOWN_FIX>"
                )
        except Exception:
            pass  # Non-critical — never let this break error handling


class ConflictDetectionMiddleware(ToolInvocationMiddleware):
    """Warns when the agent re-edits a file without verifying it first.

    Tracks which files have been edited and read in the current session.
    When the agent edits a file that was already edited without a subsequent
    read/view, a warning is prepended to the observation reminding the LLM
    to verify its mental model before making further edits.
    """

    def __init__(self) -> None:
        # {path: edit_count_since_last_view}
        self._unverified_edits: dict[str, int] = {}

    async def verify(self, ctx: ToolInvocationContext) -> None:
        """Block repeated edits without any read/verify in between."""
        from backend.events.action import FileEditAction, FileWriteAction
        from backend.events.event import EventSource
        from backend.events.observation import ErrorObservation

        action = ctx.action
        if not isinstance(action, (FileEditAction, FileWriteAction)):
            return

        command = getattr(action, "command", None)
        if command == "view":
            return

        path = getattr(action, "path", None)
        if not path:
            return

        threshold = int(os.getenv("FORGE_CONFLICT_BLOCK_THRESHOLD", "2"))
        prev_count = self._unverified_edits.get(path, 0)
        if prev_count < threshold:
            return

        ctx.block("conflict_detection_repeated_unverified_edits")
        ctx.metadata["handled"] = True
        error_obs = ErrorObservation(
            content=(
                "ACTION BLOCKED: Repeated edits without verification were detected.\n"
                f"File: {path}\n"
                f"Unverified edit streak: {prev_count}\n"
                "Read/verify the file state before applying more edits."
            ),
            error_id="CONFLICT_DETECTION_BLOCKED",
        )
        error_obs.cause = getattr(ctx.action, "id", None)
        ctx.controller.event_stream.add_event(error_obs, EventSource.ENVIRONMENT)
        ctx.controller._pending_action = None

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        from backend.events.action import FileEditAction, FileReadAction, FileWriteAction
        from backend.events.observation import ErrorObservation

        action = ctx.action

        # Track reads — reset unverified count for the file
        if isinstance(action, FileReadAction):
            path = getattr(action, "path", None)
            if path:
                self._unverified_edits.pop(path, None)
            return

        if not isinstance(action, (FileEditAction, FileWriteAction)):
            return

        # Skip view commands (they don't modify files)
        command = getattr(action, "command", None)
        if command == "view":
            return

        path = getattr(action, "path", None)
        if not path:
            return

        prev_count = self._unverified_edits.get(path, 0)
        self._unverified_edits[path] = prev_count + 1

        if observation is None:
            return

        # Only warn after first repeat edit without a verified read in between
        if prev_count >= 1 and not isinstance(observation, ErrorObservation):
            content = getattr(observation, "content", "") or ""
            observation.content = (
                f"<CONFLICT_WARNING>\n"
                f"You have edited '{path}' {prev_count + 1} times without reading it back.\n"
                "Use verify_state or str_replace_editor(view) to confirm the current "
                "file state before making further edits.\n"
                "</CONFLICT_WARNING>\n\n"
                + content
            )


class EditVerifyMiddleware(ToolInvocationMiddleware):
    """Appends a verify-after-edit hint to file edit observations.

    After a FileEditAction or FileWriteAction completes, this middleware
    appends a short reminder telling the LLM to read the affected lines
    to confirm the edit was applied correctly.  This prevents silent
    drift where the agent assumes an edit succeeded without checking.

    Selective: ``str_replace`` and ``insert`` commands already include a
    diff-style snippet in their observation, so the hint is skipped for
    those — requesting a redundant ``cat`` wastes a turn.
    """

    # Commands whose observations already contain enough verification context.
    _SELF_VERIFYING_COMMANDS = frozenset({"str_replace", "insert", "undo_edit"})

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        if observation is None:
            return
        from backend.events.action import FileEditAction, FileWriteAction

        action = ctx.action
        if not isinstance(action, (FileEditAction, FileWriteAction)):
            return

        content = getattr(observation, "content", None)
        if content is None or not isinstance(content, str):
            return

        # Only add hint for successful edits (no error markers)
        from backend.events.observation import ErrorObservation
        if isinstance(observation, ErrorObservation):
            return

        # Skip hint for commands that already show diff/context in output.
        command = getattr(action, "command", None)
        if command in self._SELF_VERIFYING_COMMANDS:
            return

        path = getattr(action, "path", "unknown")
        observation.content = (
            content
            + "\n\n<VERIFY_HINT>"
            + f"\nFile {path} was modified. Consider reading the affected "
            + "lines to confirm the edit was applied correctly before "
            + "moving on."
            + "\n</VERIFY_HINT>"
        )


def _get_syntax_check_cmd(path: str) -> list[str] | None:
    """Return syntax check command for path, or None if unsupported."""
    _, ext = os.path.splitext(path)
    ext = ext.lower()
    if ext == ".py":
        return ["python", "-m", "py_compile", path]
    if ext in (".js", ".ts"):
        return ["node", "--check", path]
    return None


def _append_syntax_check_result(
    observation: Observation,
    result: subprocess.CompletedProcess[Any] | None,
    exc: BaseException | None,
) -> None:
    """Append syntax check result to observation content."""
    current = getattr(observation, "content", "") or ""
    if exc is not None:
        observation.content = current + (
            f"\n<SYNTAX_CHECK_FAILED>\nMiddleware execution error: {exc}\n</SYNTAX_CHECK_FAILED>"
        )
    elif result is not None and result.returncode != 0:
        stderr = (result.stderr or "").strip() or (result.stdout or "").strip()
        observation.content = current + f"\n<SYNTAX_CHECK_FAILED>\n{stderr}\n</SYNTAX_CHECK_FAILED>"
    else:
        observation.content = current + "\n<SYNTAX_CHECK_PASSED />"


class AutoCheckMiddleware(ToolInvocationMiddleware):
    """Automatically checks syntax of files after editing."""

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        if observation is None:
            return
        from backend.events.action import FileEditAction, FileWriteAction
        from backend.events.observation import ErrorObservation

        if isinstance(observation, ErrorObservation):
            return
        if not isinstance(ctx.action, (FileEditAction, FileWriteAction)):
            return
        path = getattr(ctx.action, "path", None)
        if not path:
            return
        cmd = _get_syntax_check_cmd(path)
        if not cmd:
            return

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            _append_syntax_check_result(observation, result, None)
        except Exception as e:
            _append_syntax_check_result(observation, None, e)
