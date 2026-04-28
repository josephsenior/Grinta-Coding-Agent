"""Debug mixin for LLM prompt and response logging."""

from __future__ import annotations

import logging
from typing import Any

from backend.core.logger import app_logger as logger
from backend.core.logger import llm_prompt_logger, llm_response_logger

MESSAGE_SEPARATOR = "\n\n----------\n\n"


class DebugMixin:
    """Mixin that adds prompt/response debug logging to LLM classes."""

    def __init__(self, debug: bool = False, **kwargs: Any) -> None:
        self.debug = debug
        # Forward remaining kwargs up the MRO chain (cooperative multiple
        # inheritance).  Guard against object.__init__ which rejects keyword
        # arguments — when the chain ends at object and kwargs are still
        # present, silently drop them so subclasses don't need to pre-pop
        # every extra kwarg before calling super().
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

    def log_prompt(self, messages: Any) -> None:
        """Log the prompt messages at DEBUG level."""
        if not logger.isEnabledFor(logging.DEBUG):
            return
            
        if not messages:
            logger.debug("No completion messages!")
            return

        if isinstance(messages, dict):
            messages = [messages]

        parts: list[str] = []
        for msg in messages:
            content = self._format_message_content(msg)
            if content:
                parts.append(content)

        if not parts:
            logger.debug("No completion messages!")
            return

        llm_prompt_logger.debug(MESSAGE_SEPARATOR.join(parts))

    def log_response(self, response: Any) -> None:
        """Log the LLM response at DEBUG level."""
        if not logger.isEnabledFor(logging.DEBUG):
            return

        if isinstance(response, str):
            if response:
                llm_response_logger.debug(response)
            return

        if isinstance(response, dict):
            choices = response.get("choices")
            if not choices:
                return
            message = choices[0].get("message", {})
            content = message.get("content") or ""
            tool_calls = message.get("tool_calls")
            if tool_calls:
                for tc in tool_calls:
                    func = tc.get("function") if isinstance(tc, dict) else getattr(tc, "function", None)
                    if func:
                        name = func.get("name") if isinstance(func, dict) else getattr(func, "name", "")
                        arguments = func.get("arguments") if isinstance(func, dict) else getattr(func, "arguments", "")
                        content += f"\nFunction call: {name}({arguments})"
            if content:
                llm_response_logger.debug(content)

    def _format_message_content(self, message: dict[str, Any]) -> str:
        """Extract and format the content field of a single message dict."""
        content = message.get("content")
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [self._format_content_element(el) for el in content]
            return "\n".join(parts)
        return str(content)

    def _format_content_element(self, element: Any) -> str:
        """Format a single content element (text block, image_url, etc.)."""
        if not isinstance(element, dict):
            return str(element)
        if "text" in element:
            return element["text"]
        if "image_url" in element:
            if self.vision_is_active():
                return element["image_url"].get("url", str(element))
            return str(element)
        return str(element)
