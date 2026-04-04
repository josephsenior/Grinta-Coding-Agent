# Grinta Message Format and LLM Provider Integration

## Overview

App uses its own `Message` class (`App/core/message.py`) which provides rich content support while maintaining compatibility with major LLM provider SDKs (OpenAI, Anthropic, Google Gemini, and xAI Grok).

## Class Structure

Our `Message` class (`App/core/message.py`):

```python
class Message(BaseModel):
    role: Literal['user', 'system', 'assistant', 'tool']
    content: list[TextContent | ImageContent] = Field(default_factory=list)
    cache_enabled: bool = False
    vision_enabled: bool = False
    condensable: bool = True
    function_calling_enabled: bool = False
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    event_id: int = -1
```

## How It Works

1. **Message Creation**: Our `Message` class is a Pydantic model that supports rich content (text and images) through its `content` field.

2. **Serialization**: The class uses Pydantic's `@model_serializer` to convert messages into dictionaries that LLM providers can understand. We have two serialization methods:

   ```python
   def _string_serializer(self) -> dict:
       # convert content to a single string
       content = '\n'.join(item.text for item in self.content if isinstance(item, TextContent))
       message_dict: dict = {'content': content, 'role': self.role}
       return self._add_tool_call_keys(message_dict)

   def _list_serializer(self) -> dict:
       content: list[dict] = []
       for item in self.content:
           d = item.model_dump()
           if isinstance(item, TextContent):
               content.append(d)
           elif isinstance(item, ImageContent) and self.vision_enabled:
               content.extend(d)
       return {'content': content, 'role': self.role}
   ```

   The appropriate serializer is chosen based on the message's capabilities:

   ```python
   @model_serializer
   def serialize_model(self) -> dict:
       if self.cache_enabled or self.vision_enabled or self.function_calling_enabled:
           return self._list_serializer()
       return self._string_serializer()
   ```

3. **Tool Call Handling**: Tool calls are serialized to maintain compatibility with different LLM providers' formats (primarily following the OpenAI tool call structure).

4. **SDK Integration**: When we pass our messages to provider SDKs (like `openai.ChatCompletion`), the SDKs work with the dictionary representation. This works because:
   - Our serialization produces dictionaries that match the expected format for each provider.
   - We handle provider-specific transformations in our direct SDK client implementations.

## Note

- Compatibility is maintained through proper serialization rather than inheritance.
- Our rich content model is designed to be easily transformable into any provider-specific format.
