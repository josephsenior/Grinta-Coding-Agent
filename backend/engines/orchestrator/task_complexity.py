"""Task complexity analysis for automatic planning and iteration management."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from backend.core.logger import FORGE_logger as logger

if TYPE_CHECKING:
    from backend.controller.state.state import State


class TaskComplexityAnalyzer:
    """Analyzes task complexity to determine planning and iteration needs."""

    # Patterns that indicate complex tasks
    COMPLEX_TASK_PATTERNS = [
        r"\b(and|plus|also|additionally|furthermore|moreover|in addition)\b",
        r"\b(multiple|several|many|various|different)\b",
        r"\b(create|build|implement|develop|set up|configure).*(and|with|plus)\b",
        r"\b(all|every|entire|whole|complete|full)\b",
        r"\b(refactor|restructure|reorganize|redesign)\b",
        r"\b(test|verify|validate|check).*(and|plus|also)\b",
        r"\b(integration|integration test|end-to-end|e2e)\b",
        r"\b(multi-step|step by step|phased|in phases)\b",
    ]

    # Patterns that indicate simple tasks
    SIMPLE_TASK_PATTERNS = [
        r"^(add|update|fix|change|modify|edit|delete|remove)\s+(a|an|the)\s+\w+\s+(to|in|from|on)\s+",
        r"^(what|how|why|where|when|explain|describe|tell me)\s+",
        r"^(show|display|print|list|get|fetch|retrieve)\s+",
        r"^add\s+(a|an)\s+\w+\s+(comment|docstring|line|function|class)\b",
        r"^fix\s+(a|an)\s+\w+\s+(typo|error|bug|issue)\b",
    ]

    # Action words that indicate distinct requirements
    ACTION_WORDS = [
        "create",
        "build",
        "implement",
        "develop",
        "add",
        "update",
        "fix",
        "modify",
        "edit",
        "delete",
        "remove",
        "refactor",
        "test",
        "verify",
        "validate",
        "check",
        "deploy",
        "configure",
        "set up",
        "install",
        "integrate",
        "connect",
        "write",
        "read",
        "run",
        "execute",
    ]

    def __init__(self, config) -> None:
        """Initialize the task complexity analyzer.

        Args:
            config: Agent configuration
        """
        self._config = config
        self._threshold = getattr(config, "planning_complexity_threshold", 3)

    def analyze_complexity(self, user_message: str, state: State) -> float:
        """Analyze task complexity and return a score (1.0-10.0).

        Args:
            user_message: The user's message/request
            state: Current agent state

        Returns:
            Complexity score from 1.0 (simple) to 10.0 (complex)
        """
        if not user_message:
            return 1.0

        message_lower = user_message.lower()
        if self._is_simple_task(message_lower):
            return 1.5

        score = 1.0
        score += self._action_word_score(message_lower)
        score += self._complex_pattern_score(message_lower)
        score += self._conjunction_score(message_lower)
        score += self._file_mention_score(message_lower)
        score += self._history_complexity_score(state)
        return min(score, 10.0)

    def _is_simple_task(self, message_lower: str) -> bool:
        return any(
            re.search(pattern, message_lower) for pattern in self.SIMPLE_TASK_PATTERNS
        )

    def _action_word_score(self, message_lower: str) -> float:
        action_count = sum(
            1
            for action_word in self.ACTION_WORDS
            if re.search(rf"\b{action_word}\b", message_lower)
        )
        return min(action_count * 0.5, 3.0)

    def _complex_pattern_score(self, message_lower: str) -> float:
        complex_patterns = sum(
            1
            for pattern in self.COMPLEX_TASK_PATTERNS
            if re.search(pattern, message_lower)
        )
        return min(complex_patterns * 0.8, 4.0)

    def _conjunction_score(self, message_lower: str) -> float:
        conjunctions = len(
            re.findall(r"\b(and|plus|also|additionally|with)\b", message_lower)
        )
        return min(conjunctions * 0.6, 3.0)

    def _file_mention_score(self, message_lower: str) -> float:
        file_mentions = len(
            re.findall(r"\b(file|files|file\.|\.py|\.js|\.ts|\.json)\b", message_lower)
        )
        return min(file_mentions * 0.3, 2.0)

    def _history_complexity_score(self, state: State | None) -> float:
        if not state or not hasattr(state, "history"):
            return 0.0
        recent_actions = [
            event for event in state.history[-10:] if hasattr(event, "action")
        ]
        file_edit_count = sum(
            1
            for event in recent_actions
            if getattr(event, "action", None) in ("edit", "write", "create")
        )
        return min(file_edit_count * 0.2, 1.5)

    def should_plan(self, user_message: str, state: State) -> bool:
        """Determine if task should be planned (decomposed).

        Args:
            user_message: The user's message/request
            state: Current agent state

        Returns:
            True if task should be planned, False otherwise
        """
        if not getattr(self._config, "enable_auto_planning", True):
            return False

        complexity = self.analyze_complexity(user_message, state)
        threshold = float(self._threshold)

        if complexity >= threshold:
            logger.info(
                "📋 Task complexity %.1f >= %s - triggering automatic planning",
                complexity,
                threshold,
            )
            return True
        else:
            logger.debug(
                "Task complexity %.1f < %s - skipping planning", complexity, threshold
            )
            return False

    def estimate_iterations(self, complexity: float, state: State) -> int:
        """Estimate required iterations based on complexity.

        Args:
            complexity: Task complexity score (1.0-10.0)
            state: Current agent state

        Returns:
            Estimated number of iterations needed
        """
        if not getattr(self._config, "enable_dynamic_iterations", True):
            # Fall back to default max_iterations
            return getattr(self._config, "max_iterations_override", None) or 500

        min_iter = getattr(self._config, "min_iterations", 20)
        max_iter = getattr(self._config, "max_iterations_override", None) or 500
        multiplier = getattr(self._config, "complexity_iteration_multiplier", 50.0)

        # Calculate iterations: base + (complexity * multiplier)
        # Simple tasks: min_iter (20)
        # Complex tasks: min_iter + (complexity * multiplier), capped at max_iter
        estimated = int(min_iter + (complexity * multiplier))
        estimated = max(min_iter, min(estimated, max_iter))

        logger.debug(
            "🎯 Estimated iterations: %s (complexity: %.1f, range: %s-%s)",
            estimated,
            complexity,
            min_iter,
            max_iter,
        )

        return estimated
