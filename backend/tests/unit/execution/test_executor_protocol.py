"""Tests for backend.execution.executor_protocol — RuntimeExecutorProtocol structural typing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.execution.executor_protocol import RuntimeExecutorProtocol
from backend.ledger.action import (
    CmdRunAction,
    FileEditAction,
    FileReadAction,
    FileWriteAction,
)
from backend.ledger.observation import CmdOutputObservation

# ── RuntimeExecutorProtocol ────────────────────────────────────────────


class TestRuntimeExecutorProtocol:
    """Test RuntimeExecutorProtocol structural typing and runtime_checkable."""

    def test_is_runtime_checkable(self):
        """Test protocol is decorated with @runtime_checkable."""
        # Protocol should have runtime checking enabled
        assert hasattr(RuntimeExecutorProtocol, '__class__')

    def test_protocol_has_ainit_method(self):
        """Test protocol specifies ainit lifecycle method."""
        # Check method exists in protocol
        assert hasattr(RuntimeExecutorProtocol, 'ainit')

    def test_protocol_has_hard_kill_method(self):
        """Test protocol specifies hard_kill lifecycle method."""
        assert hasattr(RuntimeExecutorProtocol, 'hard_kill')

    def test_protocol_has_close_method(self):
        """Test protocol specifies close lifecycle method."""
        assert hasattr(RuntimeExecutorProtocol, 'close')

    def test_protocol_has_initialized_method(self):
        """Test protocol specifies initialized method."""
        assert hasattr(RuntimeExecutorProtocol, 'initialized')

    def test_protocol_has_initial_cwd_property(self):
        """Test protocol specifies initial_cwd property."""
        assert hasattr(RuntimeExecutorProtocol, 'initial_cwd')

    def test_protocol_has_run_action_method(self):
        """Test protocol specifies generic run_action method."""
        assert hasattr(RuntimeExecutorProtocol, 'run_action')

    def test_protocol_has_run_method(self):
        """Test protocol specifies run method for CmdRunAction."""
        assert hasattr(RuntimeExecutorProtocol, 'run')

    def test_protocol_has_read_method(self):
        """Test protocol specifies read method for FileReadAction."""
        assert hasattr(RuntimeExecutorProtocol, 'read')

    def test_protocol_has_write_method(self):
        """Test protocol specifies write method for FileWriteAction."""
        assert hasattr(RuntimeExecutorProtocol, 'write')

    def test_protocol_has_edit_method(self):
        """Test protocol specifies edit method for FileEditAction."""
        assert hasattr(RuntimeExecutorProtocol, 'edit')


# ── Protocol Compliance ────────────────────────────────────────────────


class TestProtocolCompliance:
    """Test that objects implementing the protocol are recognized."""

    def test_compliant_mock_is_recognized(self):
        """Test mock implementing all methods is recognized as protocol compliant."""
        mock_executor = MagicMock(spec=RuntimeExecutorProtocol)
        mock_executor.ainit = AsyncMock()
        mock_executor.hard_kill = AsyncMock()
        mock_executor.close = MagicMock()
        mock_executor.initialized = MagicMock(return_value=True)
        mock_executor.initial_cwd = '/workspace'
        mock_executor.run_action = AsyncMock()
        mock_executor.run = AsyncMock()
        mock_executor.read = AsyncMock()
        mock_executor.write = AsyncMock()
        mock_executor.edit = AsyncMock()

        # isinstance check should work with runtime_checkable protocol
        assert isinstance(mock_executor, RuntimeExecutorProtocol)

    def test_partial_implementation_not_recognized(self):
        """Test object missing methods is not recognized as compliant."""
        partial_executor = MagicMock()
        partial_executor.ainit = AsyncMock()
        partial_executor.close = MagicMock()
        # Missing other required methods

        # Should not be recognized as implementing the protocol
        assert not isinstance(partial_executor, RuntimeExecutorProtocol)

    @pytest.mark.asyncio
    async def test_can_call_lifecycle_methods(self):
        """Test lifecycle methods can be called on compliant object."""
        executor = MagicMock(spec=RuntimeExecutorProtocol)
        executor.ainit = AsyncMock()
        executor.hard_kill = AsyncMock()
        executor.close = MagicMock()
        executor.initialized = MagicMock(return_value=False)

        await executor.ainit()
        executor.initialized()
        await executor.hard_kill()
        executor.close()

        executor.ainit.assert_called_once()
        executor.initialized.assert_called_once()
        executor.hard_kill.assert_called_once()
        executor.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_can_call_action_methods(self):
        """Test action dispatch methods can be called on compliant object."""
        executor = MagicMock(spec=RuntimeExecutorProtocol)
        executor.run_action = AsyncMock(
            return_value=CmdOutputObservation(content='ok', command='test', exit_code=0)
        )
        executor.run = AsyncMock(
            return_value=CmdOutputObservation(
                content='run_ok', command='echo test', exit_code=0
            )
        )
        executor.read = AsyncMock()
        executor.write = AsyncMock()
        executor.edit = AsyncMock()

        cmd_action = CmdRunAction(command='echo test')
        file_read_action = FileReadAction(path='test.txt')
        file_write_action = FileWriteAction(path='out.txt', content='data')
        file_edit_action = FileEditAction(path='edit.txt')

        await executor.run_action(cmd_action)
        await executor.run(cmd_action)
        await executor.read(file_read_action)
        await executor.write(file_write_action)
        await executor.edit(file_edit_action)

        executor.run_action.assert_called_once()
        executor.run.assert_called_once_with(cmd_action)
        executor.read.assert_called_once_with(file_read_action)
        executor.write.assert_called_once_with(file_write_action)
        executor.edit.assert_called_once_with(file_edit_action)

    def test_can_access_initial_cwd_property(self):
        """Test initial_cwd property can be accessed on compliant object."""
        executor = MagicMock(spec=RuntimeExecutorProtocol)
        executor.initial_cwd = '/test/workspace'

        assert executor.initial_cwd == '/test/workspace'


# ── Protocol Documentation ─────────────────────────────────────────────


class TestProtocolDocumentation:
    """Test protocol has proper documentation."""

    def test_protocol_has_docstring(self):
        """Test RuntimeExecutorProtocol has class docstring."""
        doc = RuntimeExecutorProtocol.__doc__
        assert doc is not None and 'Structural sub-typing interface' in doc

    def test_ainit_has_docstring(self):
        """Test ainit method has docstring."""
        doc = RuntimeExecutorProtocol.ainit.__doc__
        assert doc is not None and 'async initialisation' in doc

    def test_hard_kill_has_docstring(self):
        """Test hard_kill method has docstring."""
        doc = RuntimeExecutorProtocol.hard_kill.__doc__
        assert doc is not None and 'Emergency teardown' in doc

    def test_run_action_has_docstring(self):
        """Test run_action method has docstring."""
        doc = RuntimeExecutorProtocol.run_action.__doc__
        assert doc is not None and 'Generic dispatch' in doc

    def test_initial_cwd_has_docstring(self):
        """Test initial_cwd property has docstring."""
        doc = RuntimeExecutorProtocol.initial_cwd.__doc__
        assert doc is not None and 'root working directory' in doc
