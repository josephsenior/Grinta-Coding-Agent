"""Abstract interfaces for parsing LLM responses into Forge actions."""

from abc import ABC, abstractmethod
from typing import Any

from backend.ledger.action import Action


class ActionParseError(Exception):
    """Exception raised when the response from the LLM cannot be parsed into an action."""

    def __init__(self, error: str) -> None:
        """Store the parsing error message."""
        self.error = error

    def __str__(self) -> str:
        """Return the stored parsing error message."""
        return self.error


class ResponseParser(ABC):
    """Common interface for converting LLM responses into Forge actions."""

    def __init__(self) -> None:
        """Initialize the parser with an empty list of action parsers."""
        self.action_parsers: list[ActionParser] = []

    @abstractmethod
    def parse(self, response: Any) -> Action:
        """Convert a raw LLM response into an `Action`."""

    @abstractmethod
    def parse_response(self, response: Any) -> str:
        """Extract an action string from the given LLM response."""

    @abstractmethod
    def parse_action(self, action_str: str) -> Action:
        """Convert an action string into an `Action` instance."""


class ActionParser(ABC):
    """Abstract parser that handles a specific action string format."""

    @abstractmethod
    def check_condition(self, action_str: str) -> bool:
        """Check if the action string can be parsed by this parser."""

    @abstractmethod
    def parse(self, action_str: str) -> Action:
        """Parses the action from the action string from the LLM response."""
