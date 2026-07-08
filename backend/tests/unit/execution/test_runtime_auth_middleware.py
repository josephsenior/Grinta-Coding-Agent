"""Tests for optional runtime HTTP auth middleware."""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.execution.server.routes import register_runtime_auth_middleware


@pytest.fixture()
def authed_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setenv('GRINTA_RUNTIME_API_TOKEN', 'test-runtime-token')
    app = FastAPI()

    @app.get('/ping')
    async def ping() -> dict[str, str]:
        return {'status': 'ok'}

    register_runtime_auth_middleware(app)
    return app


def test_runtime_auth_disabled_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('GRINTA_RUNTIME_API_TOKEN', raising=False)
    app = FastAPI()

    @app.get('/ping')
    async def ping() -> dict[str, str]:
        return {'status': 'ok'}

    register_runtime_auth_middleware(app)
    with TestClient(app) as client:
        assert client.get('/ping').status_code == 200


def test_runtime_auth_rejects_missing_token(authed_app: FastAPI) -> None:
    with TestClient(authed_app) as client:
        response = client.get('/ping')
    assert response.status_code == 401


def test_runtime_auth_accepts_bearer_header(authed_app: FastAPI) -> None:
    with TestClient(authed_app) as client:
        response = client.get(
            '/ping',
            headers={'Authorization': 'Bearer test-runtime-token'},
        )
    assert response.status_code == 200
    assert response.json()['status'] == 'ok'


def test_runtime_auth_accepts_custom_header(authed_app: FastAPI) -> None:
    with TestClient(authed_app) as client:
        response = client.get(
            '/ping',
            headers={'X-Grinta-Runtime-Token': 'test-runtime-token'},
        )
    assert response.status_code == 200


def test_runtime_auth_rejects_wrong_token(authed_app: FastAPI) -> None:
    with TestClient(authed_app) as client:
        response = client.get(
            '/ping',
            headers={'Authorization': 'Bearer wrong-token'},
        )
    assert response.status_code == 401
