"""Comprehensive unit tests for ActionVerifier.

Tests cover the pure synchronous methods of ActionVerifier.
The async _verify_file_edit_action / verify_action that require a live
runtime are tested with mocked runtimes.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.engines.orchestrator.action_verifier import ActionVerifier
from backend.events.action import NullAction
from backend.events.action.files import FileEditAction
from backend.events.observation import CmdOutputObservation, ErrorObservation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _verifier(verification_enabled: bool = True) -> ActionVerifier:
    runtime = MagicMock()
    v = ActionVerifier(runtime)
    v.verification_enabled = verification_enabled
    return v


def _file_edit_action(path: str = "foo.py") -> FileEditAction:
    action = MagicMock(spec=FileEditAction)
    action.path = path
    return action


def _cmd_output(content: str) -> CmdOutputObservation:
    obs = MagicMock(spec=CmdOutputObservation)
    obs.content = content
    return obs


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------

class TestInit:
    def test_stores_runtime(self):
        rt = MagicMock()
        v = ActionVerifier(rt)
        assert v.runtime is rt

    def test_verification_enabled_by_default(self):
        v = ActionVerifier(MagicMock())
        assert v.verification_enabled is True


# ---------------------------------------------------------------------------
# should_verify
# ---------------------------------------------------------------------------

class TestShouldVerify:
    def test_file_edit_action_is_verified(self):
        v = _verifier()
        action = _file_edit_action()
        assert v.should_verify(action) is True

    def test_null_action_not_verified(self):
        v = _verifier()
        assert v.should_verify(NullAction()) is False

    def test_other_mock_action_not_verified(self):
        v = _verifier()
        action = MagicMock()
        # Not a FileEditAction type
        assert v.should_verify(action) is False


# ---------------------------------------------------------------------------
# verify_action — disabled
# ---------------------------------------------------------------------------

class TestVerifyActionDisabled:
    @pytest.mark.asyncio
    async def test_disabled_returns_success(self):
        v = _verifier(verification_enabled=False)
        ok, msg, obs = await v.verify_action(_file_edit_action())
        assert ok is True
        assert "disabled" in msg.lower()
        assert obs is None


# ---------------------------------------------------------------------------
# verify_action — non-file actions
# ---------------------------------------------------------------------------

class TestVerifyActionNonFile:
    @pytest.mark.asyncio
    async def test_null_action_no_verification_needed(self):
        v = _verifier()
        ok, msg, obs = await v.verify_action(NullAction())
        assert ok is True
        assert obs is None


# ---------------------------------------------------------------------------
# verify_action — FileEditAction success
# ---------------------------------------------------------------------------

class TestVerifyActionFileSuccess:
    @pytest.mark.asyncio
    async def test_file_exists_returns_success(self):
        v = _verifier()

        # First runtime call: FILE_EXISTS; second: "42 lines, 1024 bytes"
        call_count = 0

        async def fake_run_action(action):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _cmd_output("FILE_EXISTS")
            return _cmd_output("42 lines, 1024 bytes")

        with patch.object(v, "_run_runtime_action", side_effect=fake_run_action):
            ok, msg, obs = await v.verify_action(_file_edit_action("main.py"))

        assert ok is True
        assert "main.py" in msg
        assert "42" in msg

    @pytest.mark.asyncio
    async def test_file_exists_but_empty_returns_warning(self):
        v = _verifier()
        call_count = 0

        async def fake_run_action(action):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _cmd_output("FILE_EXISTS")
            return _cmd_output("0 lines, 0 bytes")

        with patch.object(v, "_run_runtime_action", side_effect=fake_run_action):
            ok, msg, obs = await v.verify_action(_file_edit_action("empty.py"))

        assert ok is True  # still ok, just a warning
        assert "empty" in msg.lower() or "0" in msg


# ---------------------------------------------------------------------------
# verify_action — FileEditAction failure
# ---------------------------------------------------------------------------

class TestVerifyActionFileMissing:
    @pytest.mark.asyncio
    async def test_file_missing_returns_failure(self):
        v = _verifier()

        async def fake_run_action(action):
            return _cmd_output("FILE_MISSING")

        with patch.object(v, "_run_runtime_action", side_effect=fake_run_action):
            ok, msg, obs = await v.verify_action(_file_edit_action("gone.py"))

        assert ok is False
        assert "gone.py" in msg

    @pytest.mark.asyncio
    async def test_unexpected_obs_type_returns_failure(self):
        v = _verifier()

        async def fake_run_action(action):
            return ErrorObservation("unexpected")

        with patch.object(v, "_run_runtime_action", side_effect=fake_run_action):
            ok, msg, obs = await v.verify_action(_file_edit_action("mystery.py"))

        assert ok is False

    @pytest.mark.asyncio
    async def test_runtime_exception_returns_failure(self):
        v = _verifier()

        async def fake_run_action(action):
            raise OSError("disk error")

        with patch.object(v, "_run_runtime_action", side_effect=fake_run_action):
            ok, msg, obs = await v.verify_action(_file_edit_action("err.py"))

        assert ok is False
        assert "error" in msg.lower()

    @pytest.mark.asyncio
    async def test_content_check_with_unexpected_obs_reports_exists(self):
        """If existence check passes but content check returns non-CmdOutputObs, still True."""
        v = _verifier()
        call_count = 0

        async def fake_run_action(action):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _cmd_output("FILE_EXISTS")
            return MagicMock()  # not a CmdOutputObservation

        with patch.object(v, "_run_runtime_action", side_effect=fake_run_action):
            ok, msg, obs = await v.verify_action(_file_edit_action("partial.py"))

        assert ok is True
