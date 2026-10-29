"""Opt-in public Responses transport for an authorized ChatGPT-plan token.

This provider does not read Codex credentials or fall back to API-key billing.
The sign-in application owns OAuth consent and renewal and supplies the token.
"""

from __future__ import annotations

import os
from typing import Any

from openai import AsyncOpenAI, OpenAI

from backend.inference.clients.codex_app_server import CodexResponsesClient, _get

BASE_URL = 'https://api.openai.com/v1'


class ChatGPTPlanError(RuntimeError):
    """The independently authorized ChatGPT-plan connection cannot continue."""


class ChatGPTPlanClient(CodexResponsesClient):
    """Reuse Grinta's message conversion, tool execution and usage reporting."""

    def __init__(self, model_name: str, *, timeout=None):
        if not model_name or model_name == 'default':
            raise ValueError(
                'Select an explicit model available to the signed-in account'
            )
        super().__init__(model_name, timeout=timeout)

    def _credentials(self):
        token = os.environ.get('GRINTA_CHATGPT_PLAN_ACCESS_TOKEN', '').strip()
        if not token:
            from backend.inference.clients.chatgpt_plan_auth import (
                PlanAuthError,
                access_token,
            )

            try:
                token = access_token(
                    os.environ.get('GRINTA_CHATGPT_PLAN_PROFILE', 'default')
                )
            except PlanAuthError as exc:
                raise ChatGPTPlanError(
                    'ChatGPT-plan authorization required. ' + str(exc)
                ) from None
        return token, ''

    def _resolved_model_name(self):
        return self._model_name

    def _sync_responses_client(self, token, account_id):
        return OpenAI(
            api_key=token,
            base_url=BASE_URL,
            max_retries=0,
            timeout=self._timeout or 120,
        )

    def _async_responses_client(self, token, account_id):
        return AsyncOpenAI(
            api_key=token,
            base_url=BASE_URL,
            max_retries=0,
            timeout=self._timeout or 120,
        )

    def _build_payload(self, messages, kwargs):
        payload = super()._build_payload(messages, kwargs)
        tools = payload.get('tools', [])
        if any(tool.get('type') != 'function' for tool in tools):
            raise ValueError(
                'ChatGPT-plan provider currently supports Grinta function tools only'
            )
        if tools:
            payload['tools'] = [
                {
                    'type': 'namespace',
                    'name': 'grinta',
                    'description': 'Tools executed by Grinta',
                    'tools': tools,
                }
            ]
            choice = payload.get('tool_choice')
            if isinstance(choice, dict) and choice.get('type') == 'function':
                payload['tool_choice'] = {**choice, 'namespace': 'grinta'}
        return payload

    @staticmethod
    def _check_event(event):
        kind = _get(event, 'type')
        if kind in {'response.failed', 'response.incomplete', 'error'}:
            raise ChatGPTPlanError(
                'ChatGPT-plan request failed or was incomplete; no response accepted'
            )

    def _response_from_events(self, events):
        def checked():
            completed = False
            for event in events:
                self._check_event(event)
                completed |= _get(event, 'type') == 'response.completed'
                yield event
            if not completed:
                raise ChatGPTPlanError(
                    'ChatGPT-plan stream ended before response.completed'
                )

        return super()._response_from_events(checked())

    async def astream(self, messages, **kwargs):
        # Buffer until completion so interrupted tool calls cannot reach execution.
        response = await self.acompletion(messages, **kwargs)
        delta: dict[str, Any] = {'content': response.content}
        if response.tool_calls:
            delta['tool_calls'] = [
                dict(call, index=i) for i, call in enumerate(response.tool_calls)
            ]
        yield {
            'id': response.response_id,
            'model': response.model,
            'choices': [{'delta': delta, 'finish_reason': response.finish_reason}],
            'usage': response.usage,
        }
