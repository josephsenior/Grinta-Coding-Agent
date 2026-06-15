"""Activity card builders — mcp domain."""

from __future__ import annotations

import json
from typing import Any

from backend.cli.event_rendering.unified_renderer.types import (
    ActivityCard,
    ActivityLine,
)
from backend.cli.event_rendering.unified_renderer.utils import (
    _WEB_CARD_PRESETS,
    _WEB_MCP_KINDS,
    _exploration_meta_line,
)
from backend.cli.theme import NAVY_TEXT_DIM, NAVY_TEXT_MUTED
from backend.cli.tool_display.preview import mcp_result_user_preview


class _McpMixin:
    @staticmethod
    def resolve_native_web_tool_kind(mcp_name: str) -> str | None:
        return _WEB_MCP_KINDS.get((mcp_name or '').strip())

    @staticmethod
    def _coerce_mcp_result_payload(content: str) -> Any:
        s = (content or '').strip()
        if not s:
            return None
        if s.startswith('{') or s.startswith('['):
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                return s
        return s

    @staticmethod
    def _count_collection_in_mcp_content(content: str) -> int:
        payload = _McpMixin._coerce_mcp_result_payload(content)
        if isinstance(payload, list):
            return len(payload)
        if not isinstance(payload, dict):
            return 0
        for key in ('results', 'items', 'documents', 'matches'):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
        blocks = payload.get('content')
        if not isinstance(blocks, list):
            return 0
        total = 0
        for block in blocks:
            if not isinstance(block, dict):
                continue
            raw = block.get('text')
            if not isinstance(raw, str) or not raw.strip():
                continue
            inner = raw.strip()
            if not (inner.startswith('{') or inner.startswith('[')):
                continue
            try:
                parsed = json.loads(inner)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, list):
                total += len(parsed)
            elif isinstance(parsed, dict):
                for key in ('results', 'items', 'documents', 'matches'):
                    value = parsed.get(key)
                    if isinstance(value, list):
                        total += len(value)
        return total

    @staticmethod
    def _build_mcp_extra_lines_from_content(content: str) -> list[ActivityLine]:
        from backend.cli.tool_display.renderers.mcp import _format_mcp_result

        payload = _McpMixin._coerce_mcp_result_payload(content)
        if payload is None:
            return []
        formatted = _format_mcp_result(payload)
        extra_lines: list[ActivityLine] = []
        for line in formatted[:12]:
            extra_lines.append(ActivityLine(str(line), style=NAVY_TEXT_MUTED, indent=1))
        if len(formatted) > 12:
            extra_lines.append(
                ActivityLine(
                    f'... {len(formatted) - 12} more lines',
                    style=NAVY_TEXT_DIM,
                    indent=1,
                )
            )
        if extra_lines:
            return extra_lines
        preview = mcp_result_user_preview(content)
        if preview:
            extra_lines.append(ActivityLine(preview, style=NAVY_TEXT_MUTED, indent=1))
        return extra_lines

    @staticmethod
    def _web_tool_secondary(
        kind: str,
        content: str,
        *,
        error: str | None = None,
    ) -> tuple[str, str]:
        if error:
            return 'failed', 'err'
        count = _McpMixin._count_collection_in_mcp_content(content)
        if kind == 'web_search':
            if count:
                label = 'result' if count == 1 else 'results'
                return f'{count} {label}', 'ok'
            preview = mcp_result_user_preview(content)
            if preview:
                return preview[:80], 'ok'
            return 'no results', 'neutral'
        if kind == 'web_fetch':
            if count:
                label = 'page' if count == 1 else 'pages'
                return f'{count} {label}', 'ok'
            preview = mcp_result_user_preview(content)
            if preview:
                return preview[:80], 'ok'
            return 'no content', 'neutral'
        return 'completed', 'ok'

    @staticmethod
    def _web_search_meta(arguments: dict[str, Any] | None) -> list[str]:
        tokens: list[str] = []
        args = arguments or {}
        num_results = args.get('numResults')
        if num_results is not None:
            tokens.append(f'limit: {num_results}')
        return _exploration_meta_line(tokens)

    @staticmethod
    def _web_fetch_meta(
        arguments: dict[str, Any] | None,
        content: str = '',
    ) -> list[str]:
        tokens: list[str] = []
        args = arguments or {}
        max_chars = args.get('max_characters')
        if max_chars is not None:
            tokens.append(f'max: {max_chars}')
        payload = _McpMixin._coerce_mcp_result_payload(content)
        if isinstance(payload, dict):
            backend = payload.get('backend')
            if isinstance(backend, str) and backend:
                tokens.append(f'backend: {backend}')
        return _exploration_meta_line(tokens)

    @staticmethod
    def web_search_card(
        arguments: dict[str, Any] | None = None,
        *,
        result: str | None = None,
        error: str | None = None,
    ) -> ActivityCard:
        badge_category, title, verb = _WEB_CARD_PRESETS['web_search']
        query = str((arguments or {}).get('query') or '').strip()
        detail = f'"{query}"' if query else 'web'
        secondary, secondary_kind = _McpMixin._web_tool_secondary(
            'web_search',
            result or '',
            error=error,
        )
        extra_lines = _McpMixin._build_mcp_extra_lines_from_content(
            result or error or ''
        )
        return ActivityCard(
            verb=verb,
            detail=detail,
            badge_category=badge_category,
            title=title,
            secondary=secondary,
            secondary_kind=secondary_kind,
            extra_lines=extra_lines,
            meta_lines=_McpMixin._web_search_meta(arguments),
            is_collapsible=bool(extra_lines),
        )

    @staticmethod
    def web_fetch_card(
        arguments: dict[str, Any] | None = None,
        *,
        result: str | None = None,
        error: str | None = None,
    ) -> ActivityCard:
        badge_category, title, verb = _WEB_CARD_PRESETS['web_fetch']
        urls = (arguments or {}).get('urls') or []
        if isinstance(urls, str):
            urls = [urls] if urls.strip() else []
        if len(urls) == 1:
            detail = str(urls[0])[:80]
        elif urls:
            detail = f'{len(urls)} URLs'
        else:
            detail = 'web pages'
        secondary, secondary_kind = _McpMixin._web_tool_secondary(
            'web_fetch',
            result or '',
            error=error,
        )
        extra_lines = _McpMixin._build_mcp_extra_lines_from_content(
            result or error or ''
        )
        return ActivityCard(
            verb=verb,
            detail=detail,
            badge_category=badge_category,
            title=title,
            secondary=secondary,
            secondary_kind=secondary_kind,
            extra_lines=extra_lines,
            meta_lines=_McpMixin._web_fetch_meta(arguments, result or ''),
            is_collapsible=bool(extra_lines),
        )

    @staticmethod
    def mcp_activity_card(
        name: str,
        arguments: dict | None = None,
        *,
        result: str | None = None,
        success: bool | None = None,
        error: str | None = None,
    ) -> ActivityCard:
        """Build the best activity card for an MCP invocation."""
        kind = _McpMixin.resolve_native_web_tool_kind(name)
        if kind == 'web_search':
            return _McpMixin.web_search_card(
                arguments,
                result=result,
                error=error,
            )
        if kind == 'web_fetch':
            return _McpMixin.web_fetch_card(
                arguments,
                result=result,
                error=error,
            )
        return _McpMixin.mcp_tool(
            name,
            arguments,
            result=result,
            success=success,
            error=error,
        )

    @staticmethod
    def mcp_tool(
        name: str,
        arguments: dict | None = None,
        result: str | None = None,
        success: bool | None = None,
        error: str | None = None,
    ) -> ActivityCard:
        """Create an activity card for an MCP tool call."""
        args_str = ''
        if arguments:
            args_preview = ', '.join(
                f'{k}={repr(v)[:30]}' for k, v in list(arguments.items())[:2]
            )
            if len(args_preview) > 60:
                args_preview = args_preview[:57] + '...'
            args_str = f'({args_preview})' if args_preview else ''

        secondary = None
        secondary_kind = 'neutral'
        if error:
            secondary = 'failed'
            secondary_kind = 'err'
        elif result:
            preview = mcp_result_user_preview(result)
            secondary = (preview[:80] if preview else 'completed') or 'completed'
            secondary_kind = 'ok' if success is not False else 'err'
        elif success is True:
            secondary = 'completed'
            secondary_kind = 'ok'

        extra_lines = _McpMixin._build_mcp_extra_lines_from_content(
            result or error or ''
        )

        return ActivityCard(
            verb='Called',
            detail=f'{name}{args_str}',
            badge_category='mcp',
            title='Connected Tool',
            secondary=secondary,
            secondary_kind=secondary_kind,
            extra_lines=extra_lines,
            is_collapsible=bool(extra_lines) or bool(error),
            start_collapsed=not bool(error),
        )
