"""OpenCode Zen native Gemini model endpoint transport."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from backend.inference.direct_clients import (
    DirectLLMClient,
    LLMResponse,
    _normalize_timeout_seconds,
    bounded_llm_http_timeout,
    get_shared_async_http_client,
    get_shared_http_client,
)


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get('text')
                if isinstance(text, str) and text:
                    parts.append(text)
        return '\n'.join(parts)
    return str(content or '')


def _messages_to_gemini_contents(
    messages: list[dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]]]:
    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get('role') or 'user').strip().lower()
        text = _message_content_to_text(message.get('content'))
        if role == 'system':
            if text:
                system_parts.append(text)
            continue
        gemini_role = 'model' if role == 'assistant' else 'user'
        contents.append({'role': gemini_role, 'parts': [{'text': text}]})
    return ('\n\n'.join(system_parts) or None, contents)


class OpenCodeGeminiClient(DirectLLMClient):
    """Call OpenCode Zen ``/models/{model}`` Gemini-native endpoints."""

    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        endpoint_path: str,
        base_url: str | None = None,
        timeout: float | int | None = None,
        provider_name: str = 'opencode',
    ) -> None:
        self._model_name = model_name
        self._provider_name = provider_name
        self._request_timeout = _normalize_timeout_seconds(timeout)
        root = (base_url or 'https://opencode.ai/zen/v1').rstrip('/')
        if root.endswith('/v1'):
            root = root[:-3]
        self._url = f'{root}{endpoint_path}'
        self._headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }
        self._http = get_shared_http_client(provider_name, base_url)
        self._async_http = get_shared_async_http_client(provider_name, base_url)

    def _build_payload(
        self, messages: list[dict[str, Any]], kwargs: dict[str, Any]
    ) -> dict[str, Any]:
        system_instruction, contents = _messages_to_gemini_contents(messages)
        payload: dict[str, Any] = {'contents': contents}
        if system_instruction:
            payload['systemInstruction'] = {'parts': [{'text': system_instruction}]}
        generation_config: dict[str, Any] = {}
        if 'temperature' in kwargs and kwargs['temperature'] is not None:
            generation_config['temperature'] = kwargs['temperature']
        if 'max_tokens' in kwargs:
            generation_config['maxOutputTokens'] = kwargs['max_tokens']
        if 'max_completion_tokens' in kwargs:
            generation_config['maxOutputTokens'] = kwargs['max_completion_tokens']
        thinking_config = kwargs.get('thinking_config')
        if isinstance(thinking_config, dict):
            generation_config['thinkingConfig'] = thinking_config
        if generation_config:
            payload['generationConfig'] = generation_config
        return payload

    @staticmethod
    def _parse_response(data: dict[str, Any], model_name: str) -> LLMResponse:
        text_parts: list[str] = []
        for candidate in data.get('candidates') or []:
            content = candidate.get('content') if isinstance(candidate, dict) else None
            if not isinstance(content, dict):
                continue
            for part in content.get('parts') or []:
                if isinstance(part, dict) and isinstance(part.get('text'), str):
                    text_parts.append(part['text'])
        usage_meta = (
            data.get('usageMetadata')
            if isinstance(data.get('usageMetadata'), dict)
            else {}
        )
        prompt = int(usage_meta.get('promptTokenCount') or 0)
        completion = int(usage_meta.get('candidatesTokenCount') or 0)
        total = int(usage_meta.get('totalTokenCount') or prompt + completion)
        return LLMResponse(
            content='\n'.join(text_parts),
            model=model_name,
            usage={
                'prompt_tokens': prompt,
                'completion_tokens': completion,
                'total_tokens': total,
            },
            id='',
            finish_reason='stop',
            tool_calls=None,
        )

    def completion(self, messages: list[dict[str, Any]], **kwargs) -> LLMResponse:
        payload = self._build_payload(messages, kwargs)
        timeout = bounded_llm_http_timeout(self._request_timeout)
        response = self._http.post(
            self._url,
            headers=self._headers,
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError('OpenCode Gemini endpoint returned non-object JSON')
        return self._parse_response(data, self.model_name)

    async def acompletion(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> LLMResponse:
        payload = self._build_payload(messages, kwargs)
        timeout = bounded_llm_http_timeout(self._request_timeout)
        response = await self._async_http.post(
            self._url,
            headers=self._headers,
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError('OpenCode Gemini endpoint returned non-object JSON')
        return self._parse_response(data, self.model_name)

    async def astream(
        self, messages: list[dict[str, Any]], **kwargs
    ) -> AsyncIterator[dict[str, Any]]:
        result = await self.acompletion(messages, **kwargs)
        if result.content:
            yield {'choices': [{'delta': {'content': result.content}}]}
