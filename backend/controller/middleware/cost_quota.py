"""Cost quota middleware for tool invocations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.controller.tool_pipeline import ToolInvocationMiddleware

if TYPE_CHECKING:
    from backend.controller.agent_controller import AgentController
    from backend.controller.tool_pipeline import ToolInvocationContext
    from backend.events.observation import Observation


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
