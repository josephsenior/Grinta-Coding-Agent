from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from backend.execution.drivers.local.local_runtime_inprocess import LocalRuntimeInProcess


def _make_runtime(workspace: Path, *, owns_workspace: bool) -> LocalRuntimeInProcess:
    runtime = object.__new__(LocalRuntimeInProcess)
    runtime._executor = None
    runtime._temp_workspace = str(workspace)
    runtime._owns_workspace = owns_workspace
    return runtime


def test_close_removes_owned_temp_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "owned-workspace"
    workspace.mkdir()
    runtime = _make_runtime(workspace, owns_workspace=True)

    with patch("time.sleep"):
        with patch(
            "backend.execution.drivers.local.local_runtime_inprocess.ActionExecutionClient.close"
        ) as mock_super_close:
            with patch("shutil.rmtree") as mock_rmtree:
                runtime.close()

    mock_rmtree.assert_called_once_with(str(workspace))
    mock_super_close.assert_called_once_with()


def test_close_preserves_user_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "user-workspace"
    workspace.mkdir()
    runtime = _make_runtime(workspace, owns_workspace=False)

    with patch("time.sleep"):
        with patch(
            "backend.execution.drivers.local.local_runtime_inprocess.ActionExecutionClient.close"
        ) as mock_super_close:
            with patch("shutil.rmtree") as mock_rmtree:
                runtime.close()

    mock_rmtree.assert_not_called()
    mock_super_close.assert_called_once_with()