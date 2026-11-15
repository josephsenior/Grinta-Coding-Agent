"""Parsing helpers for executor streaming responses."""

from __future__ import annotations

from typing import Any

from backend.engine.executor_mixins._executor_types import _AsyncStreamingState


def _reasoning_detail_item_text(item: Any) -> str:
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return ''
    detail_type = str(item.get('type') or '').lower()
    if 'encrypted' in detail_type:
        return ''
    for key in ('text', 'summary', 'content'):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return ''


class _ExecutorStreamingParsingMixin:
    """Parsing helpers shared by the streaming executor mixin."""

    @staticmethod
    def _is_reasoning_content_part(part: Any) -> bool:
        if isinstance(part, str) or not isinstance(part, dict):
            return False
        part_type = str(part.get('type') or '').lower()
        if 'reasoning' in part_type or part_type == 'thinking':
            return True
        if part.get('thought') is True or part.get('thinking') is True:
            return True
        return False

    @staticmethod
    def _separate_reasoning_item(
        state: _AsyncStreamingState,
        reasoning_item_id: str,
    ) -> None:
        if (
            reasoning_item_id
            and state.last_reasoning_item_id
            and reasoning_item_id != state.last_reasoning_item_id
            and state.thinking_accumulate
            and not state.thinking_accumulate.endswith('\n')
        ):
            state.thinking_accumulate += '\n'

    @staticmethod
    def _extract_reasoning_details_text(details: Any) -> str:
        if not isinstance(details, list):
            return ''

        parts: list[str] = []
        for item in details:
            text = _reasoning_detail_item_text(item)
            if text:
                parts.append(text)
        return ''.join(parts)

    @classmethod
    def _extract_reasoning_from_content_parts(cls, content_parts: list[Any]) -> str:
        parts: list[str] = []
        for part in content_parts:
            if not cls._is_reasoning_content_part(part):
                continue
            if isinstance(part, str):
                parts.append(part)
                continue
            for key in ('text', 'summary', 'content', 'reasoning'):
                value = part.get(key)
                if isinstance(value, str) and value:
                    parts.append(value)
                    break
        return ''.join(parts)

    @classmethod
    def _extract_delta_reasoning(cls, delta: dict[str, Any]) -> str:
        for alt_key in ('reasoning_content', 'reasoning', 'thinking'):
            alt_val = delta.get(alt_key)
            if isinstance(alt_val, str) and alt_val:
                return alt_val

        details_text = cls._extract_reasoning_details_text(
            delta.get('reasoning_details')
        )
        if details_text:
            return details_text

        delta_content = delta.get('content')
        if isinstance(delta_content, list):
            reasoning_text = cls._extract_reasoning_from_content_parts(delta_content)
            if reasoning_text:
                return reasoning_text
        return ''

    @classmethod
    def _extract_delta_text(cls, delta: dict[str, Any]) -> str:
        delta_content = delta.get('content')
        if isinstance(delta_content, str):
            return delta_content
        if not isinstance(delta_content, list):
            return ''

        parts: list[str] = []
        for part in delta_content:
            if cls._is_reasoning_content_part(part):
                continue
            if isinstance(part, str):
                parts.append(part)
                continue
            if not isinstance(part, dict):
                continue
            maybe_text = part.get('text')
            if isinstance(maybe_text, str):
                parts.append(maybe_text)
        return ''.join(parts)

    @staticmethod
    def _extract_fallback_message(fallback: Any) -> Any | None:
        choices = getattr(fallback, 'choices', None)
        if not isinstance(choices, list) or not choices:
            return None
        first_choice = choices[0]
        if isinstance(first_choice, dict):
            return first_choice.get('message')
        return getattr(first_choice, 'message', None)

    @classmethod
    def _extract_fallback_reasoning(
        cls,
        fallback: Any,
        fallback_message: Any | None,
    ) -> str:
        for candidate in (fallback_message, fallback):
            if candidate is None:
                continue
            for key in ('reasoning_content', 'reasoning', 'thinking'):
                reasoning = (
                    candidate.get(key)
                    if isinstance(candidate, dict)
                    else getattr(candidate, key, None)
                )
                if isinstance(reasoning, str) and reasoning:
                    return reasoning
            details = (
                candidate.get('reasoning_details')
                if isinstance(candidate, dict)
                else getattr(candidate, 'reasoning_details', None)
            )
            details_text = cls._extract_reasoning_details_text(details)
            if details_text:
                return details_text
        return ''

    @staticmethod
    def _extract_fallback_tool_calls(
        fallback: Any,
        fallback_message: Any | None,
    ) -> list[dict[str, Any]]:
        fallback_tool_calls = getattr(fallback, 'tool_calls', None)
        if not isinstance(fallback_tool_calls, list) and fallback_message is not None:
            if isinstance(fallback_message, dict):
                maybe_tool_calls = fallback_message.get('tool_calls')
            else:
                maybe_tool_calls = getattr(fallback_message, 'tool_calls', None)
            if isinstance(maybe_tool_calls, list):
                fallback_tool_calls = maybe_tool_calls
        return fallback_tool_calls if isinstance(fallback_tool_calls, list) else []

    @staticmethod
    def _merge_stream_fragment(existing: str, incoming: str) -> str:
        r"""Merge streamed fragments with safe append-only defaults."""
        if not incoming:
            return existing
        if not existing:
            return incoming
        if incoming == existing:
            return existing
        if len(incoming) > len(existing) and incoming.startswith(existing):
            return incoming
        if (
            len(existing) >= 2
            and existing[-1:] in ('}', ']')
            and len(incoming) > len(existing)
            and incoming.startswith(existing[:-1])
        ):
            return incoming
        return existing + incoming

    @staticmethod
    def _visible_stream_content(content_accumulate: str) -> str:
        from backend.cli.display.tool_call_display import (
            redact_streamed_tool_call_markers,
        )

        return redact_streamed_tool_call_markers(content_accumulate).strip()

    def _resolve_stream_usage(
        self,
        call_params: dict[str, Any],
        visible_accum: str,
        tool_calls_list: list[dict[str, Any]] | None,
        streamed_usage: dict[str, int] | None,
    ) -> dict[str, Any]:
        if streamed_usage:
            return streamed_usage

        from backend.inference.llm.utils import get_token_count

        estimated_prompt = get_token_count(call_params.get('messages') or [])
        estimated_completion = get_token_count(
            [{'role': 'assistant', 'content': visible_accum or ''}]
        )
        if tool_calls_list:
            tool_payload: list[dict[str, Any]] = []
            for tool_call in tool_calls_list:
                function = tool_call.get('function', {})
                tool_payload.append(
                    {
                        'role': 'assistant',
                        'content': '',
                        'tool_calls': [
                            {
                                'function': {
                                    'name': function.get('name', ''),
                                    'arguments': function.get('arguments', ''),
                                }
                            }
                        ],
                    }
                )
            estimated_completion += get_token_count(tool_payload)
        return {
            'prompt_tokens': estimated_prompt,
            'completion_tokens': estimated_completion,
            'total_tokens': estimated_prompt + estimated_completion,
            'is_estimated': True,
        }
