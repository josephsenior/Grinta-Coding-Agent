"""Tests for backend.engine.action_verifier.ActionVerifier."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.engine.action_verifier import ActionVerifier
from backend.ledger.action.commands import CmdRunAction
from backend.ledger.action.files import FileEditAction
from backend.ledger.action.message import MessageAction
from backend.ledger.observation.commands import CmdOutputMetadata, CmdOutputObservation


@pytest.fixture
def verifier():
    runtime = MagicMock()
    return ActionVerifier(runtime)


# ── should_verify ────────────────────────────────────────────────────


class TestShouldVerify:
    def test_file_edit(self, verifier):
        action = MagicMock(spec=FileEditAction)
        assert verifier.should_verify(action)

    def test_cmd_run(self, verifier):
        action = MagicMock(spec=CmdRunAction)
        assert not verifier.should_verify(action)

    def test_message(self, verifier):
        action = MagicMock(spec=MessageAction)
        assert not verifier.should_verify(action)


# ── verify_action ────────────────────────────────────────────────────


class TestVerifyAction:
    @pytest.mark.asyncio
    async def test_disabled(self, verifier):
        verifier.verification_enabled = False
        ok, msg, obs = await verifier.verify_action(MagicMock(spec=FileEditAction))
        assert ok is True
        assert 'disabled' in msg.lower()

    @pytest.mark.asyncio
    async def test_non_file_action(self, verifier):
        action = MagicMock(spec=CmdRunAction)
        ok, msg, obs = await verifier.verify_action(action)
        assert ok is True
        assert obs is None

    @pytest.mark.asyncio
    async def test_file_edit_exists(self, verifier):
        action = MagicMock(spec=FileEditAction)
        action.path = '/tmp/test.py'

        # First call: file exists check
        exists_obs = CmdOutputObservation(
            content='FILE_EXISTS',
            command='python3 ...',
            command_id=1,
            metadata=CmdOutputMetadata(exit_code=0),
        )
        # Second call: content check
        content_obs = CmdOutputObservation(
            content='10 lines, 200 bytes',
            command='python3 ...',
            command_id=2,
            metadata=CmdOutputMetadata(exit_code=0),
        )
        verifier._run_runtime_action = AsyncMock(side_effect=[exists_obs, content_obs])

        ok, msg, obs = await verifier.verify_action(action)
        assert ok is True
        assert 'Verified' in msg

    @pytest.mark.asyncio
    async def test_file_edit_missing(self, verifier):
        action = MagicMock(spec=FileEditAction)
        action.path = '/tmp/missing.py'

        exists_obs = CmdOutputObservation(
            content='FILE_MISSING',
            command='python3 ...',
            command_id=1,
            metadata=CmdOutputMetadata(exit_code=0),
        )
        verifier._run_runtime_action = AsyncMock(return_value=exists_obs)

        ok, msg, obs = await verifier.verify_action(action)
        assert ok is False
        assert 'CRITICAL' in msg

    @pytest.mark.asyncio
    async def test_file_edit_empty(self, verifier):
        action = MagicMock(spec=FileEditAction)
        action.path = '/tmp/empty.py'

        exists_obs = CmdOutputObservation(
            content='FILE_EXISTS',
            command='check',
            command_id=1,
            metadata=CmdOutputMetadata(exit_code=0),
        )
        content_obs = CmdOutputObservation(
            content='0 lines, 0 bytes',
            command='check',
            command_id=2,
            metadata=CmdOutputMetadata(exit_code=0),
        )
        verifier._run_runtime_action = AsyncMock(side_effect=[exists_obs, content_obs])

        ok, msg, obs = await verifier.verify_action(action)
        assert ok is True
        assert 'empty' in msg.lower()

    @pytest.mark.asyncio
    async def test_runtime_error(self, verifier):
        action = MagicMock(spec=FileEditAction)
        action.path = '/tmp/error.py'
        verifier._run_runtime_action = AsyncMock(side_effect=RuntimeError('boom'))

        ok, msg, obs = await verifier.verify_action(action)
        assert ok is False
        assert 'error' in msg.lower()

    @pytest.mark.asyncio
    async def test_file_verification_uses_encoded_python_transport(self, verifier):
        action = MagicMock(spec=FileEditAction)
        action.path = "/tmp/quote'heavy path.py"

        exists_obs = CmdOutputObservation(
            content='FILE_EXISTS',
            command='check',
            command_id=1,
            metadata=CmdOutputMetadata(exit_code=0),
        )
        content_obs = CmdOutputObservation(
            content='10 lines, 200 bytes',
            command='check',
            command_id=2,
            metadata=CmdOutputMetadata(exit_code=0),
        )
        verifier._run_runtime_action = AsyncMock(side_effect=[exists_obs, content_obs])

        await verifier.verify_action(action)

        first_action = verifier._run_runtime_action.await_args_list[0].args[0]
        second_action = verifier._run_runtime_action.await_args_list[1].args[0]
        assert 'b64decode' in first_action.command
        assert 'b64decode' in second_action.command
        assert action.path not in first_action.command
        assert action.path not in second_action.command
