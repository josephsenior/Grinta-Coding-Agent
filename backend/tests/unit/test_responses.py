"""Tests for backend.server.utils.responses — API response helpers."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from backend.server.utils.responses import (
    ERROR_STATUS,
    SUCCESS_STATUS,
    error,
    success,
)


class TestSuccess:
    def test_basic_success(self):
        resp = success()
        body = json.loads(resp.body)
        assert body["status"] == SUCCESS_STATUS
        assert "timestamp" in body
        assert resp.status_code == 200

    def test_with_data(self):
        resp = success(data={"key": "value"})
        body = json.loads(resp.body)
        assert body["data"] == {"key": "value"}

    def test_with_message(self):
        resp = success(message="All good")
        body = json.loads(resp.body)
        assert body["message"] == "All good"

    def test_custom_status_code(self):
        resp = success(status_code=201)
        assert resp.status_code == 201

    def test_with_meta(self):
        resp = success(version="v1", count=5)
        body = json.loads(resp.body)
        assert body["meta"]["version"] == "v1"
        assert body["meta"]["count"] == 5

    def test_with_request_id(self):
        req = MagicMock()
        req.state.request_id = "req-123"
        resp = success(data="ok", request=req)
        body = json.loads(resp.body)
        assert body["request_id"] == "req-123"

    def test_no_data_no_message_no_meta(self):
        resp = success()
        body = json.loads(resp.body)
        assert "data" not in body
        assert "message" not in body
        assert "meta" not in body


class TestError:
    def test_basic_error(self):
        resp = error(message="Bad request")
        body = json.loads(resp.body)
        assert body["status"] == ERROR_STATUS
        assert body["message"] == "Bad request"
        assert "timestamp" in body
        assert resp.status_code == 400

    def test_custom_status_code(self):
        resp = error(message="Not found", status_code=404)
        assert resp.status_code == 404

    def test_with_error_code(self):
        resp = error(message="fail", error_code="VALIDATION_ERROR")
        body = json.loads(resp.body)
        assert body["error_code"] == "VALIDATION_ERROR"

    def test_with_details(self):
        resp = error(message="fail", details={"field": "name"})
        body = json.loads(resp.body)
        assert body["details"]["field"] == "name"

    def test_with_actions(self):
        actions = [{"label": "Retry", "type": "retry"}]
        resp = error(message="fail", actions=actions)
        body = json.loads(resp.body)
        assert len(body["actions"]) == 1
        assert body["actions"][0]["label"] == "Retry"

    def test_with_request_id(self):
        req = MagicMock()
        req.state.request_id = "req-456"
        resp = error(message="fail", request=req)
        body = json.loads(resp.body)
        assert body["request_id"] == "req-456"

    def test_with_meta(self):
        resp = error(message="fail", retry_after=30)
        body = json.loads(resp.body)
        assert body["meta"]["retry_after"] == 30

    def test_no_optional_fields(self):
        resp = error(message="fail")
        body = json.loads(resp.body)
        assert "error_code" not in body
        assert "details" not in body
        assert "actions" not in body
        assert "meta" not in body


class TestConstants:
    def test_success_status(self):
        assert SUCCESS_STATUS == "ok"

    def test_error_status(self):
        assert ERROR_STATUS == "error"
