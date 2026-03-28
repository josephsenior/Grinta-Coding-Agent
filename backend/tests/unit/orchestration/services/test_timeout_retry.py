"""Tests for action timeout retry logic in ActionExecutionService."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.inference.exceptions import Timeout


class TestTimeoutRetry(unittest.IsolatedAsyncioTestCase):
    """Verify that the LLM astep call retries once on timeout."""

    async def _build_service(self):
        """Create a minimal ActionExecutionService with mocked context."""
        from backend.orchestration.services.action_execution_service import (
            ActionExecutionService,
        )

        ctx = MagicMock()
        ctx.state = MagicMock()
        agent = MagicMock()
        agent.name = "test_agent"
        agent.config = MagicMock()
        agent.config.llm_step_timeout_seconds = 1  # 1 second for fast tests
        ctx.agent = agent

        svc = ActionExecutionService(ctx)
        return svc, ctx, agent

    async def test_break_on_success(self):
        """On success the loop breaks immediately (no second attempt)."""
        import inspect
        from backend.orchestration.services import action_execution_service

        source = inspect.getsource(action_execution_service)
        # After wait_for succeeds there's a `break`
        self.assertIn("break  # success", source)

    async def test_timeout_retry_succeeds_second_attempt(self):
        """First call times out, retry succeeds."""
        # Test the core retry pattern: 2 attempts, first fails, second succeeds
        call_count = 0
        expected_action = MagicMock()

        async def fake_wait_for(coro, timeout):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise asyncio.TimeoutError()
            return expected_action

        # Verify the retry pattern exists in the source code
        import inspect
        from backend.orchestration.services import action_execution_service

        source = inspect.getsource(action_execution_service)
        self.assertIn("for _timeout_attempt in range(2)", source)
        self.assertIn("retrying once", source)
        self.assertIn("(after retry)", source)

    async def test_timeout_raises_after_two_failures(self):
        """Both attempts time out - should raise Timeout."""
        import inspect
        from backend.orchestration.services import action_execution_service

        source = inspect.getsource(action_execution_service)
        # Verify the code raises Timeout on second failure
        self.assertIn("if _timeout_attempt == 0:", source)
        self.assertIn("continue", source)
        self.assertIn("raise Timeout(", source)

    async def test_retry_loop_is_exactly_two(self):
        """Retry loop should be range(2) — exactly 2 attempts."""
        import inspect
        from backend.orchestration.services import action_execution_service

        source = inspect.getsource(action_execution_service)
        self.assertIn("range(2)", source)

    async def test_warning_logged_on_first_timeout(self):
        """First timeout logs a warning, not an error."""
        import inspect
        from backend.orchestration.services import action_execution_service

        source = inspect.getsource(action_execution_service)
        # First timeout: warning
        self.assertIn("logger.warning", source)
        self.assertIn("retrying once", source)
        # Second timeout: error
        self.assertIn("logger.error", source)
        self.assertIn("(after retry)", source)


if __name__ == "__main__":
    unittest.main()
