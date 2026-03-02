"""Tests for backend.engines.orchestrator.tools.iframe_helper module.

Targets 0% coverage (22 statements).
"""

from __future__ import annotations

import pytest

from backend.engines.orchestrator.tools.iframe_helper import (
    add_iframe_headers,
    create_iframe_friendly_app,
    get_fastapi_iframe_config,
    get_flask_iframe_config,
    get_iframe_tips,
)


class TestAddIframeHeaders:
    def test_none_creates_new_dict(self):
        result = add_iframe_headers(None)
        assert isinstance(result, dict)

    def test_existing_headers_updated(self):
        headers = {"X-Custom": "val"}
        result = add_iframe_headers(headers)
        assert result["X-Custom"] == "val"
        assert "Content-Security-Policy" in result

    def test_returns_same_dict(self):
        headers: dict[str, str] = {}
        result = add_iframe_headers(headers)
        assert result is headers


class TestGetFlaskIframeConfig:
    def test_returns_dict(self):
        cfg = get_flask_iframe_config()
        assert isinstance(cfg, dict)
        assert "SEND_FILE_MAX_AGE_DEFAULT" in cfg

    def test_expected_keys(self):
        cfg = get_flask_iframe_config()
        assert "TEMPLATES_AUTO_RELOAD" in cfg


class TestGetFastapiIframeConfig:
    def test_returns_dict(self):
        cfg = get_fastapi_iframe_config()
        assert isinstance(cfg, dict)
        assert cfg["docs_url"] == "/docs"


class TestCreateIframeFriendlyApp:
    def test_flask_app_code(self):
        code = create_iframe_friendly_app("flask", 5000)
        assert "Flask" in code
        assert "5000" in code

    def test_fastapi_app_code(self):
        code = create_iframe_friendly_app("fastapi", 8000)
        assert "FastAPI" in code
        assert "8000" in code

    def test_case_insensitive(self):
        code = create_iframe_friendly_app("FLASK")
        assert "Flask" in code

    def test_unsupported_raises(self):
        with pytest.raises(ValueError, match="Unsupported app_type"):
            create_iframe_friendly_app("django")


class TestGetIframeTips:
    def test_returns_non_empty_string(self):
        tips = get_iframe_tips()
        assert isinstance(tips, str)
        assert len(tips) > 50

    def test_mentions_headers(self):
        tips = get_iframe_tips()
        assert "X-Frame-Options" in tips
