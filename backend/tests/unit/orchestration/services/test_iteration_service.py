"""Tests for IterationService."""

import unittest
from unittest.mock import MagicMock, patch

from backend.orchestration.services.iteration_service import IterationService


class TestIterationService(unittest.IsolatedAsyncioTestCase):
    """Test IterationService dynamic iteration adjustment."""

    def setUp(self):
        """Create mock context for testing."""
        self.mock_state = MagicMock()
        self.mock_state.iteration_flag = MagicMock()
        self.mock_state.iteration_flag.max_value = 50
        self.mock_state.adjust_iteration_limit = MagicMock()

        self.mock_agent = MagicMock()
        # Prevent MagicMock from auto-creating attributes checked via getattr(..., None)
        del self.mock_agent.task_complexity_analyzer
        self.mock_config = MagicMock()
        self.mock_config.enable_dynamic_iterations = True
        self.mock_config.min_iterations = 20
        self.mock_config.complexity_iteration_multiplier = 50.0
        self.mock_config.max_iterations_override = None

        self.mock_context = MagicMock()
        self.mock_context.agent = self.mock_agent
        self.mock_context.agent_config = self.mock_config
        self.mock_context.state = self.mock_state

        self.service = IterationService(self.mock_context)

    async def test_apply_dynamic_iterations_disabled(self):
        """Test apply_dynamic_iterations does nothing when feature disabled."""
        self.mock_config.enable_dynamic_iterations = False
        mock_ctx = MagicMock()
        mock_ctx.metadata = {'task_complexity': 0.5}

        await self.service.apply_dynamic_iterations(mock_ctx)

        # Should not modify iteration flag
        self.mock_state.adjust_iteration_limit.assert_not_called()

    async def test_apply_dynamic_iterations_no_complexity(self):
        """Test apply_dynamic_iterations does nothing without complexity metadata."""
        mock_ctx = MagicMock()
        mock_ctx.metadata = {}  # No task_complexity

        await self.service.apply_dynamic_iterations(mock_ctx)

        self.mock_state.adjust_iteration_limit.assert_not_called()

    async def test_apply_dynamic_iterations_with_fallback(self):
        """Test apply_dynamic_iterations uses fallback calculation."""
        mock_ctx = MagicMock()
        mock_ctx.metadata = {'task_complexity': 0.8}

        await self.service.apply_dynamic_iterations(mock_ctx)

        # Should calculate: 20 + 0.8 * 50 = 60
        self.mock_state.adjust_iteration_limit.assert_called_once_with(
            60, source='IterationService'
        )

    async def test_apply_dynamic_iterations_with_analyzer(self):
        """Test apply_dynamic_iterations uses analyzer when available."""
        mock_analyzer = MagicMock()
        mock_analyzer.estimate_iterations.return_value = 75
        self.mock_agent.task_complexity_analyzer = mock_analyzer

        mock_ctx = MagicMock()
        mock_ctx.metadata = {'task_complexity': 0.6}

        await self.service.apply_dynamic_iterations(mock_ctx)

        # Should use analyzer estimate
        self.mock_state.adjust_iteration_limit.assert_called_once_with(
            75, source='IterationService'
        )
        mock_analyzer.estimate_iterations.assert_called_once_with(0.6, self.mock_state)

    async def test_apply_dynamic_iterations_with_max_override(self):
        """Test apply_dynamic_iterations respects max_iterations_override."""
        self.mock_config.max_iterations_override = 40
        mock_ctx = MagicMock()
        mock_ctx.metadata = {'task_complexity': 1.0}  # Would calculate to 70

        await self.service.apply_dynamic_iterations(mock_ctx)

        # Should cap at 40
        self.mock_state.adjust_iteration_limit.assert_called_once_with(
            40, source='IterationService'
        )

    async def test_apply_dynamic_iterations_respects_min(self):
        """Test apply_dynamic_iterations respects min_iterations."""
        self.mock_config.min_iterations = 30
        mock_ctx = MagicMock()
        mock_ctx.metadata = {'task_complexity': 0.1}  # Would calculate to 25

        await self.service.apply_dynamic_iterations(mock_ctx)

        # fallback: 30 + 0.1 * 50 = 35, bounded by min=30 → 35
        self.mock_state.adjust_iteration_limit.assert_called_once_with(
            35, source='IterationService'
        )

    async def test_apply_dynamic_iterations_no_iteration_flag(self):
        """Test apply_dynamic_iterations handles missing iteration flag."""
        del self.mock_state.iteration_flag
        mock_ctx = MagicMock()
        mock_ctx.metadata = {'task_complexity': 0.5}

        # Should not raise exception
        await self.service.apply_dynamic_iterations(mock_ctx)

    async def test_apply_dynamic_iterations_none_state(self):
        """Test apply_dynamic_iterations handles None state."""
        self.mock_context.state = None
        mock_ctx = MagicMock()
        mock_ctx.metadata = {'task_complexity': 0.5}

        # Should not raise exception
        await self.service.apply_dynamic_iterations(mock_ctx)

    def test_should_apply_iterations_all_conditions_met(self):
        """Test _should_apply_iterations returns True when conditions met."""
        result = self.service._should_apply_iterations(
            self.mock_agent, self.mock_config, self.mock_state
        )

        self.assertTrue(result)

    def test_should_apply_iterations_disabled_config(self):
        """Test _should_apply_iterations returns False when disabled."""
        self.mock_config.enable_dynamic_iterations = False

        result = self.service._should_apply_iterations(
            self.mock_agent, self.mock_config, self.mock_state
        )

        self.assertFalse(result)

    def test_should_apply_iterations_none_agent(self):
        """Test _should_apply_iterations returns False with None agent."""
        result = self.service._should_apply_iterations(
            None, self.mock_config, self.mock_state
        )

        self.assertFalse(result)

    def test_get_iteration_flag_valid(self):
        """Test _get_iteration_flag returns flag when valid."""
        result = self.service._get_iteration_flag(self.mock_state)

        self.assertEqual(result, self.mock_state.iteration_flag)

    def test_get_iteration_flag_none(self):
        """Test _get_iteration_flag returns None when no flag."""
        del self.mock_state.iteration_flag

        result = self.service._get_iteration_flag(self.mock_state)

        self.assertIsNone(result)

    def test_get_iteration_flag_no_max_value(self):
        """Test _get_iteration_flag returns None when flag has no max_value."""
        self.mock_state.iteration_flag = MagicMock(spec=[])

        result = self.service._get_iteration_flag(self.mock_state)

        self.assertIsNone(result)

    def test_determine_target_iterations_uses_analyzer(self):
        """Test _determine_target_iterations prefers analyzer."""
        mock_analyzer = MagicMock()
        mock_analyzer.estimate_iterations.return_value = 100
        self.mock_agent.task_complexity_analyzer = mock_analyzer

        result = self.service._determine_target_iterations(
            self.mock_agent, self.mock_config, 0.5, self.mock_state
        )

        self.assertEqual(result, 100)

    def test_determine_target_iterations_fallback(self):
        """Test _determine_target_iterations uses fallback when no analyzer."""
        result = self.service._determine_target_iterations(
            self.mock_agent, self.mock_config, 0.6, self.mock_state
        )

        # 20 + 0.6 * 50 = 50
        self.assertEqual(result, 50)

    @patch('backend.orchestration.services.iteration_service.logger')
    def test_estimate_iterations_from_analyzer_exception(self, mock_logger):
        """Test _estimate_iterations_from_analyzer handles exceptions."""
        mock_analyzer = MagicMock()
        mock_analyzer.estimate_iterations.side_effect = ValueError('Test error')
        self.mock_agent.task_complexity_analyzer = mock_analyzer

        result = self.service._estimate_iterations_from_analyzer(
            self.mock_agent, 0.5, self.mock_state
        )

        self.assertIsNone(result)
        mock_logger.debug.assert_called_once()

    def test_estimate_iterations_from_analyzer_no_analyzer(self):
        """Test _estimate_iterations_from_analyzer returns None without analyzer."""
        result = self.service._estimate_iterations_from_analyzer(
            self.mock_agent, 0.5, self.mock_state
        )

        self.assertIsNone(result)

    def test_fallback_iteration_target(self):
        """Test _fallback_iteration_target calculates correctly."""
        result = self.service._fallback_iteration_target(self.mock_config, 0.4)

        # 20 + 0.4 * 50 = 40
        self.assertEqual(result, 40)

    def test_fallback_iteration_target_custom_config(self):
        """Test _fallback_iteration_target with custom config values."""
        self.mock_config.min_iterations = 10
        self.mock_config.complexity_iteration_multiplier = 100.0

        result = self.service._fallback_iteration_target(self.mock_config, 0.3)

        # 10 + 0.3 * 100 = 40
        self.assertEqual(result, 40)

    @patch('backend.orchestration.services.iteration_service.logger')
    def test_apply_iteration_flag_direct_mutation(self, mock_logger):
        """Test _apply_iteration_flag mutates flag directly when state doesn't match."""
        # Create a flag that's NOT on the state
        detached_flag = MagicMock()
        detached_flag.max_value = 50

        self.service._apply_iteration_flag(detached_flag, self.mock_config, 0.8, 60)

        # Should mutate directly
        self.assertEqual(detached_flag.max_value, 60)
        mock_logger.debug.assert_called_once()

    @patch('backend.orchestration.services.iteration_service.logger')
    def test_apply_iteration_flag_via_state(self, mock_logger):
        """Test _apply_iteration_flag uses state.adjust_iteration_limit."""
        self.service._apply_iteration_flag(
            self.mock_state.iteration_flag, self.mock_config, 0.8, 60
        )

        # Should use state method
        self.mock_state.adjust_iteration_limit.assert_called_once_with(
            60, source='IterationService'
        )
        mock_logger.debug.assert_called_once()

    async def test_apply_dynamic_iterations_zero_complexity(self):
        """Test apply_dynamic_iterations with zero complexity."""
        mock_ctx = MagicMock()
        mock_ctx.metadata = {'task_complexity': 0.0}

        await self.service.apply_dynamic_iterations(mock_ctx)

        # Should use min_iterations (20)
        self.mock_state.adjust_iteration_limit.assert_called_once_with(
            20, source='IterationService'
        )

    async def test_apply_dynamic_iterations_high_complexity(self):
        """Test apply_dynamic_iterations with high complexity."""
        mock_ctx = MagicMock()
        mock_ctx.metadata = {'task_complexity': 2.0}

        await self.service.apply_dynamic_iterations(mock_ctx)

        # 20 + 2.0 * 50 = 120
        self.mock_state.adjust_iteration_limit.assert_called_once_with(
            120, source='IterationService'
        )


if __name__ == '__main__':
    unittest.main()
