"""ChatGPT-authenticated Codex models as a Grinta-owned LLM provider.

Codex App Server is used only for its supported managed OAuth and model
catalog surfaces. Model inference goes directly through the Responses endpoint
used by ChatGPT-authenticated Codex clients, so Grinta owns the agent loop,
tool execution, approvals, transcript, and conversation state.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import threading
import webbrowser
from collections import OrderedDict
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI, OpenAI

from backend.inference.clients.base import (
    DirectLLMClient,
    LLMResponse,
    get_shared_async_http_client,
    get_shared_http_client,
)

_CODEX_RESPONSES_BASE_URL = 'https://chatgpt.com/backend-api/codex'
_FALLBACK_INSTRUCTIONS = (
    'You are the language model inside the Grinta agent harness. Follow the '
    'supplied instructions and use only the tools provided by Grinta.'
)
_MAX_REASONING_REPLAY_ENTRIES = 256


class CodexAppServerError(RuntimeError):
    """Raised when Codex authentication or inference cannot complete."""


def _find_codex_executable() -> str | None:
    """Resolve the Codex CLI across Windows package formats.

    The desktop installer exposes ``codex.exe``, while npm-based installs
    commonly expose ``codex.cmd``. Looking up only the latter makes a valid
    desktop installation invisible to Grinta.
    """
    names = (
        ('codex.cmd', 'codex.exe', 'codex') if sys.platform == 'win32' else ('codex',)
    )
    for name in names:
        executable = shutil.which(name)
        if executable:
            return executable
    return None


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _model_dump(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    dump = getattr(value, 'model_dump', None)
    if callable(dump):
        try:
            return dump(mode='json', exclude_none=True)
        except TypeError:
            return dump(exclude_none=True)
    return {}


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content or '')
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        text = item.get('text')
        if isinstance(text, str) and text:
            parts.append(text)
    return '\n'.join(parts)


def _message_content_parts(content: Any, *, assistant: bool) -> list[dict[str, Any]]:
    text_type = 'output_text' if assistant else 'input_text'
    if isinstance(content, str):
        return [{'type': text_type, 'text': content}] if content else []
    if not isinstance(content, list):
        text = str(content or '')
        return [{'type': text_type, 'text': text}] if text else []

    parts: list[dict[str, Any]] = []
    for item in content:
        if isinstance(item, str):
            if item:
                parts.append({'type': text_type, 'text': item})
            continue
        if not isinstance(item, dict):
            continue
        text = item.get('text')
        if isinstance(text, str) and text:
            parts.append({'type': text_type, 'text': text})
            continue
        if assistant:
            continue
        image_url = item.get('image_url')
        if isinstance(image_url, dict):
            image_url = image_url.get('url')
        if not image_url:
            urls = item.get('image_urls')
            if isinstance(urls, list):
                for url in urls:
                    if url:
                        parts.append({'type': 'input_image', 'image_url': str(url)})
            continue
        parts.append({'type': 'input_image', 'image_url': str(image_url)})
    return parts


def _responses_tools(tools: Any) -> list[dict[str, Any]]:
    if not isinstance(tools, list):
        return []
    converted: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if tool.get('type') != 'function':
            converted.append(dict(tool))
            continue
        function = tool.get('function')
        if not isinstance(function, dict) or not function.get('name'):
            continue
        converted.append(
            {
                'type': 'function',
                'name': str(function['name']),
                'description': str(function.get('description') or ''),
                'parameters': function.get('parameters')
                or {
                    'type': 'object',
                    'properties': {},
                },
                **(
                    {'strict': bool(function['strict'])} if 'strict' in function else {}
                ),
            }
        )
    return converted


def _responses_tool_choice(tool_choice: Any) -> Any:
    if not isinstance(tool_choice, dict):
        return tool_choice
    function = tool_choice.get('function')
    if tool_choice.get('type') == 'function' and isinstance(function, dict):
        name = function.get('name')
        if name:
            return {'type': 'function', 'name': str(name)}
    return tool_choice


def _usage_dict(usage: Any) -> dict[str, int]:
    if usage is None:
        return {
            'prompt_tokens': 0,
            'completion_tokens': 0,
            'reasoning_tokens': 0,
            'total_tokens': 0,
        }
    input_tokens = int(_get(usage, 'input_tokens', 0) or 0)
    output_tokens = int(_get(usage, 'output_tokens', 0) or 0)
    total_tokens = int(_get(usage, 'total_tokens', 0) or 0)
    output_details = _get(usage, 'output_tokens_details') or {}
    reasoning_tokens = int(_get(output_details, 'reasoning_tokens', 0) or 0)
    return {
        'prompt_tokens': input_tokens,
        'completion_tokens': output_tokens,
        'reasoning_tokens': reasoning_tokens,
        'total_tokens': total_tokens or input_tokens + output_tokens,
    }


def _response_text(output: Any) -> str:
    parts: list[str] = []
    for item in output or []:
        if _get(item, 'type') != 'message':
            continue
        for content in _get(item, 'content', []) or []:
            if _get(content, 'type') not in {'output_text', 'text'}:
                continue
            text = _get(content, 'text')
            if isinstance(text, str) and text:
                parts.append(text)
    return '\n'.join(parts)


def _response_reasoning(output: Any) -> str:
    parts: list[str] = []
    for item in output or []:
        if _get(item, 'type') != 'reasoning':
            continue
        for summary in _get(item, 'summary', []) or []:
            text = _get(summary, 'text')
            if isinstance(text, str) and text:
                parts.append(text)
    return '\n'.join(parts)


def _response_tool_calls(output: Any) -> list[dict[str, Any]] | None:
    calls: list[dict[str, Any]] = []
    for item in output or []:
        if _get(item, 'type') != 'function_call':
            continue
        name = _get(item, 'name')
        call_id = _get(item, 'call_id') or _get(item, 'id')
        if not name or not call_id:
            continue
        calls.append(
            {
                'id': str(call_id),
                'type': 'function',
                'function': {
                    'name': str(name),
                    'arguments': str(_get(item, 'arguments') or '{}'),
                },
            }
        )
    return calls or None


def _reasoning_replay_item(item: Any) -> dict[str, Any] | None:
    dumped = _model_dump(item)
    encrypted = dumped.get('encrypted_content')
    if dumped.get('type') != 'reasoning' or not encrypted:
        return None
    replay: dict[str, Any] = {
        'type': 'reasoning',
        'encrypted_content': encrypted,
    }
    summary = dumped.get('summary')
    if isinstance(summary, list):
        replay['summary'] = summary
    return replay


def _item_call_id(item: Any) -> str:
    return str(_get(item, 'call_id') or _get(item, 'id') or '')


def _done_item_arguments(
    item: Any,
    tool_index: int,
    streamed_arguments: set[int],
) -> str:
    if tool_index in streamed_arguments:
        return ''
    return str(_get(item, 'arguments') or '')


class CodexResponsesClient(DirectLLMClient):
    """Use Codex OAuth credits while Grinta owns the complete agent harness."""

    def __init__(
        self,
        model_name: str = 'default',
        *,
        timeout: float | int | None = None,
    ) -> None:
        self._model_name = model_name
        self._timeout = float(timeout) if timeout else None
        self._process: subprocess.Popen[str] | None = None
        self._next_id = 1
        self._auth_lock = threading.Lock()
        self._default_model: str | None = None
        self._reasoning_by_call_id: OrderedDict[str, list[dict[str, Any]]] = (
            OrderedDict()
        )

    def completion(self, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        token, account_id = self._credentials()
        client = self._sync_responses_client(token, account_id)
        payload = self._build_payload(messages, kwargs)
        response = self._collect_sync_response(
            client.responses.create(**payload, stream=True)
        )
        return self._to_llm_response(response)

    async def acompletion(
        self, messages: list[dict[str, Any]], **kwargs: Any
    ) -> LLMResponse:
        token, account_id = await asyncio.to_thread(self._credentials)
        client = self._async_responses_client(token, account_id)
        payload = self._build_payload(messages, kwargs)
        stream = await client.responses.create(**payload, stream=True)
        response = await self._collect_async_response(stream)
        return self._to_llm_response(response)

    async def astream(
        self, messages: list[dict[str, Any]], **kwargs: Any
    ) -> AsyncIterator[dict[str, Any]]:
        token, account_id = await asyncio.to_thread(self._credentials)
        client = self._async_responses_client(token, account_id)
        payload = self._build_payload(messages, kwargs)
        payload['stream'] = True
        stream = await client.responses.create(**payload)

        response_id = ''
        reasoning_items: list[dict[str, Any]] = []
        call_ids: list[str] = []
        tool_indexes: dict[int, int] = {}
        tool_item_indexes: dict[str, int] = {}
        streamed_arguments: set[int] = set()

        async for event in stream:
            event_type = str(_get(event, 'type') or '')
            event_response = _get(event, 'response')
            if event_response is not None:
                response_id = str(_get(event_response, 'id') or response_id)

            if event_type == 'response.completed':
                chunk, response_id = self._stream_completed_chunk(
                    event,
                    response_id,
                    call_ids,
                    reasoning_items,
                )
                if chunk is not None:
                    yield chunk
                break

            chunk = self._stream_event_chunk(
                event,
                event_type,
                response_id,
                tool_indexes,
                tool_item_indexes,
                call_ids,
                streamed_arguments,
                reasoning_items,
            )
            if chunk is not None:
                yield chunk

    def _stream_event_chunk(
        self,
        event: Any,
        event_type: str,
        response_id: str,
        tool_indexes: dict[int, int],
        tool_item_indexes: dict[str, int],
        call_ids: list[str],
        streamed_arguments: set[int],
        reasoning_items: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if event_type == 'response.output_text.delta':
            return self._stream_text_delta_chunk(event, response_id)
        if event_type in {
            'response.reasoning_summary_text.delta',
            'response.reasoning_text.delta',
        }:
            return self._stream_reasoning_delta_chunk(event, response_id)
        if event_type == 'response.output_item.added':
            return self._stream_output_item_added_chunk(
                event,
                response_id,
                tool_indexes,
                tool_item_indexes,
                call_ids,
            )
        if event_type == 'response.function_call_arguments.delta':
            return self._stream_arguments_delta_chunk(
                event,
                response_id,
                tool_indexes,
                tool_item_indexes,
                streamed_arguments,
            )
        if event_type == 'response.output_item.done':
            return self._stream_output_item_done_chunk(
                event,
                response_id,
                tool_indexes,
                streamed_arguments,
                call_ids,
                reasoning_items,
            )
        return None

    def _stream_completed_chunk(
        self,
        event: Any,
        response_id: str,
        call_ids: list[str],
        reasoning_items: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, str]:
        completed = _get(event, 'response')
        if completed is None:
            return None, response_id
        response_id = str(_get(completed, 'id') or response_id)
        self._cache_reasoning_items(
            _get(completed, 'output') or [],
            call_ids=call_ids,
            extra_reasoning=reasoning_items,
        )
        return (
            {
                'id': response_id,
                'usage': _usage_dict(_get(completed, 'usage')),
            },
            response_id,
        )

    def _stream_text_delta_chunk(
        self, event: Any, response_id: str
    ) -> dict[str, Any] | None:
        delta = _get(event, 'delta')
        if not isinstance(delta, str) or not delta:
            return None
        return {
            'id': response_id,
            'choices': [{'delta': {'content': delta}}],
        }

    def _stream_reasoning_delta_chunk(
        self, event: Any, response_id: str
    ) -> dict[str, Any] | None:
        delta = _get(event, 'delta')
        if not isinstance(delta, str) or not delta:
            return None
        return {
            'id': response_id,
            'choices': [
                {
                    'delta': {
                        'reasoning_content': delta,
                        '_reasoning_item_id': str(_get(event, 'item_id') or ''),
                    }
                }
            ],
        }

    def _stream_output_item_added_chunk(
        self,
        event: Any,
        response_id: str,
        tool_indexes: dict[int, int],
        tool_item_indexes: dict[str, int],
        call_ids: list[str],
    ) -> dict[str, Any] | None:
        item = _get(event, 'item')
        if _get(item, 'type') != 'function_call':
            return None
        output_index = int(_get(event, 'output_index', 0) or 0)
        tool_index = len(tool_indexes)
        tool_indexes[output_index] = tool_index
        item_id = str(_get(item, 'id') or '')
        if item_id:
            tool_item_indexes[item_id] = tool_index
        call_id = str(_get(item, 'call_id') or item_id)
        if call_id:
            call_ids.append(call_id)
        return self._tool_call_chunk(
            response_id=response_id,
            index=tool_index,
            call_id=call_id,
            name=str(_get(item, 'name') or ''),
            arguments='',
        )

    def _stream_arguments_delta_chunk(
        self,
        event: Any,
        response_id: str,
        tool_indexes: dict[int, int],
        tool_item_indexes: dict[str, int],
        streamed_arguments: set[int],
    ) -> dict[str, Any] | None:
        output_index = int(_get(event, 'output_index', 0) or 0)
        tool_index: int | None = tool_indexes.get(output_index)
        if tool_index is None:
            item_id = str(_get(event, 'item_id') or '')
            tool_index = tool_item_indexes.get(item_id)
        if tool_index is None:
            tool_index = len(tool_indexes)
            tool_indexes[output_index] = tool_index
        delta = _get(event, 'delta')
        if not isinstance(delta, str) or not delta:
            return None
        streamed_arguments.add(tool_index)
        return self._tool_call_chunk(
            response_id=response_id,
            index=tool_index,
            arguments=delta,
        )

    def _stream_output_item_done_chunk(
        self,
        event: Any,
        response_id: str,
        tool_indexes: dict[int, int],
        streamed_arguments: set[int],
        call_ids: list[str],
        reasoning_items: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        item = _get(event, 'item')
        item_type = _get(item, 'type')
        if item_type == 'reasoning':
            replay = _reasoning_replay_item(item)
            if replay is not None:
                reasoning_items.append(replay)
            return None
        if item_type != 'function_call':
            return None
        return self._function_call_done_chunk(
            event,
            response_id,
            tool_indexes,
            streamed_arguments,
            call_ids,
        )

    def _function_call_done_chunk(
        self,
        event: Any,
        response_id: str,
        tool_indexes: dict[int, int],
        streamed_arguments: set[int],
        call_ids: list[str],
    ) -> dict[str, Any] | None:
        item = _get(event, 'item')
        output_index = int(_get(event, 'output_index', 0) or 0)
        tool_index: int | None = tool_indexes.get(output_index)
        if tool_index is None:
            tool_index = len(tool_indexes)
            tool_indexes[output_index] = tool_index
        call_id = _item_call_id(item)
        if call_id and call_id not in call_ids:
            call_ids.append(call_id)
        name = str(_get(item, 'name') or '')
        arguments = _done_item_arguments(item, tool_index, streamed_arguments)
        if not name and not arguments:
            return None
        return self._tool_call_chunk(
            response_id=response_id,
            index=tool_index,
            call_id=call_id,
            name=name,
            arguments=arguments,
        )

    def close(self) -> None:
        process = self._process
        self._process = None
        if process and process.poll() is None:
            process.terminate()

    def ensure_authenticated(self) -> None:
        """Complete managed ChatGPT login and validate readable OAuth state."""
        self._credentials()

    def list_available_models(self) -> list[str]:
        """Return this signed-in account's picker-visible Codex model ids."""
        with self._auth_lock:
            self._ensure_started()
            self._ensure_authenticated_locked()
            cursor: str | None = None
            models: list[str] = []
            while True:
                result = self._request(
                    'model/list', {'cursor': cursor, 'includeHidden': False}
                )
                for item in result.get('data') or []:
                    if not isinstance(item, dict):
                        continue
                    model = str(item.get('model') or item.get('id') or '').strip()
                    if not model:
                        continue
                    if item.get('isDefault'):
                        self._default_model = model
                    if model not in models:
                        models.append(model)
                cursor_value = result.get('nextCursor')
                cursor = str(cursor_value).strip() if cursor_value else None
                if not cursor:
                    if self._default_model is None and models:
                        self._default_model = models[0]
                    return models

    def _credentials(self) -> tuple[str, str]:
        with self._auth_lock:
            auth_path = self._codex_home() / 'auth.json'
            credentials = self._read_file_credentials(auth_path)
            if credentials is not None:
                return credentials

            self._ensure_started()
            self._ensure_authenticated_locked()
            credentials = self._read_file_credentials(auth_path)
            if credentials is not None:
                return credentials
            raise CodexAppServerError(
                'Codex OAuth credentials are incomplete. Sign out of Codex '
                'and select the Codex provider in Grinta to sign in again.'
            )

    @staticmethod
    def _read_file_credentials(auth_path: Path) -> tuple[str, str] | None:
        """Read a complete explicit OAuth record without consulting OS keyrings."""
        if not auth_path.is_file():
            return None
        try:
            auth = json.loads(auth_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            raise CodexAppServerError(
                'Codex OAuth credential store is not readable at '
                f'{auth_path}. Configure Codex to use its file credential '
                'store and sign in again.'
            ) from exc
        tokens = auth.get('tokens') or {}
        access_token = str(tokens.get('access_token') or '').strip()
        account_id = str(tokens.get('account_id') or '').strip()
        if access_token and account_id:
            return access_token, account_id
        return None

    def _ensure_authenticated_locked(self) -> None:
        account = self._request('account/read', {'refreshToken': True})
        if (account.get('account') or {}).get('type') == 'chatgpt':
            return
        self._start_chatgpt_login()

    def _ensure_started(self) -> None:
        if self._process and self._process.poll() is None:
            return
        executable = _find_codex_executable()
        if not executable:
            raise CodexAppServerError(
                'Codex CLI is required to manage ChatGPT OAuth. Install Codex, '
                'then select the Codex provider again.'
            )
        self._process = subprocess.Popen(
            [
                executable,
                'app-server',
                '--stdio',
                '--config',
                'cli_auth_credentials_store="file"',
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            bufsize=1,
            cwd=os.getcwd(),
        )
        self._request(
            'initialize',
            {'clientInfo': {'name': 'grinta', 'title': 'Grinta', 'version': '1.0'}},
        )
        self._notify('initialized', {})

    def _start_chatgpt_login(self) -> None:
        login = self._request(
            'account/login/start',
            {
                'type': 'chatgpt',
                'useHostedLoginSuccessPage': True,
                'appBrand': 'codex',
            },
        )
        auth_url = str(login.get('authUrl') or '')
        login_id = str(login.get('loginId') or '')
        if not auth_url or not login_id:
            raise CodexAppServerError('Codex did not provide a ChatGPT login URL.')
        if not webbrowser.open(auth_url, new=2):
            raise CodexAppServerError(
                f'Open this URL to sign in with ChatGPT, then retry: {auth_url}'
            )
        while True:
            message = self._read()
            if message.get('method') != 'account/login/completed':
                continue
            params = message.get('params') or {}
            if str(params.get('loginId') or '') != login_id:
                continue
            if not params.get('success'):
                raise CodexAppServerError(
                    f'ChatGPT sign-in did not complete: '
                    f'{params.get("error") or "cancelled"}'
                )
            account = self._request('account/read', {'refreshToken': True})
            if (account.get('account') or {}).get('type') == 'chatgpt':
                return
            raise CodexAppServerError(
                'ChatGPT sign-in completed, but Codex has no active ChatGPT account.'
            )

    def _resolved_model_name(self) -> str:
        if self._model_name != 'default':
            return self._model_name
        if self._default_model:
            return self._default_model
        models = self.list_available_models()
        if models:
            return self._default_model or models[0]
        raise CodexAppServerError(
            'The signed-in Codex account did not advertise a default model.'
        )

    def _default_headers(self, account_id: str) -> dict[str, str]:
        return {
            'ChatGPT-Account-ID': account_id,
            'OpenAI-Beta': 'responses=v1',
            'originator': 'grinta',
            'User-Agent': 'grinta/1.0',
        }

    def _sync_responses_client(self, token: str, account_id: str) -> OpenAI:
        return OpenAI(
            api_key=token,
            base_url=_CODEX_RESPONSES_BASE_URL,
            default_headers=self._default_headers(account_id),
            http_client=get_shared_http_client(
                'codex-oauth', _CODEX_RESPONSES_BASE_URL
            ),
        )

    def _async_responses_client(self, token: str, account_id: str) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=token,
            base_url=_CODEX_RESPONSES_BASE_URL,
            default_headers=self._default_headers(account_id),
            http_client=get_shared_async_http_client(
                'codex-oauth', _CODEX_RESPONSES_BASE_URL
            ),
        )

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        instructions, input_items = self._messages_to_responses_input(messages)
        payload: dict[str, Any] = {
            'model': self._resolved_model_name(),
            'instructions': instructions or _FALLBACK_INSTRUCTIONS,
            'input': input_items,
            'store': False,
            'include': ['reasoning.encrypted_content'],
        }

        tools = _responses_tools(kwargs.get('tools'))
        if tools:
            payload['tools'] = tools
            payload['tool_choice'] = _responses_tool_choice(
                kwargs.get('tool_choice', 'auto')
            )
            if 'parallel_tool_calls' in kwargs:
                payload['parallel_tool_calls'] = bool(kwargs['parallel_tool_calls'])

        effort = str(kwargs.get('reasoning_effort') or '').strip().lower()
        payload['reasoning'] = {
            **({'effort': effort} if effort else {}),
            'summary': 'detailed',
        }

        # The ChatGPT Codex Responses gateway requires streaming and rejects
        # max_output_tokens. Grinta's executor remains responsible for its
        # normal run/token boundaries for this provider.
        if kwargs.get('timeout') is not None:
            payload['timeout'] = kwargs['timeout']
        return payload

    def _messages_to_responses_input(
        self, messages: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]]]:
        instructions: list[str] = []
        input_items: list[dict[str, Any]] = []
        for message in messages:
            role = str(message.get('role') or 'user').strip().lower()
            if role in {'system', 'developer'}:
                text = _content_text(message.get('content'))
                if text:
                    instructions.append(text)
                continue

            if role == 'tool':
                call_id = message.get('tool_call_id') or message.get('id')
                if call_id:
                    input_items.append(
                        {
                            'type': 'function_call_output',
                            'call_id': str(call_id),
                            'output': _content_text(message.get('content')),
                        }
                    )
                continue

            if role == 'assistant':
                tool_calls = message.get('tool_calls')
                if isinstance(tool_calls, list) and tool_calls:
                    self._append_reasoning_replay(input_items, tool_calls)
                    for tool_call in tool_calls:
                        if not isinstance(tool_call, dict):
                            continue
                        function = tool_call.get('function') or {}
                        call_id = tool_call.get('id')
                        name = function.get('name')
                        if not call_id or not name:
                            continue
                        input_items.append(
                            {
                                'type': 'function_call',
                                'call_id': str(call_id),
                                'name': str(name),
                                'arguments': str(function.get('arguments') or '{}'),
                            }
                        )
                content = _message_content_parts(message.get('content'), assistant=True)
                if content:
                    input_items.append(
                        {'type': 'message', 'role': 'assistant', 'content': content}
                    )
                continue

            content = _message_content_parts(message.get('content'), assistant=False)
            if content:
                input_items.append(
                    {'type': 'message', 'role': 'user', 'content': content}
                )
        return '\n\n'.join(instructions), input_items

    def _append_reasoning_replay(
        self,
        input_items: list[dict[str, Any]],
        tool_calls: list[Any],
    ) -> None:
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            call_id = str(tool_call.get('id') or '')
            reasoning_items = self._reasoning_by_call_id.get(call_id)
            if reasoning_items:
                input_items.extend(dict(item) for item in reasoning_items)
                self._reasoning_by_call_id.move_to_end(call_id)
                return

    def _to_llm_response(self, response: Any) -> LLMResponse:
        output = _get(response, 'output') or []
        self._cache_reasoning_items(output)
        tool_calls = _response_tool_calls(output)
        return LLMResponse(
            content=_response_text(output),
            model=str(_get(response, 'model') or self._resolved_model_name()),
            usage=_usage_dict(_get(response, 'usage')),
            response_id=str(_get(response, 'id') or ''),
            finish_reason='tool_calls'
            if tool_calls
            else str(_get(response, 'status') or 'stop'),
            tool_calls=tool_calls,
            reasoning_content=_response_reasoning(output),
        )

    def _collect_sync_response(self, stream: Any) -> dict[str, Any]:
        return self._response_from_events(iter(stream))

    async def _collect_async_response(self, stream: Any) -> dict[str, Any]:
        events = [event async for event in stream]
        return self._response_from_events(events)

    def _response_from_events(self, events: Any) -> dict[str, Any]:
        response: dict[str, Any] = {
            'id': '',
            'model': self._resolved_model_name(),
            'status': 'completed',
            'output': [],
            'usage': None,
        }
        text_deltas: list[str] = []
        reasoning_deltas: list[str] = []
        for event in events:
            event_type = str(_get(event, 'type') or '')
            event_response = _get(event, 'response')
            if event_response is not None:
                self._apply_event_response_metadata(response, event_response)
            if event_type == 'response.output_text.delta':
                self._append_text_delta(event, text_deltas)
            elif event_type in {
                'response.reasoning_summary_text.delta',
                'response.reasoning_text.delta',
            }:
                self._append_reasoning_delta(event, reasoning_deltas)
            elif event_type == 'response.output_item.done':
                item = _get(event, 'item')
                if item is not None:
                    response['output'].append(item)
            elif event_type == 'response.completed' and event_response is not None:
                self._apply_completed_response(response, event_response)

        self._append_synthesized_deltas(response, text_deltas, reasoning_deltas)
        return response

    @staticmethod
    def _apply_event_response_metadata(
        response: dict[str, Any], event_response: Any
    ) -> None:
        response['id'] = str(_get(event_response, 'id') or response['id'])
        response['model'] = str(_get(event_response, 'model') or response['model'])

    @staticmethod
    def _apply_completed_response(
        response: dict[str, Any], event_response: Any
    ) -> None:
        response['status'] = str(_get(event_response, 'status') or response['status'])
        response['usage'] = _get(event_response, 'usage')
        completed_output = _get(event_response, 'output')
        if completed_output:
            response['output'] = list(completed_output)

    @staticmethod
    def _append_text_delta(event: Any, text_deltas: list[str]) -> None:
        delta = _get(event, 'delta')
        if isinstance(delta, str):
            text_deltas.append(delta)

    @staticmethod
    def _append_reasoning_delta(event: Any, reasoning_deltas: list[str]) -> None:
        delta = _get(event, 'delta')
        if isinstance(delta, str):
            reasoning_deltas.append(delta)

    @staticmethod
    def _append_synthesized_deltas(
        response: dict[str, Any],
        text_deltas: list[str],
        reasoning_deltas: list[str],
    ) -> None:
        output_types = {_get(item, 'type') for item in response['output']}
        if text_deltas and 'message' not in output_types:
            response['output'].append(
                {
                    'type': 'message',
                    'role': 'assistant',
                    'content': [{'type': 'output_text', 'text': ''.join(text_deltas)}],
                }
            )
        if reasoning_deltas and 'reasoning' not in output_types:
            response['output'].insert(
                0,
                {
                    'type': 'reasoning',
                    'summary': [
                        {'type': 'summary_text', 'text': ''.join(reasoning_deltas)}
                    ],
                },
            )

    def _cache_reasoning_items(
        self,
        output: Any,
        *,
        call_ids: list[str] | None = None,
        extra_reasoning: list[dict[str, Any]] | None = None,
    ) -> None:
        reasoning_items = list(extra_reasoning or [])
        discovered_call_ids = list(call_ids or [])
        for item in output or []:
            item_type = _get(item, 'type')
            if item_type == 'reasoning':
                replay = _reasoning_replay_item(item)
                if replay is not None and replay not in reasoning_items:
                    reasoning_items.append(replay)
            elif item_type == 'function_call':
                call_id = str(_get(item, 'call_id') or _get(item, 'id') or '')
                if call_id and call_id not in discovered_call_ids:
                    discovered_call_ids.append(call_id)
        if not reasoning_items:
            return
        for call_id in discovered_call_ids:
            self._reasoning_by_call_id[call_id] = [
                dict(item) for item in reasoning_items
            ]
            self._reasoning_by_call_id.move_to_end(call_id)
        while len(self._reasoning_by_call_id) > _MAX_REASONING_REPLAY_ENTRIES:
            self._reasoning_by_call_id.popitem(last=False)

    @staticmethod
    def _tool_call_chunk(
        *,
        response_id: str,
        index: int,
        call_id: str = '',
        name: str = '',
        arguments: str = '',
    ) -> dict[str, Any]:
        tool_call: dict[str, Any] = {
            'index': index,
            'type': 'function',
            'function': {'name': name, 'arguments': arguments},
        }
        if call_id:
            tool_call['id'] = call_id
        return {
            'id': response_id,
            'choices': [{'delta': {'tool_calls': [tool_call]}}],
        }

    @staticmethod
    def _codex_home() -> Path:
        configured = os.environ.get('CODEX_HOME')
        return Path(configured).expanduser() if configured else Path.home() / '.codex'

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._write({'method': method, 'id': request_id, 'params': params})
        while True:
            message = self._read()
            if message.get('id') != request_id:
                continue
            if 'error' in message:
                error = message['error']
                raise CodexAppServerError(str(error.get('message', error)))
            return message.get('result') or {}

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({'method': method, 'params': params})

    def _write(self, payload: dict[str, Any]) -> None:
        if not self._process or not self._process.stdin:
            raise CodexAppServerError('Codex authentication broker is not running.')
        self._process.stdin.write(json.dumps(payload, separators=(',', ':')) + '\n')
        self._process.stdin.flush()

    def _read(self) -> dict[str, Any]:
        if not self._process or not self._process.stdout:
            raise CodexAppServerError('Codex authentication broker is not running.')
        line = self._process.stdout.readline()
        if not line:
            detail = ''
            if self._process.stderr:
                detail = self._process.stderr.read().strip()
            raise CodexAppServerError(
                f'Codex authentication broker exited unexpectedly. {detail}'.strip()
            )
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise CodexAppServerError(
                f'Invalid Codex authentication response: {line!r}'
            ) from exc


# Compatibility import for older integrations. Despite the historic name,
# inference no longer starts Codex threads or uses the Codex agent harness.
CodexAppServerClient = CodexResponsesClient
