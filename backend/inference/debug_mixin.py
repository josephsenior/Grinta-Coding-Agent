"""Debug mixin for LLM prompt and response logging via session.jsonl wire events."""

from __future__ import annotations

from typing import Any

from backend.core.logging.session_event_logger import emit_session_event
from backend.core.prompt_role_debug import current_astep_id

MESSAGE_SEPARATOR = '\n\n----------\n\n'


class DebugMixin:
    """Mixin that adds WIRE_PROMPT / WIRE_RESPONSE session events to LLM classes."""

    def __init__(self, debug: bool = False, **kwargs: Any) -> None:
        self.debug = debug
        if kwargs:
            try:
                super().__init__(**kwargs)
            except TypeError:
                super().__init__()
        else:
            super().__init__()

    def vision_is_active(self) -> bool:
        """Return whether vision mode is active. Subclasses must override."""
        raise NotImplementedError

    def log_prompt(
        self,
        messages: Any,
        *,
        call_params: dict[str, Any] | None = None,
    ) -> None:
        """Emit WIRE_PROMPT with full messages sent to the API."""
        if not messages:
            return
        if isinstance(messages, dict):
            messages = [messages]
        payload: dict[str, Any] = {
            'astep_id': current_astep_id() or None,
            'messages': messages,
        }
        if call_params:
            payload['call_params'] = call_params
        emit_session_event('WIRE_PROMPT', payload)

    def log_response(
        self,
        response: Any,
        *,
        latency_ms: int | None = None,
    ) -> None:
        """Emit WIRE_RESPONSE with LLM output."""
        payload: dict[str, Any] = {'astep_id': current_astep_id() or None}
        if latency_ms is not None:
            payload['latency_ms'] = latency_ms
        if isinstance(response, str):
            if response:
                payload['content'] = response
                emit_session_event('WIRE_RESPONSE', payload)
            return
        if isinstance(response, dict):
            self._fill_wire_response_payload(payload, response)
            emit_session_event('WIRE_RESPONSE', payload)

    def _fill_wire_response_payload(
        self, payload: dict[str, Any], response: dict[str, Any]
    ) -> None:
        payload['raw'] = response
        choices = response.get('choices')
        if not choices:
            return
        message = choices[0].get('message', {})
        content = message.get('content') or ''
        tool_calls = message.get('tool_calls')
        content = _append_tool_calls_content(content, tool_calls)
        if content:
            payload['content'] = content
        if tool_calls:
            payload['tool_calls'] = tool_calls

    def _format_message_content(self, message: dict[str, Any]) -> str:
        """Extract and format the content field of a single message dict."""
        content = message.get('content')
        if content is None:
            return ''
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [self._format_content_element(el) for el in content]
            return '\n'.join(parts)
        return str(content)

    def _format_content_element(self, element: Any) -> str:
        """Format a single content element (text block, image_url, etc.)."""
        if not isinstance(element, dict):
            return str(element)
        if 'text' in element:
            return element['text']
        if 'image_url' in element:
            if self.vision_is_active():
                return element['image_url'].get('url', str(element))
            return str(element)
        return str(element)


def _append_tool_calls_content(content: str, tool_calls: Any) -> str:
    if not tool_calls:
        return content
    for tc in tool_calls:
        func = (
            tc.get('function')
            if isinstance(tc, dict)
            else getattr(tc, 'function', None)
        )
        if func:
            name = (
                func.get('name')
                if isinstance(func, dict)
                else getattr(func, 'name', '')
            )
            arguments = (
                func.get('arguments')
                if isinstance(func, dict)
                else getattr(func, 'arguments', '')
            )
            content += f'\nFunction call: {name}({arguments})'
    return content
