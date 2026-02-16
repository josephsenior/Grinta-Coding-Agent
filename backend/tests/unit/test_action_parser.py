"""Unit tests for backend.controller.action_parser — parsing abstractions."""

from __future__ import annotations

import pytest

from backend.controller.action_parser import ActionParseError, ActionParser, ResponseParser
from backend.events.action import Action
from backend.events.action.message import MessageAction


# ---------------------------------------------------------------------------
# ActionParseError
# ---------------------------------------------------------------------------


class TestActionParseError:
    def test_message_stored(self):
        err = ActionParseError("bad format")
        assert err.error == "bad format"

    def test_str(self):
        err = ActionParseError("unexpected token")
        assert str(err) == "unexpected token"

    def test_empty_string(self):
        err = ActionParseError("")
        assert str(err) == ""

    def test_is_exception(self):
        with pytest.raises(ActionParseError):
            raise ActionParseError("boom")


# ---------------------------------------------------------------------------
# Concrete stub implementations for abstract classes
# ---------------------------------------------------------------------------


class _StubActionParser(ActionParser):
    """Concrete parser that matches any string containing 'hello'."""

    def check_condition(self, action_str: str) -> bool:
        return "hello" in action_str.lower()

    def parse(self, action_str: str) -> Action:
        return MessageAction(content=action_str)


class _StubResponseParser(ResponseParser):
    """Concrete response parser for testing the abstract interface."""

    def __init__(self):
        super().__init__()
        self.action_parsers = [_StubActionParser()]

    def parse(self, response) -> Action:
        text = self.parse_response(response)
        return self.parse_action(text)

    def parse_response(self, response) -> str:
        return str(response)

    def parse_action(self, action_str: str) -> Action:
        for parser in self.action_parsers:
            if parser.check_condition(action_str):
                return parser.parse(action_str)
        raise ActionParseError(f"No parser matched: {action_str!r}")


# ---------------------------------------------------------------------------
# ActionParser ABC
# ---------------------------------------------------------------------------


class TestActionParser:
    def test_check_condition_match(self):
        p = _StubActionParser()
        assert p.check_condition("say hello world") is True

    def test_check_condition_no_match(self):
        p = _StubActionParser()
        assert p.check_condition("goodbye") is False

    def test_parse_returns_action(self):
        p = _StubActionParser()
        result = p.parse("hello there")
        assert isinstance(result, Action)
        assert result.content == "hello there"

    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            ActionParser()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# ResponseParser ABC
# ---------------------------------------------------------------------------


class TestResponseParser:
    def test_parse_returns_action(self):
        rp = _StubResponseParser()
        result = rp.parse("hello from llm")
        assert isinstance(result, MessageAction)
        assert result.content == "hello from llm"

    def test_parse_action_no_match_raises(self):
        rp = _StubResponseParser()
        with pytest.raises(ActionParseError, match="No parser matched"):
            rp.parse_action("goodbye")

    def test_action_parsers_list(self):
        rp = _StubResponseParser()
        assert len(rp.action_parsers) == 1

    def test_parse_response_stringifies(self):
        rp = _StubResponseParser()
        assert rp.parse_response(42) == "42"
        assert rp.parse_response({"key": "val"}) == "{'key': 'val'}"

    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            ResponseParser()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# Integration: parser chain
# ---------------------------------------------------------------------------


class TestParserChain:
    def test_multiple_parsers_first_match(self):
        class FallbackParser(ActionParser):
            def check_condition(self, action_str: str) -> bool:
                return True

            def parse(self, action_str: str) -> Action:
                return MessageAction(content="fallback")

        rp = _StubResponseParser()
        rp.action_parsers.append(FallbackParser())
        # "hello" triggers first parser
        result = rp.parse("hello world")
        assert result.content == "hello world"

    def test_multiple_parsers_fallback(self):
        class FallbackParser(ActionParser):
            def check_condition(self, action_str: str) -> bool:
                return True

            def parse(self, action_str: str) -> Action:
                return MessageAction(content="fallback")

        rp = _StubResponseParser()
        rp.action_parsers.append(FallbackParser())
        result = rp.parse("unknown input")
        assert result.content == "fallback"
