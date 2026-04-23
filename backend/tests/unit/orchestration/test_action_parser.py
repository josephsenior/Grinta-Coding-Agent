"""Tests for backend.orchestration.action_parser module."""

from abc import ABC
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from backend.ledger.action import Action
from backend.orchestration.action_parser import (
    ActionParseError,
    ActionParser,
    ResponseParser,
)


def _raise_action_parse_error(message: str) -> None:
    raise ActionParseError(message)


def _instantiate_abstract(cls: Any) -> Any:
    return cls()


class TestActionParseError:
    """Tests for ActionParseError exception."""

    def test_stores_error_message(self):
        """Test stores error message."""
        error = ActionParseError('test error')
        assert error.error == 'test error'

    def test_str_returns_error_message(self):
        """Test __str__ returns error message."""
        error = ActionParseError('parse failed')
        assert str(error) == 'parse failed'

    def test_is_exception_subclass(self):
        """Test is subclass of Exception."""
        error = ActionParseError('test')
        assert isinstance(error, Exception)

    def test_can_be_raised(self):
        """Test can be raised and caught."""
        with pytest.raises(ActionParseError) as exc_info:
            _raise_action_parse_error('deliberate error')
        assert str(exc_info.value) == 'deliberate error'


class TestResponseParser:
    """Tests for ResponseParser abstract base class."""

    def test_is_abstract_base_class(self):
        """Test is ABC."""
        assert issubclass(ResponseParser, ABC)

    def test_cannot_instantiate(self):
        """Test cannot instantiate ABC directly."""
        with pytest.raises(TypeError):
            _instantiate_abstract(ResponseParser)

    def test_init_creates_empty_action_parsers_list(self):
        """Test __init__ creates empty action_parsers list."""

        class ConcreteParser(ResponseParser):
            def parse(self, response):
                return MagicMock(spec=Action)

            def parse_response(self, response):
                return ''

            def parse_action(self, action_str):
                return MagicMock(spec=Action)

        parser = ConcreteParser()
        assert hasattr(parser, 'action_parsers')
        assert parser.action_parsers == []
        assert isinstance(parser.action_parsers, list)

    def test_has_required_abstract_methods(self):
        """Test has all required abstract methods."""
        # Check parse method
        assert hasattr(ResponseParser, 'parse')
        assert callable(getattr(ResponseParser, 'parse'))

        # Check parse_response method
        assert hasattr(ResponseParser, 'parse_response')
        assert callable(getattr(ResponseParser, 'parse_response'))

        # Check parse_action method
        assert hasattr(ResponseParser, 'parse_action')
        assert callable(getattr(ResponseParser, 'parse_action'))

    def test_subclass_must_implement_parse(self):
        """Test subclass must implement parse method."""

        class IncompleteParser(ResponseParser):
            def parse_response(self, response):
                return ''

            def parse_action(self, action_str):
                return MagicMock(spec=Action)

        with pytest.raises(TypeError):
            _instantiate_abstract(IncompleteParser)

    def test_subclass_must_implement_parse_response(self):
        """Test subclass must implement parse_response method."""

        class IncompleteParser(ResponseParser):
            def parse(self, response):
                return MagicMock(spec=Action)

            def parse_action(self, action_str):
                return MagicMock(spec=Action)

        with pytest.raises(TypeError):
            _instantiate_abstract(IncompleteParser)

    def test_subclass_must_implement_parse_action(self):
        """Test subclass must implement parse_action method."""

        class IncompleteParser(ResponseParser):
            def parse(self, response):
                return MagicMock(spec=Action)

            def parse_response(self, response):
                return ''

        with pytest.raises(TypeError):
            _instantiate_abstract(IncompleteParser)

    def test_concrete_subclass_can_be_instantiated(self):
        """Test concrete implementation can be instantiated."""

        class ConcreteParser(ResponseParser):
            def parse(self, response):
                return MagicMock(spec=Action)

            def parse_response(self, response):
                return 'action'

            def parse_action(self, action_str):
                return MagicMock(spec=Action)

        parser = ConcreteParser()
        assert isinstance(parser, ResponseParser)
        assert parser.action_parsers == []


class TestActionParser:
    """Tests for ActionParser abstract base class."""

    def test_is_abstract_base_class(self):
        """Test is ABC."""
        assert issubclass(ActionParser, ABC)

    def test_cannot_instantiate(self):
        """Test cannot instantiate ABC directly."""
        with pytest.raises(TypeError):
            _instantiate_abstract(ActionParser)

    def test_has_required_abstract_methods(self):
        """Test has all required abstract methods."""
        # Check check_condition method
        assert hasattr(ActionParser, 'check_condition')
        assert callable(getattr(ActionParser, 'check_condition'))

        # Check parse method
        assert hasattr(ActionParser, 'parse')
        assert callable(getattr(ActionParser, 'parse'))

    def test_subclass_must_implement_check_condition(self):
        """Test subclass must implement check_condition method."""

        class IncompleteParser(ActionParser):
            def parse(self, action_str):
                return MagicMock(spec=Action)

        with pytest.raises(TypeError):
            _instantiate_abstract(IncompleteParser)

    def test_subclass_must_implement_parse(self):
        """Test subclass must implement parse method."""

        class IncompleteParser(ActionParser):
            def check_condition(self, action_str):
                return True

        with pytest.raises(TypeError):
            _instantiate_abstract(IncompleteParser)

    def test_concrete_subclass_can_be_instantiated(self):
        """Test concrete implementation can be instantiated."""

        class ConcreteActionParser(ActionParser):
            def check_condition(self, action_str):
                return 'test' in action_str.lower()

            def parse(self, action_str):
                return MagicMock(spec=Action)

        parser = ConcreteActionParser()
        assert isinstance(parser, ActionParser)

    def test_concrete_check_condition_works(self):
        """Test concrete implementation check_condition works."""

        class ConcreteActionParser(ActionParser):
            def check_condition(self, action_str):
                return action_str.startswith('cmd:')

            def parse(self, action_str):
                return MagicMock(spec=Action)

        parser = ConcreteActionParser()
        assert parser.check_condition('cmd:ls') is True
        assert parser.check_condition('think:foo') is False

    def test_concrete_parse_works(self):
        """Test concrete implementation parse works."""

        class ConcreteActionParser(ActionParser):
            def check_condition(self, action_str):
                return True

            def parse(self, action_str):
                mock_action = MagicMock(spec=Action)
                mock_action.command = action_str
                return mock_action

        parser = ConcreteActionParser()
        result = parser.parse('test command')
        assert hasattr(result, 'command')
        assert result.command == 'test command'
