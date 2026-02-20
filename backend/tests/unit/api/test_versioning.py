"""Tests for backend.api.versioning — API version middleware and helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.api.versioning import (
    APIVersion,
    CURRENT_VERSION,
    MINIMUM_SUPPORTED_VERSION,
    SUNSET_DATES,
    _EXCLUDED_PATHS,
    add_version_headers,
    get_api_version_from_path,
    version_middleware,
)


# ---------------------------------------------------------------------------
# APIVersion enum
# ---------------------------------------------------------------------------


class TestAPIVersion:
    """Tests for the APIVersion enum."""

    def test_v1_value(self):
        assert APIVersion.V1.value == "v1"

    def test_current_is_v1(self):
        assert CURRENT_VERSION == APIVersion.V1

    def test_minimum_is_v1(self):
        assert MINIMUM_SUPPORTED_VERSION == APIVersion.V1

    def test_sunset_dates_empty(self):
        assert SUNSET_DATES == {}


# ---------------------------------------------------------------------------
# get_api_version_from_path
# ---------------------------------------------------------------------------


class TestGetApiVersionFromPath:
    """Tests for get_api_version_from_path."""

    def test_versioned_path(self):
        assert get_api_version_from_path("/api/v1/health") == "v1"

    def test_v2_path(self):
        assert get_api_version_from_path("/api/v2/sessions") == "v2"

    def test_non_versioned_api_path(self):
        assert get_api_version_from_path("/api/health") is None

    def test_root_path(self):
        assert get_api_version_from_path("/") is None

    def test_empty_path(self):
        assert get_api_version_from_path("") is None

    def test_non_api_path(self):
        assert get_api_version_from_path("/docs/v1/something") is None

    def test_short_path(self):
        assert get_api_version_from_path("/api") is None


# ---------------------------------------------------------------------------
# add_version_headers
# ---------------------------------------------------------------------------


class TestAddVersionHeaders:
    """Tests for add_version_headers."""

    def test_sets_header(self):
        response = MagicMock()
        response.headers = {}
        add_version_headers(response, "v1")
        assert response.headers["API-Version"] == "v1"


# ---------------------------------------------------------------------------
# _EXCLUDED_PATHS
# ---------------------------------------------------------------------------


class TestExcludedPaths:
    """Tests for the excluded paths constant."""

    def test_contains_health_endpoints(self):
        assert "/api/health/live" in _EXCLUDED_PATHS
        assert "/api/health/ready" in _EXCLUDED_PATHS

    def test_contains_docs(self):
        assert "/docs" in _EXCLUDED_PATHS
        assert "/openapi.json" in _EXCLUDED_PATHS

    def test_contains_ws(self):
        assert "/ws" in _EXCLUDED_PATHS
        assert "/api/ws" in _EXCLUDED_PATHS


# ---------------------------------------------------------------------------
# version_middleware
# ---------------------------------------------------------------------------


class TestVersionMiddleware:
    """Tests for the version_middleware async function."""

    @pytest.fixture()
    def mock_request(self):
        request = MagicMock(spec=["url"])
        request.url = MagicMock()
        return request

    @pytest.fixture()
    def mock_response(self):
        resp = MagicMock()
        resp.headers = {}
        return resp

    async def test_excluded_path_skips_middleware(self, mock_request, mock_response):
        mock_request.url.path = "/api/health/live"
        call_next = AsyncMock(return_value=mock_response)
        result = await version_middleware(mock_request, call_next)
        call_next.assert_awaited_once_with(mock_request)
        assert result is mock_response

    @patch("backend.api.versioning.ENFORCE_API_VERSIONING", False)
    async def test_api_path_gets_version_header(self, mock_request, mock_response):
        mock_request.url.path = "/api/sessions"
        call_next = AsyncMock(return_value=mock_response)
        result = await version_middleware(mock_request, call_next)
        assert result.headers.get("API-Version") == CURRENT_VERSION.value

    async def test_versioned_api_path_uses_extracted_version(
        self, mock_request, mock_response
    ):
        mock_request.url.path = "/api/v1/sessions"
        call_next = AsyncMock(return_value=mock_response)
        result = await version_middleware(mock_request, call_next)
        assert result.headers.get("API-Version") == "v1"

    async def test_non_api_path_no_header(self, mock_request, mock_response):
        mock_request.url.path = "/other/path"
        call_next = AsyncMock(return_value=mock_response)
        result = await version_middleware(mock_request, call_next)
        assert "API-Version" not in result.headers

    @patch("backend.api.versioning.ENFORCE_API_VERSIONING", True)
    async def test_enforce_returns_400_for_unversioned(self, mock_request):
        mock_request.url.path = "/api/sessions"
        call_next = AsyncMock()
        result = await version_middleware(mock_request, call_next)
        assert result.status_code == 400
        call_next.assert_not_awaited()

    @patch("backend.api.versioning.ENFORCE_API_VERSIONING", True)
    async def test_enforce_allows_versioned_path(self, mock_request, mock_response):
        mock_request.url.path = "/api/v1/sessions"
        call_next = AsyncMock(return_value=mock_response)
        result = await version_middleware(mock_request, call_next)
        assert result.headers.get("API-Version") == "v1"
