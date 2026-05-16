"""MCP tool call renderer with structured result display.

Shows MCP tool calls with badge, args summary, and result preview.
"""

from __future__ import annotations

import re
from typing import Any

from backend.cli.theme import (
    CLR_STATUS_ERR,
    CLR_STATUS_OK,
)
from backend.cli.transcript import format_activity_primary

_PATH_RE = re.compile(r'["\']?path["\']?\s*[:=]\s*["\']([^"\']+)["\']')
_URL_RE = re.compile(r'https?://\S+')


def render_mcp_tool(
    tool_name: str,
    args: dict[str, Any] | None = None,
    result: Any | None = None,
    error: str | None = None,
    duration: str = '',
) -> list[str]:
    """Render an MCP tool call with structured display."""
    lines: list[str] = []

    service_name = tool_name.split('::')[0] if '::' in tool_name else tool_name
    short_name = tool_name.split('::')[-1] if '::' in tool_name else tool_name

    if service_name != short_name:
        detail = f'{service_name}  [dim]→  {short_name}[/dim]'
    else:
        detail = short_name

    if duration:
        detail += f'  [dim]·  {duration}[/dim]'

    lines.append(format_activity_primary('MCP', detail))

    if args:
        args_summary = _summarize_mcp_args(tool_name, args)
        if args_summary:
            lines.append(f'  {args_summary}')

    if error:
        lines.append(f'  [{CLR_STATUS_ERR}]✗ {error}[/{CLR_STATUS_ERR}]')
        return lines

    if result is not None:
        result_lines = _format_mcp_result(result)
        for line in result_lines[:10]:
            lines.append(f'  {line}')
        if len(result_lines) > 10:
            lines.append(f'  [dim]... {len(result_lines) - 10} more[/dim]')

    return lines


def _summarize_mcp_args(tool_name: str, args: dict[str, Any]) -> str:
    """Summarize MCP tool args into a one-line description."""
    short_name = tool_name.split('::')[-1] if '::' in tool_name else tool_name

    if 'read' in short_name.lower() and 'path' in args:
        path = args.get('path', '')
        if isinstance(path, str) and path:
            return f'[dim]path: {path}[/dim]'
    if 'write' in short_name.lower() and 'path' in args:
        path = args.get('path', '')
        if isinstance(path, str) and path:
            return f'[dim]path: {path}[/dim]'
    if 'search' in short_name.lower():
        query = args.get('query', args.get('q', args.get('search', '')))
        if isinstance(query, str) and query:
            return f'[dim]query: "{query}"[/dim]'
    if 'list' in short_name.lower() and 'path' in args:
        path = args.get('path', '')
        if isinstance(path, str) and path:
            return f'[dim]path: {path}[/dim]'
    if 'git' in short_name.lower() and 'command' in args:
        cmd = args.get('command', '')
        if isinstance(cmd, str):
            return f'[dim]$ {cmd}[/dim]'
    if 'run' in short_name.lower() or 'execute' in short_name.lower():
        cmd = args.get('command', args.get('cmd', ''))
        if isinstance(cmd, str):
            return f'[dim]$ {cmd}[/dim]'

    path_match = _PATH_RE.search(str(args))
    if path_match:
        return f'[dim]path: {path_match.group(1)}[/dim]'

    keys = list(args.keys())
    if keys:
        first_key = keys[0]
        first_val = args[first_key]
        if isinstance(first_val, str) and len(first_val) < 60:
            return f'[dim]{first_key}: {first_val}[/dim]'

    return f'[dim]{len(keys)} args[/dim]'


def _format_mcp_result(result: Any) -> list[str]:
    """Format MCP result for display."""
    if result is None:
        return []

    if isinstance(result, str):
        lines = result.splitlines()[:10]
        return [line.strip() for line in lines if line.strip()]

    if isinstance(result, dict):
        if 'content' in result:
            content = result['content']
            if isinstance(content, list):
                first_item = content[0] if content else None
                if isinstance(first_item, dict):
                    text = first_item.get('text', str(first_item))
                    if text:
                        return text.splitlines()[:10]
            elif isinstance(content, str):
                return content.splitlines()[:10]

        if 'files' in result:
            files = result['files']
            if isinstance(files, list):
                output = [f'[{CLR_STATUS_OK}]Files ({len(files)}):[/]']
                for f in files[:5]:
                    name = f.get('name', f.get('path', str(f)))
                    output.append(f'  [dim]· {name}[/dim]')
                if len(files) > 5:
                    output.append(f'  [dim]... {len(files) - 5} more[/dim]')
                return output

        if 'results' in result:
            results = result['results']
            if isinstance(results, list):
                output = [f'[{CLR_STATUS_OK}]Results ({len(results)}):[/]']
                for r in results[:5]:
                    preview = str(r).splitlines()[0] if str(r) else ''
                    if len(preview) > 60:
                        preview = preview[:57] + '…'
                    output.append(f'  [dim]· {preview}[/dim]')
                return output

        if 'paths' in result:
            paths = result['paths']
            if isinstance(paths, list):
                output = [f'[{CLR_STATUS_OK}]Paths ({len(paths)}):[/]']
                for path in paths[:5]:
                    output.append(f'  [dim]· {path}[/dim]')
                return output

        key_count = len(result)
        return [f'[dim]{key_count} fields[/dim]']

    if isinstance(result, list):
        if len(result) == 0:
            return [f'[{CLR_STATUS_OK}]✓ done[/]']

        output = [f'[{CLR_STATUS_OK}]Items ({len(result)}):[/]']
        for item in result[:5]:
            if isinstance(item, dict):
                name = item.get('name', item.get('title', item.get('path', str(item)[:40])))
                output.append(f'  [dim]· {name}[/dim]')
            elif isinstance(item, str):
                output.append(f'  [dim]· {item[:60]}[/dim]')
        if len(result) > 5:
            output.append(f'  [dim]... {len(result) - 5} more[/dim]')
        return output

    return [f'[dim]{str(result)[:80]}[/dim]']
