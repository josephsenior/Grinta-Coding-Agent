"""Native library-docs tools — thin facades over bundled Context7 MCP backends."""

from __future__ import annotations

from typing import Any

from backend.core.enums import ActionSecurityRisk
from backend.core.tools.tool_names import DOCS_QUERY_TOOL_NAME, DOCS_RESOLVE_TOOL_NAME
from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.param_defs import create_tool_definition
from backend.integrations.mcp.native_backends import (
    CONTEXT7_QUERY_MCP_TOOL,
    CONTEXT7_RESOLVE_MCP_TOOL,
)
from backend.ledger.action.mcp import MCPAction


def apply_docs_resolve_defaults(inner: dict[str, Any]) -> None:
    """Context7 resolve requires both library name and query."""
    if not inner.get('libraryName') or inner.get('query') not in (None, ''):
        return
    ln = str(inner['libraryName']).strip()
    if not ln:
        return
    inner['query'] = (
        f'Documentation, setup, and API reference for {ln} — pick the best-matching library.'
    )


def create_docs_resolve_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=DOCS_RESOLVE_TOOL_NAME,
        description=(
            'Resolve a library or framework name to a documentation corpus ID. '
            'Call before docs_query when you need current API docs, setup guides, '
            'migrations, or version-specific behavior for a known package. '
            'Skip when you already have a corpus ID like /vercel/next.js or '
            '/vercel/next.js/v14. Prefer this over web_search for library documentation.'
        ),
        properties={
            'library_name': {
                'type': 'string',
                'description': (
                    'Official library or package name with correct punctuation '
                    "(e.g. 'Next.js', 'Customer.io', 'Three.js')."
                ),
            },
            'query': {
                'type': 'string',
                'description': (
                    'What you need from the docs — specific enough to rank matches '
                    "(e.g. 'App Router middleware', 'JWT auth setup')."
                ),
            },
        },
        required=['library_name', 'query'],
    )


def create_docs_query_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=DOCS_QUERY_TOOL_NAME,
        description=(
            'Query up-to-date documentation and code examples for a library corpus. '
            'Use after docs_resolve unless you already have a corpus ID in /org/project '
            'or /org/project/version form. Prefer over web_search for framework/library '
            'API syntax, configuration, migrations, and CLI usage.'
        ),
        properties={
            'library_id': {
                'type': 'string',
                'description': (
                    'Corpus ID from docs_resolve or known directly '
                    "(e.g. '/facebook/react', '/vercel/next.js/v14.3.0')."
                ),
            },
            'query': {
                'type': 'string',
                'description': (
                    'Specific documentation question. Good: '
                    "'useEffect cleanup examples'. Bad: 'hooks'."
                ),
            },
        },
        required=['library_id', 'query'],
    )


def build_docs_resolve_action(arguments: dict[str, Any]) -> MCPAction:
    from backend.core.errors import FunctionCallValidationError

    library_name = str(
        arguments.get('library_name') or arguments.get('libraryName') or ''
    ).strip()
    query = str(arguments.get('query') or '').strip()
    if not library_name:
        raise FunctionCallValidationError(
            'docs_resolve requires a non-empty library_name.'
        )

    inner: dict[str, Any] = {'libraryName': library_name}
    if query:
        inner['query'] = query
    apply_docs_resolve_defaults(inner)

    return MCPAction(
        name=CONTEXT7_RESOLVE_MCP_TOOL,
        arguments=inner,
        security_risk=ActionSecurityRisk.LOW,
    )


def build_docs_query_action(arguments: dict[str, Any]) -> MCPAction:
    from backend.core.errors import FunctionCallValidationError

    library_id = str(
        arguments.get('library_id') or arguments.get('libraryId') or ''
    ).strip()
    query = str(arguments.get('query') or '').strip()
    if not library_id:
        raise FunctionCallValidationError('docs_query requires a non-empty library_id.')
    if not query:
        raise FunctionCallValidationError('docs_query requires a non-empty query.')

    return MCPAction(
        name=CONTEXT7_QUERY_MCP_TOOL,
        arguments={'libraryId': library_id, 'query': query},
        security_risk=ActionSecurityRisk.LOW,
    )
