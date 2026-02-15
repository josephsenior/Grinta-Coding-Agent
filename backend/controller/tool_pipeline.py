from __future__ import annotations

import inspect
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from backend.controller.tool_telemetry import ToolTelemetry
from backend.core.constants import LOG_ALL_EVENTS
from backend.core.logger import FORGE_logger as logger

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

    async def plan(self, ctx: ToolInvocationContext) -> None:
        """Analyze task complexity and trigger planning if needed."""
        if not ctx.action.runnable:
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

            logger.info(
                "📋 Planning middleware: Task complexity %.1f - "
                "agent should use task tracker for decomposition",
                complexity,
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
        if not config or not getattr(config, "enable_reflection", True):
            return

        # For file edits, verify syntax and logic
        if hasattr(ctx.action, "action") and ctx.action.action in ("edit", "write"):
            await self._verify_file_action(ctx, agent)

        # For commands, verify safety
        if hasattr(ctx.action, "action") and ctx.action.action == "run":
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
                logger.warning(
                    "⚠️ Reflection: Potentially destructive command detected: %s",
                    command,
                )
                # Don't block, but log warning (safety validator should handle this)

        logger.debug("✅ Reflection: Command action verified: %s", command)


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
