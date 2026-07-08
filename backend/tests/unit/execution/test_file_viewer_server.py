"""Tests for backend.execution.server.file_viewer_server module.

Targets 20.5% coverage (44 statements) by testing the FastAPI app routes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.execution.server.file_viewer_server import create_app


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
def create_localhost_app(workspace_roots: list[str] | None = None):
    """Create app that always passes localhost check."""
    from starlette.middleware.base import BaseHTTPMiddleware

    app = create_app(
        workspace_roots=workspace_roots,
        allow_configured_extra_roots=False,
    )

    class FakeLocalhostMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            # Override the scope so request.client.host appears as 127.0.0.1
            request.scope['client'] = ('127.0.0.1', 12345)
            return await call_next(request)

    app.add_middleware(FakeLocalhostMiddleware)
    return app


@pytest.fixture()
def localhost_client(tmp_path):
    app = create_localhost_app(workspace_roots=[str(tmp_path)])
    with TestClient(app) as c:
        yield c


class TestRootEndpoint:
    def test_root_returns_status(self, client):
        resp = client.get('/')
        assert resp.status_code == 200
        assert resp.json()['status'] == 'File viewer server is running'


class TestViewEndpointRemoteRejected:
    def test_remote_host_rejected(self, client):
        # TestClient uses "testclient" as client host, which is not localhost
        resp = client.get('/view', params={'path': '/some/file.pdf'})
        assert resp.status_code == 403
        assert 'Access Denied' in resp.text


class TestViewEndpoint:
    def test_relative_path_rejected(self, localhost_client):
        resp = localhost_client.get('/view', params={'path': 'relative/path.pdf'})
        assert resp.status_code == 400
        assert 'absolute' in resp.text.lower()

    def test_nonexistent_file(self, localhost_client, tmp_path):
        missing = tmp_path / 'nonexistent_xyz_abc.pdf'
        resp = localhost_client.get('/view', params={'path': str(missing.resolve())})
        assert resp.status_code in (403, 404)

    def test_directory_path_rejected(self, localhost_client, tmp_path):
        directory = tmp_path / 'subdir'
        directory.mkdir()
        resp = localhost_client.get('/view', params={'path': str(directory.resolve())})
        assert resp.status_code == 400
        assert 'directory' in resp.text.lower()

    def test_unsupported_extension(self, localhost_client, tmp_path):
        """Unsupported extension should return 500 (generate_file_viewer_html raises)."""
        target = tmp_path / 'sample.txt'
        target.write_text('text content', encoding='utf-8')
        resp = localhost_client.get('/view', params={'path': str(target.resolve())})
        assert resp.status_code == 500

    def test_valid_pdf_file(self, localhost_client, tmp_path):
        """Valid PDF file should return 200 with HTML content."""
        target = tmp_path / 'sample.pdf'
        target.write_bytes(b'%PDF-1.4 fake content')
        resp = localhost_client.get('/view', params={'path': str(target.resolve())})
        assert resp.status_code == 200
        assert 'html' in resp.text.lower()

    def test_valid_png_file(self, localhost_client, tmp_path):
        target = tmp_path / 'sample.png'
        target.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 20)
        resp = localhost_client.get('/view', params={'path': str(target.resolve())})
        assert resp.status_code == 200

    def test_path_outside_workspace_rejected(self, localhost_client, tmp_path):
        outside = tmp_path / 'outside'
        outside.mkdir()
        target = outside / 'secret.pdf'
        target.write_bytes(b'%PDF-1.4 outside workspace')
        workspace = tmp_path / 'workspace'
        workspace.mkdir()

        app = create_localhost_app(workspace_roots=[str(workspace)])
        with TestClient(app) as scoped_client:
            resp = scoped_client.get('/view', params={'path': str(target.resolve())})
        assert resp.status_code == 403
        assert 'Access Denied' in resp.text

    def test_path_inside_configured_workspace_allowed(self, tmp_path):
        workspace = tmp_path / 'workspace'
        workspace.mkdir()
        target = workspace / 'inside.pdf'
        target.write_bytes(b'%PDF-1.4 inside workspace')

        app = create_localhost_app(workspace_roots=[str(workspace)])
        with TestClient(app) as scoped_client:
            resp = scoped_client.get('/view', params={'path': str(target.resolve())})
        assert resp.status_code == 200
