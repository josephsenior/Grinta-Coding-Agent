"""Unit tests for backend.runtime.supervisor."""

from __future__ import annotations

import asyncio
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from backend.runtime.supervisor import RuntimeSupervisor, RuntimeSupervisorConfig


class TestRuntimeSupervisorConfig(IsolatedAsyncioTestCase):
    """Test RuntimeSupervisorConfig dataclass."""

    def test_default_configuration(self):
        """Test default configuration values."""
        config = RuntimeSupervisorConfig()
        self.assertEqual(config.connect_timeout_s, 30.0)
        self.assertEqual(config.readiness_timeout_s, 5.0)
        self.assertEqual(config.readiness_poll_s, 0.1)

    def test_custom_configuration(self):
        """Test custom configuration values."""
        config = RuntimeSupervisorConfig(
            connect_timeout_s=60.0,
            readiness_timeout_s=10.0,
            readiness_poll_s=0.2,
        )
        self.assertEqual(config.connect_timeout_s, 60.0)
        self.assertEqual(config.readiness_timeout_s, 10.0)
        self.assertEqual(config.readiness_poll_s, 0.2)

    def test_config_is_frozen(self):
        """Test that config is immutable (frozen dataclass)."""
        config = RuntimeSupervisorConfig()
        with self.assertRaises(AttributeError):
            config.connect_timeout_s = 100.0


