"""Tests for backend.telemetry.cost_recording — cost recording abstraction with callback registration."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.telemetry.cost_recording import record_llm_cost, register_cost_recorder

# ── register_cost_recorder function ────────────────────────────────────


class TestRegisterCostRecorder:
    """Test cost recorder registration."""

    def teardown_method(self):
        """Clear registered recorder after each test."""
        import backend.telemetry.cost_recording as module

        module._cost_recorder = None

    def test_registers_recorder_callback(self):
        """Test registers a cost recorder callback."""
        recorder = MagicMock()
        register_cost_recorder(recorder)

        import backend.telemetry.cost_recording as module

        assert module._cost_recorder is recorder

    def test_registration_completes_without_error(self):
        """Test registration completes successfully."""
        recorder = MagicMock()
        # Should not raise
        register_cost_recorder(recorder)

        import backend.telemetry.cost_recording as module

        assert module._cost_recorder is recorder

    def test_can_register_different_recorder(self):
        """Test can register a different recorder (replaces previous)."""
        recorder1 = MagicMock()
        recorder2 = MagicMock()

        register_cost_recorder(recorder1)
        register_cost_recorder(recorder2)

        import backend.telemetry.cost_recording as module

        assert module._cost_recorder is recorder2

    def test_accepts_callable(self):
        """Test accepts any callable as recorder."""

        def my_recorder(user_key: str, cost: float) -> None:
            pass

        register_cost_recorder(my_recorder)

        import backend.telemetry.cost_recording as module

        assert module._cost_recorder is my_recorder


# ── record_llm_cost function ───────────────────────────────────────────


class TestRecordLLMCost:
    """Test LLM cost recording."""

    def setup_method(self):
        """Clear recorder before each test."""
        import backend.telemetry.cost_recording as module

        module._cost_recorder = None

    def teardown_method(self):
        """Clear recorder after each test."""
        import backend.telemetry.cost_recording as module

        module._cost_recorder = None

    def test_no_op_when_no_recorder_registered(self):
        """Test is no-op when no cost recorder is registered."""
        # Should not raise even though no recorder is set
        record_llm_cost('user:123', 0.05)

    def test_calls_registered_recorder(self):
        """Test calls registered recorder with user_key and cost."""
        recorder = MagicMock()
        register_cost_recorder(recorder)

        record_llm_cost('user:123', 0.05)

        recorder.assert_called_once_with('user:123', 0.05)

    def test_records_multiple_costs(self):
        """Test can record multiple costs sequentially."""
        recorder = MagicMock()
        register_cost_recorder(recorder)

        record_llm_cost('user:123', 0.05)
        record_llm_cost('user:456', 0.10)
        record_llm_cost('ip:127.0.0.1', 0.02)

        assert recorder.call_count == 3
        recorder.assert_any_call('user:123', 0.05)
        recorder.assert_any_call('user:456', 0.10)
        recorder.assert_any_call('ip:127.0.0.1', 0.02)

    def test_handles_recorder_exception_gracefully(self):
        """Test handles recorder exception without raising."""
        recorder = MagicMock(side_effect=ValueError('Recorder failed'))
        register_cost_recorder(recorder)

        # Should not raise even though recorder raises
        record_llm_cost('user:123', 0.05)

    def test_continues_after_recorder_exception(self):
        """Test continues recording after a callback exception."""
        recorder = MagicMock()
        recorder.side_effect = [ValueError('First call fails'), None, None]
        register_cost_recorder(recorder)

        # First call raises, but subsequent calls should still work
        record_llm_cost('user:1', 0.01)  # fails
        record_llm_cost('user:2', 0.02)  # succeeds
        record_llm_cost('user:3', 0.03)  # succeeds

        assert recorder.call_count == 3

    def test_handles_zero_cost(self):
        """Test handles zero cost recording."""
        recorder = MagicMock()
        register_cost_recorder(recorder)

        record_llm_cost('user:123', 0.0)

        recorder.assert_called_once_with('user:123', 0.0)

    def test_handles_large_cost(self):
        """Test handles large cost values."""
        recorder = MagicMock()
        register_cost_recorder(recorder)

        record_llm_cost('user:123', 1000.50)

        recorder.assert_called_once_with('user:123', 1000.50)

    def test_handles_ip_based_user_key(self):
        """Test handles IP-based user keys."""
        recorder = MagicMock()
        register_cost_recorder(recorder)

        record_llm_cost('ip:192.168.1.1', 0.03)

        recorder.assert_called_once_with('ip:192.168.1.1', 0.03)

    def test_handles_user_id_based_key(self):
        """Test handles user ID-based keys."""
        recorder = MagicMock()
        register_cost_recorder(recorder)

        record_llm_cost('user:abc123', 0.07)

        recorder.assert_called_once_with('user:abc123', 0.07)


# ── Global State Management ────────────────────────────────────────────


class TestGlobalState:
    """Test global cost recorder state management."""

    def teardown_method(self):
        """Reset global state after each test."""
        import backend.telemetry.cost_recording as module

        module._cost_recorder = None

    def test_initial_state_is_none(self):
        """Test _cost_recorder is None initially."""
        import backend.telemetry.cost_recording as module

        # Reset to initial state
        module._cost_recorder = None
        assert module._cost_recorder is None

    def test_state_persists_across_calls(self):
        """Test registered recorder persists across multiple record calls."""
        recorder = MagicMock()
        register_cost_recorder(recorder)

        record_llm_cost('user:1', 0.01)
        record_llm_cost('user:2', 0.02)

        # Same recorder should be called both times
        assert recorder.call_count == 2


# ── Integration Scenarios ──────────────────────────────────────────────


class TestIntegrationScenarios:
    """Test realistic usage scenarios."""

    def teardown_method(self):
        """Clean up after each test."""
        import backend.telemetry.cost_recording as module

        module._cost_recorder = None

    def test_server_middleware_registration_pattern(self):
        """Test typical server middleware registration pattern."""
        cost_accumulator = {'total': 0.0}

        def middleware_recorder(user_key: str, cost: float) -> None:
            cost_accumulator['total'] += cost

        # Server middleware registers itself
        register_cost_recorder(middleware_recorder)

        # Controller/models record costs
        record_llm_cost('user:123', 0.05)
        record_llm_cost('user:456', 0.10)
        record_llm_cost('user:123', 0.03)

        # Verify costs accumulated
        assert abs(cost_accumulator['total'] - 0.18) < 0.0001

    def test_quota_disabled_scenario(self):
        """Test behavior when quota middleware is disabled (no recorder)."""
        # No recorder registered (quota disabled)

        # Should not raise errors
        record_llm_cost('user:123', 0.05)
        record_llm_cost('user:456', 0.10)

    def test_test_environment_scenario(self):
        """Test typical test environment (no recorder needed)."""
        # In tests, recorder often not registered

        # Should silently no-op
        record_llm_cost('test_user', 0.01)

    def test_recorders_can_be_swapped(self):
        """Test swapping recorders (e.g., for different middleware)."""
        calls1 = []
        calls2 = []

        def recorder1(user_key: str, cost: float) -> None:
            calls1.append((user_key, cost))

        def recorder2(user_key: str, cost: float) -> None:
            calls2.append((user_key, cost))

        register_cost_recorder(recorder1)
        record_llm_cost('user:1', 0.01)

        register_cost_recorder(recorder2)
        record_llm_cost('user:2', 0.02)

        assert len(calls1) == 1
        assert len(calls2) == 1
        assert calls1[0] == ('user:1', 0.01)
        assert calls2[0] == ('user:2', 0.02)
