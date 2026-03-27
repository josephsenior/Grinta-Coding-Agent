from __future__ import annotations

import io
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.events.observation.empty import NullObservation
from backend.events.serialization import event_to_dict
from backend.runtime.server_routes import (
    _ensure_path_in_workspace,
    register_exception_handlers,
    register_routes,
)


def _make_app(workspace_root: Path) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    register_routes(
        app,
        get_client=lambda: SimpleNamespace(initial_cwd=str(workspace_root)),
        get_mcp_proxy=lambda: None,
    )
    return TestClient(app)


def _make_executor_app(
    workspace_root: Path, **executor_fields: object
) -> tuple[TestClient, SimpleNamespace]:
    executor = SimpleNamespace(
        initial_cwd=str(workspace_root.resolve()),
        start_time=0.0,
        last_execution_time=0.0,
    )
    for key, val in executor_fields.items():
        setattr(executor, key, val)
    app = FastAPI()
    register_exception_handlers(app)
    register_routes(
        app,
        get_client=lambda: executor,
        get_mcp_proxy=lambda: None,
    )
    return TestClient(app), executor


def test_upload_file_blocks_destination_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    client = _make_app(workspace)
    response = client.post(
        "/upload_file",
        params={"destination": str(outside)},
        files={"file": ("example.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 400
    assert "Path traversal detected" in response.json()["detail"]


def test_upload_file_blocks_zip_slip_entries(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    destination = workspace / "uploads"
    destination.mkdir()

    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("../escape.txt", "bad")
    payload.seek(0)

    client = _make_app(workspace)
    response = client.post(
        "/upload_file",
        params={"destination": str(destination), "recursive": "true"},
        files={"file": ("archive.zip", payload.read(), "application/zip")},
    )

    assert response.status_code == 400
    assert "Path traversal detected in uploaded archive" in response.json()["detail"]
    assert not (tmp_path / "escape.txt").exists()


def test_upload_file_allows_workspace_destination(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    destination = workspace / "uploads"
    destination.mkdir()

    client = _make_app(workspace)
    response = client.post(
        "/upload_file",
        params={"destination": str(destination)},
        files={"file": ("example.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 200
    assert (destination / "example.txt").read_text(encoding="utf-8") == "hello"


def test_ensure_path_in_workspace_accepts_nested_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    nested = workspace / "a" / "b"
    nested.mkdir(parents=True)
    resolved = _ensure_path_in_workspace(str(nested), str(workspace))
    assert Path(resolved).resolve() == nested.resolve()


def test_ensure_path_in_workspace_rejects_outside(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(HTTPException) as exc:
        _ensure_path_in_workspace(str(outside / "f.txt"), str(workspace))
    assert exc.value.status_code == 400
    assert "traversal" in str(exc.value.detail).lower()


def test_exception_handlers_starlette_and_unexpected() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/teapot")
    async def teapot() -> None:
        raise StarletteHTTPException(418, "short and stout")

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("unexpected")

    client = TestClient(app, raise_server_exceptions=False)
    r1 = client.get("/teapot")
    assert r1.status_code == 418
    assert r1.json()["detail"] == "short and stout"

    r2 = client.get("/boom")
    assert r2.status_code == 500
    assert "unexpected" in r2.json()["detail"].lower()


def test_exception_handler_request_validation_error() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    class Payload(BaseModel):
        count: int

    @app.post("/typed")
    async def typed(p: Payload) -> Payload:
        return p

    client = TestClient(app)
    r = client.post("/typed", json={"count": "not-int"})
    assert r.status_code == 422
    body = r.json()
    assert "Invalid request parameters" in body.get("detail", "")
    assert "errors" in body


def test_get_server_info_includes_uptime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    executor = SimpleNamespace(
        initial_cwd=str(workspace.resolve()),
        start_time=1000.0,
        last_execution_time=1005.0,
    )

    monkeypatch.setattr("backend.runtime.server_routes.time.time", lambda: 1010.0)
    monkeypatch.setattr(
        "backend.runtime.server_routes.get_system_stats",
        lambda: {"ok": True},
    )

    app = FastAPI()
    register_exception_handlers(app)
    register_routes(
        app,
        get_client=lambda: executor,
        get_mcp_proxy=lambda: None,
    )
    client = TestClient(app)
    r = client.get("/server_info")
    assert r.status_code == 200
    data = r.json()
    assert data["uptime"] == 10.0
    assert data["idle_time"] == 5.0
    assert data["resources"] == {"ok": True}


def test_download_files_zips_directory(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "pkg"
    target.mkdir()
    (target / "note.txt").write_text("zip-me", encoding="utf-8")

    client = _make_app(workspace)
    r = client.get("/download_files", params={"path": str(target.resolve())})
    assert r.status_code == 200
    raw = io.BytesIO(r.content)
    with zipfile.ZipFile(raw, "r") as zf:
        names = zf.namelist()
        assert any(n.endswith("note.txt") for n in names)
        data = zf.read([n for n in names if n.endswith("note.txt")][0])
        assert data == b"zip-me"


def test_download_files_rejects_relative_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    client = _make_app(workspace)
    r = client.get("/download_files", params={"path": "relative/path"})
    assert r.status_code == 400


def test_download_files_not_found(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    missing = workspace / "nope"
    client = _make_app(workspace)
    r = client.get("/download_files", params={"path": str(missing.resolve())})
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


def test_upload_file_rejects_relative_destination(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    client = _make_app(workspace)
    r = client.post(
        "/upload_file",
        params={"destination": "not/absolute"},
        files={"file": ("x.txt", b"x", "text/plain")},
    )
    assert r.status_code == 400


def test_upload_file_recursive_requires_zip(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    dest = workspace / "up"
    dest.mkdir()
    client = _make_app(workspace)
    r = client.post(
        "/upload_file",
        params={"destination": str(dest.resolve()), "recursive": "true"},
        files={"file": ("not.zip", io.BytesIO(b"not-a-zip"), "application/octet-stream")},
    )
    # BadZipFile is surfaced as HTTP 500 by the route's broad except branch.
    assert r.status_code == 500
    assert "zip" in r.json()["detail"].lower()


@patch("backend.runtime.server_routes.sys.platform", "win32")
def test_update_mcp_server_skipped_on_windows(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    client = _make_app(workspace)
    r = client.post("/update_mcp_server", json=[])
    assert r.status_code == 200
    assert "skipped" in r.json()["detail"].lower()


def test_execute_action_accepts_flat_action_json(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    back = NullObservation(content="done")
    client, executor = _make_executor_app(
        workspace, run_action=AsyncMock(return_value=back)
    )

    r = client.post(
        "/execute_action",
        json={"action": "null", "args": {}},
    )

    assert r.status_code == 200
    body = r.json()
    assert body.get("observation") == "null"
    assert body.get("content") == "done"
    executor.run_action.assert_awaited_once()
    called_action = executor.run_action.await_args.args[0]
    assert getattr(called_action, "action", None) == "null"


def test_execute_action_accepts_wrapped_event_key(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    back = NullObservation(content="")
    client, executor = _make_executor_app(
        workspace, run_action=AsyncMock(return_value=back)
    )

    r = client.post(
        "/execute_action",
        json={"event": {"action": "null", "args": {}}},
    )

    assert r.status_code == 200
    assert r.json().get("observation") == "null"
    executor.run_action.assert_awaited_once()


def test_execute_action_rejects_observation_payload(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    obs_payload = event_to_dict(NullObservation(content="x"))
    client, _executor = _make_executor_app(workspace, run_action=AsyncMock())

    r = client.post("/execute_action", json=obs_payload)

    assert r.status_code == 400
    assert "Invalid action type" in r.json()["detail"]


def test_execute_action_invalid_json_body(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    client, _executor = _make_executor_app(workspace, run_action=AsyncMock())

    r = client.post(
        "/execute_action",
        content=b"not-json",
        headers={"Content-Type": "application/json"},
    )

    assert r.status_code == 400
    assert "json" in r.json()["detail"].lower()


def test_execute_action_run_action_failure_returns_500(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    client, _executor = _make_executor_app(
        workspace,
        run_action=AsyncMock(side_effect=RuntimeError("executor failed")),
    )

    r = client.post("/execute_action", json={"action": "null", "args": {}})

    assert r.status_code == 500
    assert "unexpected" in r.json()["detail"].lower()


def test_list_files_uses_workspace_when_path_missing(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "alpha.txt").write_text("a", encoding="utf-8")
    client = _make_app(workspace)

    r = client.post("/list_files", json={})

    assert r.status_code == 200
    assert r.json() == ["alpha.txt"]


def test_list_files_directories_sort_before_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "zzz_dir").mkdir()
    (workspace / "aaa.txt").write_text("x", encoding="utf-8")

    client = _make_app(workspace)
    r = client.post("/list_files", json={})

    assert r.status_code == 200
    assert r.json() == ["zzz_dir", "aaa.txt"]


def test_list_files_relative_path_joins_cwd(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sub = workspace / "inside"
    sub.mkdir()
    (sub / "nested.txt").write_text("n", encoding="utf-8")

    client = _make_app(workspace)
    r = client.post("/list_files", json={"path": "inside"})

    assert r.status_code == 200
    assert r.json() == ["nested.txt"]


def test_list_files_outside_workspace_returns_empty(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    client = _make_app(workspace)
    r = client.post("/list_files", json={"path": str(outside.resolve())})

    assert r.status_code == 200
    assert r.json() == []


def test_list_files_when_path_is_file_returns_empty(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    f = workspace / "solo.txt"
    f.write_text("x", encoding="utf-8")

    client = _make_app(workspace)
    r = client.post("/list_files", json={"path": str(f.resolve())})

    assert r.status_code == 200
    assert r.json() == []