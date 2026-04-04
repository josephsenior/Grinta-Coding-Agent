from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.logger import app_logger as logger

if TYPE_CHECKING:
    from backend.orchestration.services.orchestration_context import (
        OrchestrationContext,
    )
    from backend.orchestration.tool_pipeline import ToolInvocationContext


class IterationService:
    """Handles iteration limit adjustments and related helpers."""

    def __init__(self, context: OrchestrationContext) -> None:
        self._context = context

    async def apply_dynamic_iterations(self, ctx: ToolInvocationContext) -> None:
        """Adjust max iterations dynamically based on inferred complexity."""
        agent = self._context.agent
        config = self._context.agent_config
        state = self._context.state

        if not self._should_apply_iterations(agent, config, state):
            return

        iteration_flag = self._get_iteration_flag(state)
        if iteration_flag is None:
            return

        complexity = ctx.metadata.get('task_complexity')
        if complexity is None:
            return

        target_iterations = self._determine_target_iterations(
            agent, config, complexity, state
        )
        self._apply_iteration_flag(
            iteration_flag, config, complexity, target_iterations
        )

    def _should_apply_iterations(self, agent, config, state) -> bool:
        if agent is None or config is None or state is None:
            return False
        return bool(getattr(config, 'enable_dynamic_iterations', False))

    def _get_iteration_flag(self, state):
        iteration_flag = getattr(state, 'iteration_flag', None)
        if iteration_flag is None or not hasattr(iteration_flag, 'max_value'):
            return None
        return iteration_flag

    def _determine_target_iterations(
        self, agent, config, complexity: float, state
    ) -> int:
        estimate = self._estimate_iterations_from_analyzer(agent, complexity, state)
        if estimate is not None:
            return estimate
        return self._fallback_iteration_target(config, complexity)

    def _estimate_iterations_from_analyzer(
        self, agent, complexity, state
    ) -> int | None:
        analyzer = getattr(agent, 'task_complexity_analyzer', None)
        if not analyzer or not hasattr(analyzer, 'estimate_iterations'):
            return None
        try:
            estimated = analyzer.estimate_iterations(complexity, state)
            return int(estimated)
        except Exception as exc:  # pragma: no cover - diagnostic logging
            logger.debug('Dynamic iteration estimation failed: %s', exc, exc_info=True)
            return None

    def _fallback_iteration_target(self, config, complexity: float) -> int:
        base = getattr(config, 'min_iterations', 20)
        multiplier = getattr(config, 'complexity_iteration_multiplier', 50.0)
        return int(float(base) + float(complexity) * float(multiplier))

    def _apply_iteration_flag(self, iteration_flag, config, complexity, target) -> None:
        min_iterations = int(getattr(config, 'min_iterations', 0))
        bounded_target = max(min_iterations, target)
        max_override = getattr(config, 'max_iterations_override', None)
        if max_override is not None:
            bounded_target = min(bounded_target, int(max_override))

        current_max = getattr(iteration_flag, 'max_value', min_iterations)
        new_max = max(min_iterations, bounded_target)
        # Use centralized mutation path when the flag lives on a State object
        state = getattr(self._context, 'state', None)
        if (
            state is not None
            and getattr(state, 'iteration_flag', None) is iteration_flag
        ):
            state.adjust_iteration_limit(new_max, source='IterationService')
        else:
            iteration_flag.max_value = new_max
        logger.debug(
            'Dynamic iterations updated from %s to %s (complexity=%.2f)',
            current_max,
            new_max,
            complexity,
        )
