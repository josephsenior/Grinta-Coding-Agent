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


def _build_mcp_header(tool_name: str, duration: str) -> Any:
    service_name = tool_name.split('::')[0] if '::' in tool_name else tool_name
    short_name = tool_name.split('::')[-1] if '::' in tool_name else tool_name
    if service_name != short_name:
        detail = f'{service_name}  [dim]\u2192  {short_name}[/dim]'
    else:
        detail = short_name
    if duration:
        detail += f'  [dim]\u00b7  {duration}[/dim]'
    return format_activity_primary('MCP', detail)


def _append_mcp_result(lines: list[Any], result: Any | None) -> None:
    if result is None:
        return
    result_lines = _format_mcp_result(result)
    for line in result_lines[:10]:
        lines.append(f'  {line}')
    if len(result_lines) > 10:
        lines.append(f'  [dim]... {len(result_lines) - 10} more[/dim]')


def render_mcp_tool(
    tool_name: str,
    args: dict[str, Any] | None = None,
    result: Any | None = None,
    error: str | None = None,
    duration: str = '',
) -> list[Any]:
    """Render an MCP tool call with structured display."""
    lines: list[Any] = []

    lines.append(_build_mcp_header(tool_name, duration))

    if args:
        args_summary = _summarize_mcp_args(tool_name, args)
        if args_summary:
            lines.append(f'  {args_summary}')

    if error:
        lines.append(f'  [{CLR_STATUS_ERR}]\u2717 {error}[/{CLR_STATUS_ERR}]')
        return lines

    _append_mcp_result(lines, result)

    return lines


def _try_match_path_args(short_name: str, args: dict[str, Any], keywords: tuple[str, ...]) -> str | None:
    if any(kw in short_name.lower() for kw in keywords) and 'path' in args:
        path = args.get('path', '')
        if isinstance(path, str) and path:
            return f'[dim]path: {path}[/dim]'
    return None


def _try_match_search_args(short_name: str, args: dict[str, Any]) -> str | None:
    if 'search' in short_name.lower():
        query = args.get('query', args.get('q', args.get('search', '')))
        if isinstance(query, str) and query:
            return f'[dim]query: "{query}"[/dim]'
    return None


def _try_match_command_args(short_name: str, args: dict[str, Any], keywords: tuple[str, ...]) -> str | None:
    if any(kw in short_name.lower() for kw in keywords) and 'command' in args:
        cmd = args.get('command', '')
        if isinstance(cmd, str):
            return f'[dim]$ {cmd}[/dim]'
    return None


def _try_match_run_args(short_name: str, args: dict[str, Any]) -> str | None:
    if 'run' in short_name.lower() or 'execute' in short_name.lower():
        cmd = args.get('command', args.get('cmd', ''))
        if isinstance(cmd, str):
            return f'[dim]$ {cmd}[/dim]'
    return None


def _try_match_regex_path(args: dict[str, Any]) -> str | None:
    path_match = _PATH_RE.search(str(args))
    if path_match:
        return f'[dim]path: {path_match.group(1)}[/dim]'
    return None


def _try_match_first_arg(args: dict[str, Any]) -> str | None:
    keys = list(args.keys())
    if keys:
        first_key = keys[0]
        first_val = args[first_key]
        if isinstance(first_val, str) and len(first_val) < 60:
            return f'[dim]{first_key}: {first_val}[/dim]'
    return None


def _summarize_mcp_args(tool_name: str, args: dict[str, Any]) -> str:
    """Summarize MCP tool args into a one-line description."""
    short_name = tool_name.split('::')[-1] if '::' in tool_name else tool_name

    if result := _try_match_path_args(short_name, args, ('read', 'write', 'list')):
        return result
    if result := _try_match_search_args(short_name, args):
        return result
    if result := _try_match_command_args(short_name, args, ('git',)):
        return result
    if result := _try_match_run_args(short_name, args):
        return result
    if result := _try_match_regex_path(args):
        return result
    if result := _try_match_first_arg(args):
        return result

    return f'[dim]{len(args)} args[/dim]'


def _format_mcp_result_string(result: str) -> list[str]:
    lines = result.splitlines()[:10]
    return [line.strip() for line in lines if line.strip()]


def _format_mcp_result_dict_content(content: Any) -> list[str] | None:
    if isinstance(content, list):
        first_item = content[0] if content else None
        if isinstance(first_item, dict):
            text = first_item.get('text', str(first_item))
            if text:
                return text.splitlines()[:10]
    elif isinstance(content, str):
        return content.splitlines()[:10]
    return None


def _format_mcp_result_dict_files(files: list) -> list[str]:
    output = [f'[{CLR_STATUS_OK}]Files ({len(files)}):[/]']
    for f in files[:5]:
        name = f.get('name', f.get('path', str(f)))
        output.append(f'  [dim]· {name}[/dim]')
    if len(files) > 5:
        output.append(f'  [dim]... {len(files) - 5} more[/dim]')
    return output


def _format_mcp_result_dict_results(results: list) -> list[str]:
    output = [f'[{CLR_STATUS_OK}]Results ({len(results)}):[/]']
    for r in results[:5]:
        preview = str(r).splitlines()[0] if str(r) else ''
        if len(preview) > 60:
            preview = preview[:57] + '…'
        output.append(f'  [dim]· {preview}[/dim]')
    return output


def _format_mcp_result_dict_paths(paths: list) -> list[str]:
    output = [f'[{CLR_STATUS_OK}]Paths ({len(paths)}):[/]']
    for path in paths[:5]:
        output.append(f'  [dim]· {path}[/dim]')
    return output


def _format_mcp_result_dict(result: dict) -> list[str]:
    if 'content' in result:
        formatted = _format_mcp_result_dict_content(result['content'])
        if formatted is not None:
            return formatted

    if 'files' in result:
        files = result['files']
        if isinstance(files, list):
            return _format_mcp_result_dict_files(files)

    if 'results' in result:
        results = result['results']
        if isinstance(results, list):
            return _format_mcp_result_dict_results(results)

    if 'paths' in result:
        paths = result['paths']
        if isinstance(paths, list):
            return _format_mcp_result_dict_paths(paths)

    key_count = len(result)
    return [f'[dim]{key_count} fields[/dim]']


def _format_mcp_result_list(result: list) -> list[str]:
    if len(result) == 0:
        return [f'[{CLR_STATUS_OK}]✓ done[/]']

    output = [f'[{CLR_STATUS_OK}]Items ({len(result)}):[/]']
    for item in result[:5]:
        if isinstance(item, dict):
            name = item.get(
                'name', item.get('title', item.get('path', str(item)[:40]))
            )
            output.append(f'  [dim]· {name}[/dim]')
        elif isinstance(item, str):
            output.append(f'  [dim]· {item[:60]}[/dim]')
    if len(result) > 5:
        output.append(f'  [dim]... {len(result) - 5} more[/dim]')
    return output


def _format_mcp_result(result: Any) -> list[Any]:
    """Format MCP result for display."""
    if result is None:
        return []

    if isinstance(result, str):
        return _format_mcp_result_string(result)

    if isinstance(result, dict):
        return _format_mcp_result_dict(result)

    if isinstance(result, list):
        return _format_mcp_result_list(result)

    return [f'[dim]{str(result)[:80]}[/dim]']
