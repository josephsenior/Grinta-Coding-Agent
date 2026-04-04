"""Message models and serialization utilities for App.

Classes:
    - ContentType: Enum of supported content kinds (text, image_url)
    - Content: Abstract base for message content with caching flag
    - TextContent: Text message content with optional cache control
    - ImageContent: One-or-more image URLs with optional cache control
    - Message: LLM message supporting text, images, tools, and caching

Key APIs:
    - serialize_model(): Pydantic serializers for content/message objects
    - contains_image: Convenience property on Message to detect images
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_serializer

from backend.core.pydantic_compat import model_dump_with_options


class ToolCallFunction(BaseModel):
    """Function call details within a tool call.

    Attributes:
        name: Name of the function to call
        arguments: JSON-formatted arguments for the function

    """

    name: str
    arguments: str


class ToolCall(BaseModel):
    """Tool call from an assistant message.

    Attributes:
        id: Unique identifier for the tool call
        type: Type of tool call (usually "function")
        function: Function call details

    """

    id: str
    type: str = 'function'
    function: ToolCallFunction


from backend.core.enums import ContentType  # noqa: E402


class Content(BaseModel):
    """Abstract base class for message content with optional caching.

    Attributes:
        type: Content type identifier
        cache_prompt: Whether to enable prompt caching for this content

    """

    type: str
    cache_prompt: bool = False

    @model_serializer(mode='plain')
    def serialize_model(
        self,
    ) -> dict[str, str | dict[str, str]] | list[dict[str, str | dict[str, str]]]:
        """Serialize content for LLM API (must be implemented by subclasses)."""
        msg = 'Subclasses should implement this method.'
        raise NotImplementedError(msg)


class TextContent(Content):
    """Text content for messages.

    Attributes:
        text: The text content

    """

    type: str = ContentType.TEXT.value
    text: str

    @model_serializer(mode='plain')
    def serialize_model(self) -> dict[str, str | dict[str, str]]:
        """Serialize text content with optional cache control."""
        data: dict[str, str | dict[str, str]] = {'type': self.type, 'text': self.text}
        if self.cache_prompt:
            data['cache_control'] = {'type': 'ephemeral'}
        return data


class ImageContent(Content):
    """Image content for messages with multiple image URLs.

    Attributes:
        image_urls: List of image URLs to include

    """

    type: str = ContentType.IMAGE_URL.value
    image_urls: list[str]

    @model_serializer(mode='plain')
    def serialize_model(self) -> list[dict[str, str | dict[str, str]]]:
        """Serialize image URLs with optional cache control on last image."""
        images: list[dict[str, str | dict[str, str]]] = [
            {'type': self.type, 'image_url': {'url': url}} for url in self.image_urls
        ]
        if self.cache_prompt and images:
            images[-1]['cache_control'] = {'type': 'ephemeral'}
        return images


class Message(BaseModel):
    """LLM message with support for text, images, function calls, and caching.

    Attributes:
        role: Message role (user/system/assistant/tool)
        content: List of content items (text/images)
        cache_enabled: Whether prompt caching is enabled
        vision_enabled: Whether vision capabilities are enabled
        function_calling_enabled: Whether function calling is enabled
        tool_calls: Tool calls from assistant messages
        tool_call_id: ID for tool response messages
        name: Optional name for the message sender
        force_string_serializer: Force string serialization format
        tool_ok: When role is tool, optional structured success/failure for
            learning and diagnostics (None = unknown / use legacy content heuristics).

    """

    role: Literal['user', 'system', 'assistant', 'tool']
    content: list[TextContent | ImageContent] = Field(default_factory=list)
    cache_enabled: bool = False
    vision_enabled: bool = False
    function_calling_enabled: bool = False
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None

    name: str | None = None
    force_string_serializer: bool = False
    tool_ok: bool | None = None

    # Rebuild the model to ensure all dependencies are properly resolved
    def __init_subclass__(cls, **kwargs):
        """Rebuild Pydantic models when subclasses are defined to refresh validators."""
        super().__init_subclass__(**kwargs)
        if hasattr(cls, 'model_rebuild'):
            cls.model_rebuild()

    @property
    def contains_image(self) -> bool:
        """Check if message contains any image content.

        Returns:
            True if message has image content

        """
        return any(isinstance(content, ImageContent) for content in self.content)

    @model_serializer(mode='plain')
    def serialize_model(self) -> dict[str, Any]:
        """Serialize message for LLM API.

        Uses list serializer for advanced features (caching, vision, tools),
        string serializer for simple text-only messages.

        Returns:
            Serialized message dictionary

        """
        if not self.force_string_serializer and (
            self.cache_enabled or self.vision_enabled or self.function_calling_enabled
        ):
            return self._list_serializer()
        return self._string_serializer()

    def _string_serializer(self) -> dict[str, Any]:
        content = '\n'.join(
            item.text for item in self.content if isinstance(item, TextContent)
        )
        message_dict: dict[str, Any] = {'content': content, 'role': self.role}
        return self._add_tool_call_keys(message_dict)

    def _list_serializer(self) -> dict[str, Any]:
        content: list[dict[str, Any]] = []
        role_tool_with_prompt_caching = False

        for item in self.content:
            d = model_dump_with_options(item)
            role_tool_with_prompt_caching = self._process_item_caching(
                item, d, role_tool_with_prompt_caching
            )
            self._add_item_to_content(item, d, content)

        message_dict: dict[str, Any] = {'content': content, 'role': self.role}
        if role_tool_with_prompt_caching:
            message_dict['cache_control'] = {'type': 'ephemeral'}
        return self._add_tool_call_keys(message_dict)

    def _process_item_caching(
        self, item: Any, d: dict, role_tool_with_prompt_caching: bool
    ) -> bool:
        """Process caching for tool items."""
        if self.role == 'tool' and item.cache_prompt:
            role_tool_with_prompt_caching = True
            if isinstance(item, TextContent):
                d.pop('cache_control', None)
            elif isinstance(item, ImageContent):
                self._remove_cache_control_from_image_content(d)
        return role_tool_with_prompt_caching

    def _remove_cache_control_from_image_content(self, d: dict) -> None:
        """Remove cache_control from image content items."""
        if hasattr(d, '__iter__'):
            for d_item in d:
                if hasattr(d_item, 'pop'):
                    d_item.pop('cache_control', None)

    def _add_item_to_content(
        self, item: Any, d: dict, content: list[dict[str, Any]]
    ) -> None:
        """Add item to content list based on type."""
        if isinstance(item, TextContent):
            content.append(d)
        elif isinstance(item, ImageContent) and self.vision_enabled:
            content.extend([d] if isinstance(d, dict) else d)

    def _add_tool_call_keys(self, message_dict: dict[str, Any]) -> dict[str, Any]:
        """Add tool call keys if we have a tool call or response.

        NOTE: this is necessary for both native and non-native tool calling
        """
        if self.tool_calls is not None:
            message_dict['tool_calls'] = [
                {
                    'id': tool_call.id,
                    'type': 'function',
                    'function': {
                        'name': tool_call.function.name,
                        'arguments': tool_call.function.arguments,
                    },
                }
                for tool_call in self.tool_calls
            ]
        if self.tool_call_id is not None:
            assert self.name is not None, (
                'name is required when tool_call_id is not None'
            )
            message_dict['tool_call_id'] = self.tool_call_id
            message_dict['name'] = self.name
            if self.role == 'tool' and self.tool_ok is not None:
                message_dict['tool_ok'] = self.tool_ok
        return message_dict


# Rebuild the Message model to ensure ToolCall is properly resolved
Message.model_rebuild()
