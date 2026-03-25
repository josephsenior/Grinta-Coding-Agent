"""Tests for backend.runtime.file_viewer_server module.

Targets 20.5% coverage (44 statements) by testing the FastAPI app routes.
"""

from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from backend.runtime.file_viewer_server import create_app


@pytest.fixture()
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def _localhost_headers():
    """Custom client that tricks the app into thinking it comes from localhost."""
    return {}


# Starlette TestClient sets client = ("testclient", 50000) by default.
# We patch create_app to add a middleware that overrides scope["client"].
def create_localhost_app():
    """Create app that always passes localhost check."""
    from starlette.middleware.base import BaseHTTPMiddleware

    app = create_app()

    class FakeLocalhostMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            # Override the scope so request.client.host appears as 127.0.0.1
            request.scope["client"] = ("127.0.0.1", 12345)
            return await call_next(request)

    app.add_middleware(FakeLocalhostMiddleware)
    return app


@pytest.fixture()
def localhost_client():
    app = create_localhost_app()
    with TestClient(app) as c:
        yield c


class TestRootEndpoint:
    def test_root_returns_status(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json()["status"] == "File viewer server is running"


class TestViewEndpointRemoteRejected:
    def test_remote_host_rejected(self, client):
        # TestClient uses "testclient" as client host, which is not localhost
        resp = client.get("/view", params={"path": "/some/file.pdf"})
        assert resp.status_code == 403
        assert "Access Denied" in resp.text


class TestViewEndpoint:
    def test_relative_path_rejected(self, localhost_client):
        resp = localhost_client.get("/view", params={"path": "relative/path.pdf"})
        assert resp.status_code == 400
        assert "absolute" in resp.text.lower()

    def test_nonexistent_file(self, localhost_client):
        resp = localhost_client.get(
            "/view", params={"path": "/nonexistent_xyz_abc/file.pdf"}
        )
        assert resp.status_code in (400, 404)

    def test_directory_path_rejected(self, localhost_client, tmp_path):
        resp = localhost_client.get("/view", params={"path": str(tmp_path)})
        assert resp.status_code == 400
        assert "directory" in resp.text.lower()

    def test_unsupported_extension(self, localhost_client):
        """Unsupported extension should return 500 (generate_file_viewer_html raises)."""
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.write(fd, b"text content")
        os.close(fd)
        try:
            resp = localhost_client.get("/view", params={"path": path})
            assert resp.status_code == 500
        finally:
            os.unlink(path)

    def test_valid_pdf_file(self, localhost_client):
        """Valid PDF file should return 200 with HTML content."""
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.write(fd, b"%PDF-1.4 fake content")
        os.close(fd)
        try:
            resp = localhost_client.get("/view", params={"path": path})
            assert resp.status_code == 200
            assert "html" in resp.text.lower()
        finally:
            os.unlink(path)

    def test_valid_png_file(self, localhost_client):
        fd, path = tempfile.mkstemp(suffix=".png")
        os.write(fd, b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
        os.close(fd)
        try:
            resp = localhost_client.get("/view", params={"path": path})
            assert resp.status_code == 200
        finally:
            os.unlink(path)
