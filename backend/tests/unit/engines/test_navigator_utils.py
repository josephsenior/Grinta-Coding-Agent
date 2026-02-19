"""Tests for backend.engines.navigator.utils — dataclasses, PageParser, PromptBuilder, parse_error_response."""

from __future__ import annotations

import json

import pytest

from backend.engines.navigator.utils import (
    BrowsingPromptFragment,
    ErrorResponse,
    NavigatorMetadata,
    PageParser,
    PromptBuilder,
    parse_error_response,
)


# ── ErrorResponse dataclass ────────────────────────────────────────────


class TestErrorResponse:
    def test_basic(self):
        r = ErrorResponse(message="fail", reason="timeout")
        assert r.message == "fail"
        assert r.reason == "timeout"


# ── NavigatorMetadata dataclass ────────────────────────────────────────


class TestNavigatorMetadata:
    def test_required_only(self):
        m = NavigatorMetadata(goal="search", url="http://x.com", action_space="full")
        assert m.goal == "search"
        assert m.url == "http://x.com"
        assert m.action_space == "full"
        assert m.additional_context is None
        assert m.include_error_prefix is False

    def test_all_fields(self):
        m = NavigatorMetadata(
            goal="g",
            url="u",
            action_space="a",
            additional_context="extra",
            include_error_prefix=True,
        )
        assert m.additional_context == "extra"
        assert m.include_error_prefix is True


# ── BrowsingPromptFragment ─────────────────────────────────────────────


class TestBrowsingPromptFragment:
    def test_defaults(self):
        f = BrowsingPromptFragment(name="intro", content="Hello")
        assert f.name == "intro"
        assert f.content == "Hello"
        assert f.fallback is None
        assert f.metadata == {}

    def test_with_metadata(self):
        f = BrowsingPromptFragment(
            name="n",
            content="c",
            fallback="fb",
            metadata={"k": "v"},
        )
        assert f.fallback == "fb"
        assert f.metadata == {"k": "v"}

    def test_metadata_default_factory(self):
        """Each instance should get its own dict."""
        f1 = BrowsingPromptFragment(name="a", content="a")
        f2 = BrowsingPromptFragment(name="b", content="b")
        f1.metadata["x"] = "1"
        assert "x" not in f2.metadata


# ── PageParser ─────────────────────────────────────────────────────────


class TestPageParser:
    def test_extract_text(self):
        html = "<html><body><p>Hello</p><p>World</p></body></html>"
        parser = PageParser(html)
        text = parser.extract_text()
        assert "Hello" in text
        assert "World" in text

    def test_extract_title(self):
        html = "<html><head><title>My Page</title></head><body></body></html>"
        parser = PageParser(html)
        assert parser.extract_title() == "My Page"

    def test_extract_title_missing(self):
        html = "<html><body>No title</body></html>"
        parser = PageParser(html)
        assert parser.extract_title() == ""

    def test_to_dict(self):
        html = (
            "<html><head><title>Test</title></head><body><p>Content</p></body></html>"
        )
        parser = PageParser(html)
        d = parser.to_dict()
        assert d["title"] == "Test"
        assert "Content" in d["content"]

    def test_strips_tags(self):
        html = "<div><span style='color:red'>Bold</span></div>"
        parser = PageParser(html)
        text = parser.extract_text()
        assert "<" not in text
        assert "Bold" in text


# ── PromptBuilder ──────────────────────────────────────────────────────


class TestPromptBuilder:
    def test_empty_build(self):
        builder = PromptBuilder()
        assert builder.build() == ""

    def test_single_fragment(self):
        builder = PromptBuilder()
        builder.add_fragment(BrowsingPromptFragment(name="intro", content="Hello"))
        assert builder.build() == "Hello"

    def test_multiple_fragments_joined(self):
        builder = PromptBuilder()
        builder.add_fragment(BrowsingPromptFragment(name="a", content="First"))
        builder.add_fragment(BrowsingPromptFragment(name="b", content="Second"))
        result = builder.build()
        assert "First" in result
        assert "Second" in result
        assert "\n\n" in result


# ── parse_error_response ───────────────────────────────────────────────


class TestParseErrorResponse:
    def test_basic(self):
        data = json.dumps({"message": "not found", "reason": "404"})
        result = parse_error_response(data)
        assert isinstance(result, ErrorResponse)
        assert result.message == "not found"
        assert result.reason == "404"

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            parse_error_response("not json")

    def test_missing_keys_raises(self):
        with pytest.raises(KeyError):
            parse_error_response(json.dumps({"message": "ok"}))
