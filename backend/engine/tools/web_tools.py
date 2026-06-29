"""Native web search/fetch tools — thin facades over bundled Exa + fetch MCP backends."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.core.enums import ActionSecurityRisk
from backend.core.tools.tool_names import WEB_FETCH_TOOL_NAME, WEB_SEARCH_TOOL_NAME
from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.param_defs import create_tool_definition
from backend.integrations.mcp.native_backends import (
    EXA_WEB_FETCH_MCP_TOOL,
    EXA_WEB_SEARCH_MCP_TOOL,
    FALLBACK_FETCH_MCP_TOOL,
)
from backend.ledger.action.mcp import MCPAction

# Internal router name — not exposed to the model; handled by WRAPPER_TOOL_REGISTRY.
NATIVE_WEB_FETCH_ROUTER = '__native_web_fetch__'


def create_web_search_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=WEB_SEARCH_TOOL_NAME,
        description=(
            'Search the web for current external information: release notes, errors, '
            'official docs, news, or facts not in the repo. Returns clean text snippets '
            'from top results. Prefer natural-language queries describing the ideal page. '
            'Follow up with web_fetch when you need full page bodies.'
        ),
        properties={
            'query': {
                'type': 'string',
                'description': (
                    'Natural-language search query describing the ideal page or answer.'
                ),
            },
            'num_results': {
                'type': 'integer',
                'description': 'Number of results to return (default 8).',
            },
        },
        required=['query'],
    )


def create_web_fetch_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=WEB_FETCH_TOOL_NAME,
        description=(
            'Read full page content from one or more http(s) URLs as clean markdown/text. '
            'Use after web_search when snippets are insufficient, or when you already have '
            'the URL. For interactive/JS-heavy pages, use browser instead.'
        ),
        properties={
            'urls': {
                'type': 'array',
                'items': {'type': 'string'},
                'description': 'One or more http(s) URLs to read.',
            },
            'max_characters': {
                'type': 'integer',
                'description': 'Maximum characters per page (default 8000).',
            },
        },
        required=['urls'],
    )


def _coerce_url_list(raw: Any) -> list[str]:
    if isinstance(raw, str):
        value = raw.strip()
        return [value] if value else []
    if not isinstance(raw, list):
        return []
    urls: list[str] = []
    for item in raw:
        if isinstance(item, str) and (value := item.strip()):
            urls.append(value)
    return urls


def _mcp_payload_ok(result: dict[str, Any]) -> bool:
    if result.get('isError') or result.get('ok') is False:
        return False
    content = result.get('content')
    if isinstance(content, list) and not content:
        return False
    return True


def _truncate_fetch_payload_text(payload: dict[str, Any], max_chars: int) -> dict[str, Any]:
    """Truncate text content within a fetch MCP payload to ``max_chars``.

    The fallback ``fetch`` MCP tool does not accept a ``maxCharacters``
    parameter, so we apply a head-truncation on the returned text content
    to match the cap that Exa would have enforced upstream.
    """
    if max_chars <= 0:
        return payload
    content = payload.get('content')
    if not isinstance(content, list):
        return payload
    new_content: list[Any] = []
    for item in content:
        if isinstance(item, dict) and isinstance(item.get('text'), str):
            text = item['text']
            if len(text) > max_chars:
                item = dict(item)
                item['text'] = (
                    text[:max_chars]
                    + f'\n[... truncated: {len(text) - max_chars} chars omitted]'
                )
        new_content.append(item)
    payload = dict(payload)
    payload['content'] = new_content
    return payload


async def native_web_fetch_wrapper(
    _mcps: list[Any],
    args: dict[str, Any],
    call_tool_func: Callable,
) -> dict[str, Any]:
    """Try Exa web_fetch_exa first; fall back to bundled fetch MCP."""
    urls = _coerce_url_list(args.get('urls'))
    if not urls:
        return {
            'ok': False,
            'isError': True,
            'error': 'web_fetch requires at least one URL in urls.',
            'category': 'bad_args',
        }

    max_chars = args.get('max_characters', 8000)
    try:
        max_chars = int(max_chars)
    except (TypeError, ValueError):
        max_chars = 8000

    exa_args = {'urls': urls, 'maxCharacters': max_chars}
    try:
        exa_result = await call_tool_func(EXA_WEB_FETCH_MCP_TOOL, exa_args)
        if _mcp_payload_ok(exa_result):
            payload = dict(exa_result)
            payload['backend'] = 'exa'
            return payload
    except Exception:
        pass

    if len(urls) == 1:
        try:
            fetch_result = await call_tool_func(
                FALLBACK_FETCH_MCP_TOOL,
                {'url': urls[0]},
            )
            if _mcp_payload_ok(fetch_result):
                payload = _truncate_fetch_payload_text(
                    dict(fetch_result), max_chars
                )
                payload['backend'] = 'fetch'
                return payload
        except Exception:
            pass

    return {
        'ok': False,
        'isError': True,
        'error': ('web_fetch failed. Check MCP connectivity or try browser.'),
        'category': 'env',
        'retryable': True,
        'urls': urls,
    }


def build_web_search_action(arguments: dict[str, Any]) -> MCPAction:
    from backend.core.errors import FunctionCallValidationError

    query = str(arguments.get('query') or '').strip()
    if not query:
        raise FunctionCallValidationError('web_search requires a non-empty query.')

    exa_args: dict[str, Any] = {'query': query}
    if arguments.get('num_results') is not None:
        try:
            exa_args['numResults'] = int(arguments['num_results'])
        except (TypeError, ValueError):
            pass

    return MCPAction(
        name=EXA_WEB_SEARCH_MCP_TOOL,
        arguments=exa_args,
        security_risk=ActionSecurityRisk.LOW,
    )


def build_web_fetch_action(arguments: dict[str, Any]) -> MCPAction:
    from backend.core.errors import FunctionCallValidationError

    urls = _coerce_url_list(arguments.get('urls'))
    if not urls:
        raise FunctionCallValidationError(
            'web_fetch requires at least one URL in urls.'
        )

    payload: dict[str, Any] = {'urls': urls}
    if arguments.get('max_characters') is not None:
        try:
            payload['max_characters'] = int(arguments['max_characters'])
        except (TypeError, ValueError):
            pass

    return MCPAction(
        name=NATIVE_WEB_FETCH_ROUTER,
        arguments=payload,
        security_risk=ActionSecurityRisk.LOW,
    )
