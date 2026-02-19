"""Tests for backend.engines.navigator.response_parser — browsing action parsers."""

from __future__ import annotations


from backend.engines.navigator.response_parser import (
    BrowsingActionParserBrowseInteractive,
    BrowsingActionParserMessage,
    BrowsingResponseParser,
)
from backend.events.action import BrowseInteractiveAction


# ── BrowsingActionParserMessage ────────────────────────────────────────


class TestBrowsingActionParserMessage:
    def test_check_condition_no_code_block(self):
        parser = BrowsingActionParserMessage()
        assert parser.check_condition("just plain text") is True

    def test_check_condition_with_code_block(self):
        parser = BrowsingActionParserMessage()
        assert parser.check_condition("text ```code``` more") is False

    def test_parse_returns_browse_interactive(self):
        parser = BrowsingActionParserMessage()
        result = parser.parse("Hello user")
        assert isinstance(result, BrowseInteractiveAction)
        assert result.thought == "Hello user"
        assert result.browsergym_send_msg_to_user == "Hello user"
        assert "send_msg_to_user" in result.browser_actions


# ── BrowsingActionParserBrowseInteractive ──────────────────────────────


class TestBrowsingActionParserBrowseInteractive:
    def test_check_condition_always_true(self):
        parser = BrowsingActionParserBrowseInteractive()
        assert parser.check_condition("anything") is True
        assert parser.check_condition("") is True

    def test_parse_with_code_block(self):
        parser = BrowsingActionParserBrowseInteractive()
        action_str = "I will click the button```click('#btn')```"
        result = parser.parse(action_str)
        assert isinstance(result, BrowseInteractiveAction)
        assert "click" in result.browser_actions
        assert result.thought == "I will click the button"

    def test_parse_no_code_block(self):
        parser = BrowsingActionParserBrowseInteractive()
        result = parser.parse("just text no blocks")
        assert isinstance(result, BrowseInteractiveAction)

    def test_extract_send_msg_to_user_from_ast(self):
        parser = BrowsingActionParserBrowseInteractive()
        result = parser.parse('thought```send_msg_to_user("hello world")```')
        assert result.browsergym_send_msg_to_user == "hello world"

    def test_extract_send_msg_to_user_from_regex(self):
        parser = BrowsingActionParserBrowseInteractive()
        # Malformed python that won't parse with AST but regex can catch
        result = parser.parse("think```send_msg_to_user('hi there')```")
        assert result.browsergym_send_msg_to_user == "hi there"

    def test_no_send_msg(self):
        parser = BrowsingActionParserBrowseInteractive()
        result = parser.parse("think```click('#btn')```")
        assert result.browsergym_send_msg_to_user == ""

    def test_extract_browser_actions_empty_code(self):
        parser = BrowsingActionParserBrowseInteractive()
        # Code block is empty — thought becomes the action
        result = parser.parse("some thought``````")
        assert isinstance(result, BrowseInteractiveAction)


# ── BrowsingResponseParser ─────────────────────────────────────────────


class TestBrowsingResponseParser:
    def test_parse_string_input_plain(self):
        parser = BrowsingResponseParser()
        result = parser.parse("just a plain message")
        assert isinstance(result, BrowseInteractiveAction)
        assert result.browsergym_send_msg_to_user == "just a plain message"

    def test_parse_string_input_with_code(self):
        parser = BrowsingResponseParser()
        result = parser.parse("think```goto('http://example.com')```")
        assert isinstance(result, BrowseInteractiveAction)
        assert "goto" in result.browser_actions

    def test_parse_response_dict(self):
        parser = BrowsingResponseParser()
        response = {
            "choices": [{"message": {"content": "I'll click```click('#btn')```"}}]
        }
        result = parser.parse(response)
        assert isinstance(result, BrowseInteractiveAction)

    def test_parse_response_none_content(self):
        parser = BrowsingResponseParser()
        response = {"choices": [{"message": {"content": None}}]}
        action_str = parser.parse_response(response)
        assert action_str == ""

    def test_parse_response_adds_suffix(self):
        parser = BrowsingResponseParser()
        response = {"choices": [{"message": {"content": "click('#btn')"}}]}
        action_str = parser.parse_response(response)
        assert action_str.endswith("```")

    def test_parse_response_already_ends_with_backticks(self):
        parser = BrowsingResponseParser()
        response = {"choices": [{"message": {"content": "text```code```"}}]}
        action_str = parser.parse_response(response)
        assert action_str == "text```code```"
