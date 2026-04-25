"""Messaging-related action types including user, system, and streaming chunks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

import backend
from backend.core.enums import ActionSecurityRisk
from backend.core.schemas import ActionType
from backend.ledger.action.action import Action


@dataclass
class MessageAction(Action):
    """Action to send a message (agent to user or user to agent).

    Attributes:
        content: Message text content
        thought: Inner ``<think>...</think>`` text (CLI shows dim; stripped from ``content``).
        file_urls: URLs of attached files
        image_urls: URLs of attached images
        wait_for_response: Whether to wait for user response

    """

    content: str = ''
    thought: str = ''
    file_urls: list[str] | None = None
    image_urls: list[str] | None = None
    wait_for_response: bool = False
    suppress_cli: bool = False
    action: ClassVar[str] = ActionType.MESSAGE
    security_risk: ActionSecurityRisk = ActionSecurityRisk.UNKNOWN

    @property
    def message(self) -> str:
        """Get message content."""
        return self.content

    def __str__(self) -> str:
        """Return a readable summary including content and attachments."""
        ret = f'**MessageAction** (source={self.source})\n'
        ret += f'CONTENT: {self.content}'
        if self.image_urls:
            for url in self.image_urls:
                ret += f'\nIMAGE_URL: {url}'
        if self.file_urls:
            for url in self.file_urls:
                ret += f'\nFILE_URL: {url}'
        return ret


@dataclass
class SystemMessageAction(Action):
    """System message for agent with system prompt and tools.

    This should be the first message in the event stream.
    """

    content: str = ''
    tools: list[Any] | None = None
    APP_version: str | None = backend.__version__
    agent_class: str | None = None
    action: ClassVar[str] = ActionType.SYSTEM

    @property
    def message(self) -> str:
        """Get system message content."""
        return self.content

    def __str__(self) -> str:
        """Return a readable summary including tools and agent metadata."""
        ret = f'**SystemMessageAction** (source={self.source})\n'
        ret += f'CONTENT: {self.content}'
        if self.tools:
            ret += f'\nTOOLS: {len(self.tools)} tools available'
        if self.agent_class:
            ret += f'\nAGENT_CLASS: {self.agent_class}'
        return ret


@dataclass
class StreamingChunkAction(Action):
    """Streaming chunk from LLM for real-time token display.

    Emitted during LLM streaming to show tokens as they arrive,
    providing instant feedback (ChatGPT/Cursor style).
    """

    chunk: str = ''  # The new token/chunk text
    accumulated: str = ''  # All text accumulated so far
    is_final: bool = False  # True when streaming is complete
    is_tool_call: bool = False  # True when streaming tool call arguments (not content)
    tool_call_name: str = ''  # Name of the tool being called (e.g. "execute_bash")
    thinking_chunk: str = ''  # New thinking/reasoning token from the model
    thinking_accumulated: str = ''  # All thinking text accumulated so far
    action: ClassVar[str] = ActionType.STREAMING_CHUNK
    runnable: ClassVar[bool] = False  # Not executable, just informational

    def __str__(self) -> str:
        """Return a concise description of streaming progress."""
        status = 'FINAL' if self.is_final else 'STREAMING'
        char_count = len(self.accumulated)
        return f'**StreamingChunkAction** ({status}) - {char_count} chars'
