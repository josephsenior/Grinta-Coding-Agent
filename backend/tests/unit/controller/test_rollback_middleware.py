"""Unit tests for backend.controller.rollback_middleware — checkpoint creation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.controller.rollback_middleware import (
    RollbackMiddleware,
    _RISKY_ACTION_TYPES,
)
from backend.controller.tool_pipeline import ToolInvocationContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(
    action_type: str = "FileEditAction",
    workspace_path: str | None = None,
) -> ToolInvocationContext:
    """Build a lightweight ToolInvocationContext mock."""
    action = MagicMock()
    type(action).__name__ = action_type

    controller = MagicMock()
    if workspace_path:
        runtime = MagicMock()
        runtime.workspace_dir = workspace_path
        controller.runtime = runtime
    else:
        controller.runtime = None

    state = MagicMock()
    state.sid = "test-session"

    return ToolInvocationContext(
        controller=controller,
        action=action,
        state=state,
        metadata={},
    )


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestRollbackMiddlewareInit:
    def test_default_enabled(self):
        mw = RollbackMiddleware()
        assert mw._enabled is True
        assert mw._manager is None

    def test_disabled(self):
        mw = RollbackMiddleware(enabled=False)
        assert mw._enabled is False

    def test_workspace_path_stored(self):
        mw = RollbackMiddleware(workspace_path="/tmp/ws")
        assert mw._workspace_path == "/tmp/ws"


# ---------------------------------------------------------------------------
# _RISKY_ACTION_TYPES classification
# ---------------------------------------------------------------------------


class TestRiskyActionTypes:
    @pytest.mark.parametrize(
        "action_type",
        ["FileEditAction", "FileWriteAction", "CmdRunAction"],
    )
    def test_risky(self, action_type):
        assert action_type in _RISKY_ACTION_TYPES

    @pytest.mark.parametrize(
        "action_type",
        ["MessageAction", "BrowseURLAction", "AgentFinishAction", "IPythonRunCellAction"],
    )
    def test_not_risky(self, action_type):
        assert action_type not in _RISKY_ACTION_TYPES


# ---------------------------------------------------------------------------
# execute stage
# ---------------------------------------------------------------------------


class TestExecuteStage:
    @pytest.mark.asyncio
    async def test_disabled_skips(self):
        mw = RollbackMiddleware(enabled=False)
        ctx = _make_ctx()
        await mw.execute(ctx)
        assert "rollback_checkpoint_id" not in ctx.metadata

    @pytest.mark.asyncio
    async def test_non_risky_action_skips(self):
        mw = RollbackMiddleware(workspace_path="/tmp/ws")
        ctx = _make_ctx(action_type="MessageAction")
        await mw.execute(ctx)
        assert "rollback_checkpoint_id" not in ctx.metadata

    @pytest.mark.asyncio
    async def test_risky_action_creates_checkpoint(self, tmp_path):
        """With a mock manager, checkpoint is created and metadata set."""
        mw = RollbackMiddleware(workspace_path=str(tmp_path))
        mock_mgr = MagicMock()
        mock_mgr.create_checkpoint.return_value = "cp-001"
        mw._manager = mock_mgr

        ctx = _make_ctx(action_type="FileEditAction")
        await mw.execute(ctx)

        mock_mgr.create_checkpoint.assert_called_once()
        assert ctx.metadata["rollback_checkpoint_id"] == "cp-001"
        assert ctx.metadata["rollback_available"] is True

    @pytest.mark.asyncio
    async def test_checkpoint_failure_continues(self, tmp_path):
        """If checkpoint creation throws, execution continues without error."""
        mw = RollbackMiddleware(workspace_path=str(tmp_path))
        mock_mgr = MagicMock()
        mock_mgr.create_checkpoint.side_effect = RuntimeError("disk full")
        mw._manager = mock_mgr

        ctx = _make_ctx(action_type="CmdRunAction")
        await mw.execute(ctx)
        # No checkpoint stored, but no crash
        assert "rollback_checkpoint_id" not in ctx.metadata


# ---------------------------------------------------------------------------
# Lazy manager initialization
# ---------------------------------------------------------------------------


class TestLazyManagerInit:
    def test_no_workspace_disables(self):
        mw = RollbackMiddleware(workspace_path=None)
        ctx = _make_ctx(workspace_path=None)
        ctx.controller.runtime = None
        result = mw._get_manager(ctx)
        assert result is None
        assert mw._enabled is False

    def test_invalid_workspace_disables(self):
        mw = RollbackMiddleware(workspace_path="/nonexistent/path/xyz")
        ctx = _make_ctx()
        result = mw._get_manager(ctx)
        assert result is None
        assert mw._enabled is False

    def test_manager_cached(self, tmp_path):
        """Once created, the manager is reused."""
        mw = RollbackMiddleware(workspace_path=str(tmp_path))
        mock_mgr = MagicMock()
        mw._manager = mock_mgr
        ctx = _make_ctx()
        result = mw._get_manager(ctx)
        assert result is mock_mgr

    def test_workspace_from_runtime(self, tmp_path):
        """Falls back to ctx.controller.runtime.workspace_dir."""
        mw = RollbackMiddleware(workspace_path=None)
        ctx = _make_ctx(workspace_path=str(tmp_path))
        # RollbackManager is imported inside _get_manager — patch at source
        with patch(
            "backend.core.rollback.rollback_manager.RollbackManager"
        ) as MockRM:
            MockRM.return_value = MagicMock()
            result = mw._get_manager(ctx)
        assert result is not None


# ---------------------------------------------------------------------------
# observe stage
# ---------------------------------------------------------------------------


class TestObserveStage:
    @pytest.mark.asyncio
    async def test_observe_no_checkpoint_noop(self):
        mw = RollbackMiddleware()
        ctx = _make_ctx()
        ctx.metadata = {}
        # Should not raise
        await mw.observe(ctx)

    @pytest.mark.asyncio
    async def test_observe_no_audit_id_noop(self):
        mw = RollbackMiddleware()
        ctx = _make_ctx()
        ctx.metadata = {"rollback_checkpoint_id": "cp-001"}
        await mw.observe(ctx)

    @pytest.mark.asyncio
    async def test_observe_updates_audit_entry(self):
        mw = RollbackMiddleware()
        ctx = _make_ctx()
        ctx.metadata = {
            "rollback_checkpoint_id": "cp-001",
            "audit_id": "audit-123",
        }
        mock_audit = AsyncMock()
        ctx.controller.id = "sid-1"
        ctx.controller.safety_validator = MagicMock()
        ctx.controller.safety_validator.telemetry_logger = mock_audit

        await mw.observe(ctx)
        mock_audit.update_entry_snapshot.assert_awaited_once()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


class TestPublicHelpers:
    def test_rollback_to_no_manager(self):
        mw = RollbackMiddleware()
        assert mw.rollback_to("cp-001") is False

    def test_rollback_to_with_manager(self):
        mw = RollbackMiddleware()
        mock_mgr = MagicMock()
        mock_mgr.rollback_to.return_value = True
        mw._manager = mock_mgr
        assert mw.rollback_to("cp-001") is True
        mock_mgr.rollback_to.assert_called_once_with("cp-001")

    def test_list_checkpoints_no_manager(self):
        mw = RollbackMiddleware()
        assert mw.list_checkpoints() == []

    def test_list_checkpoints_with_manager(self):
        mw = RollbackMiddleware()
        mock_mgr = MagicMock()
        mock_mgr.list_checkpoints.return_value = [{"id": "cp-001"}]
        mw._manager = mock_mgr
        result = mw.list_checkpoints()
        assert result == [{"id": "cp-001"}]