class TestRuntimeSupervisor(IsolatedAsyncioTestCase):
    """Test RuntimeSupervisor class."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = RuntimeSupervisorConfig(
            connect_timeout_s=1.0,
            readiness_timeout_s=0.5,
            readiness_poll_s=0.1,
        )
        self.supervisor = RuntimeSupervisor(self.config)

    def test_initialization_with_config(self):
        """Test supervisor initialization with custom config."""
        supervisor = RuntimeSupervisor(self.config)
        self.assertEqual(supervisor._config.connect_timeout_s, 1.0)

    def test_initialization_without_config(self):
        """Test supervisor initialization with default config."""
        supervisor = RuntimeSupervisor()
        self.assertEqual(supervisor._config.connect_timeout_s, 30.0)

    async def test_ensure_connected_no_runtime(self):
        """Test ensure_connected when conversation has no runtime attribute."""
        conversation = MagicMock(spec=[])  # No runtime attribute
        # Should not raise an exception
        await self.supervisor.ensure_connected(conversation)

    async def test_ensure_connected_runtime_is_none(self):
        """Test ensure_connected when runtime is None."""
        conversation = MagicMock()
        conversation.runtime = None
        # Should not raise an exception
        await self.supervisor.ensure_connected(conversation)

    async def test_ensure_connected_no_connect_method(self):
        """Test ensure_connected when runtime has no connect method."""
        conversation = MagicMock()
        conversation.runtime = MagicMock(spec=[])  # No connect method
        conversation.sid = "test-sid"
        # Should not raise an exception
        await self.supervisor.ensure_connected(conversation)

    async def test_ensure_connected_successful(self):
        """Test successful runtime connection with immediate readiness."""
        conversation = MagicMock()
        runtime = MagicMock()
        runtime.connect = AsyncMock()
        runtime.runtime_initialized = True
        conversation.runtime = runtime
        conversation.sid = "test-sid"

        await self.supervisor.ensure_connected(conversation)

        runtime.connect.assert_called_once()

    async def test_ensure_connected_with_readiness_wait(self):
        """Test runtime connection with readiness waiting."""
        conversation = MagicMock()
        runtime = MagicMock()
        runtime.connect = AsyncMock()
        conversation.runtime = runtime
        conversation.sid = "test-sid"

        # Simulate runtime initializing after 2 polls
        call_count = 0

        def get_initialized():
            nonlocal call_count
            call_count += 1
            return call_count > 2

        type(runtime).runtime_initialized = property(lambda self: get_initialized())

        await self.supervisor.ensure_connected(conversation)

        runtime.connect.assert_called_once()
        self.assertGreater(call_count, 2)

    async def test_ensure_connected_timeout_on_connect(self):
        """Test connect timeout handling."""
        conversation = MagicMock()
        runtime = MagicMock()

        async def slow_connect():
            await asyncio.sleep(10)  # Much longer than timeout

        runtime.connect = slow_connect
        conversation.runtime = runtime
        conversation.sid = "test-sid"

        with patch("backend.runtime.supervisor.logger") as mock_logger:
            await self.supervisor.ensure_connected(conversation)
            mock_logger.warning.assert_called_once()
            self.assertIn("timed out", mock_logger.warning.call_args[0][0])

    async def test_ensure_connected_exception_during_connect(self):
        """Test exception handling during connect."""
        conversation = MagicMock()
        runtime = MagicMock()
        runtime.connect = AsyncMock(side_effect=ValueError("Connection failed"))
        conversation.runtime = runtime
        conversation.sid = "test-sid"

        with patch("backend.runtime.supervisor.logger") as mock_logger:
            await self.supervisor.ensure_connected(conversation)
            mock_logger.error.assert_called_once()
            self.assertIn("connect failed", mock_logger.error.call_args[0][0])

    async def test_ensure_connected_readiness_timeout(self):
        """Test readiness timeout when runtime never becomes ready."""
        conversation = MagicMock()
        runtime = MagicMock()
        runtime.connect = AsyncMock()
        runtime.runtime_initialized = False
        conversation.runtime = runtime
        conversation.sid = "test-sid"

        with patch("backend.runtime.supervisor.logger") as mock_logger:
            await self.supervisor.ensure_connected(conversation)
            mock_logger.warning.assert_called()
            # Should have warning about not initializing
            warning_calls = [call for call in mock_logger.warning.call_args_list]
            self.assertTrue(
                any("did not initialize" in str(call) for call in warning_calls)
            )

    async def test_ensure_connected_no_readiness_attribute(self):
        """Test when runtime has no runtime_initialized attribute."""
        conversation = MagicMock()
        runtime = MagicMock(spec=["connect"])
        runtime.connect = AsyncMock()
        conversation.runtime = runtime
        conversation.sid = "test-sid"

        # Should not raise, just skip readiness check
        await self.supervisor.ensure_connected(conversation)
        runtime.connect.assert_called_once()

    async def test_ensure_connected_exception_during_readiness_check(self):
        """Test exception during readiness check is handled gracefully."""
        conversation = MagicMock()

        class FaultyRuntime:
            connect = AsyncMock()
            _call_count = 0

            @property
            def runtime_initialized(self):
                # First call (from hasattr) returns False to pass the check,
                # second call (from getattr) raises to simulate a fault.
                self._call_count += 1
                if self._call_count == 1:
                    return False
                raise RuntimeError("Readiness check failed")

        runtime = FaultyRuntime()
        conversation.runtime = runtime
        conversation.sid = "test-sid"

        # Should not raise — _wait_for_readiness catches the exception
        await self.supervisor.ensure_connected(conversation)
        runtime.connect.assert_called_once()

    async def test_close_no_runtime(self):
        """Test close when conversation has no runtime."""
        conversation = MagicMock(spec=[])
        # Should not raise
        await self.supervisor.close(conversation)

    async def test_close_runtime_is_none(self):
        """Test close when runtime is None."""
        conversation = MagicMock()
        conversation.runtime = None
        # Should not raise
        await self.supervisor.close(conversation)

    async def test_close_no_close_method(self):
        """Test close when runtime has no close method."""
        conversation = MagicMock()
        conversation.runtime = MagicMock(spec=[])
        conversation.sid = "test-sid"
        # Should not raise
        await self.supervisor.close(conversation)

    async def test_close_sync_close(self):
        """Test close with synchronous close method."""
        conversation = MagicMock()
        runtime = MagicMock()
        runtime.close = MagicMock(return_value=None)
        conversation.runtime = runtime
        conversation.sid = "test-sid"

        await self.supervisor.close(conversation)
        runtime.close.assert_called_once()

    async def test_close_async_close(self):
        """Test close with asynchronous close method."""
        conversation = MagicMock()
        runtime = MagicMock()
        runtime.close = AsyncMock()
        conversation.runtime = runtime
        conversation.sid = "test-sid"

        await self.supervisor.close(conversation)
        runtime.close.assert_called_once()

    async def test_close_exception_during_close(self):
        """Test exception during close is logged but not raised."""
        conversation = MagicMock()
        runtime = MagicMock()
        runtime.close = MagicMock(side_effect=ValueError("Close failed"))
        conversation.runtime = runtime
        conversation.sid = "test-sid"

        with patch("backend.runtime.supervisor.logger") as mock_logger:
            # Should not raise
            await self.supervisor.close(conversation)
            mock_logger.debug.assert_called_once()
            self.assertIn("close failed", mock_logger.debug.call_args[0][0])

    async def test_close_async_exception_during_close(self):
        """Test exception during async close is logged but not raised."""
        conversation = MagicMock()
        runtime = MagicMock()
        runtime.close = AsyncMock(side_effect=ValueError("Async close failed"))
        conversation.runtime = runtime
        conversation.sid = "test-sid"

        with patch("backend.runtime.supervisor.logger") as mock_logger:
            # Should not raise
            await self.supervisor.close(conversation)
            mock_logger.debug.assert_called_once()
            self.assertIn("close failed", mock_logger.debug.call_args[0][0])

    async def test_wait_for_readiness_immediate(self):
        """Test _wait_for_readiness when already ready."""
        runtime = MagicMock()
        runtime.runtime_initialized = True

        # Should return immediately
        await self.supervisor._wait_for_readiness(runtime, "test-sid")

    async def test_wait_for_readiness_becomes_ready(self):
        """Test _wait_for_readiness when runtime becomes ready."""
        runtime = MagicMock()
        call_count = 0

        def get_initialized():
            nonlocal call_count
            call_count += 1
            return call_count > 1

        type(runtime).runtime_initialized = property(lambda self: get_initialized())

        await self.supervisor._wait_for_readiness(runtime, "test-sid")
        self.assertGreater(call_count, 1)

    async def test_global_runtime_supervisor_singleton(self):
        """Test that global runtime_supervisor is created."""
        from backend.runtime.supervisor import runtime_supervisor

        self.assertIsInstance(runtime_supervisor, RuntimeSupervisor)
