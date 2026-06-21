"""Flat activity-line specs for read-only orientation tools."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlparse

from backend.cli.display.text_truncation import shorten_middle
from backend.cli.tool_display.summarize import _orient_path

ORIENT_MCP_TOOL_NAMES: frozenset[str] = frozenset(
    {
        'web_search_exa',
        'web_fetch_exa',
        '__native_web_fetch__',
        'fetch',
        'resolve-library-id',
        'query-docs',
    }
)


@dataclass(frozen=True)
class OrientLineModel:
    """One completed flat orient row."""

    tool: str
    icon: str
    verb: str
    target: str
    result: str
    area: str = 'codebase'

    def with_result(self, result: str) -> 'OrientLineModel':
        return replace(self, result=(result or 'completed').strip())


def _quote(value: Any, *, fallback: str = '') -> str:
    text = str(value or fallback).strip()
    return f'"{text}"' if text else '""'


def _display_path(path: Any, max_len: int = 44) -> str:
    text = str(path or '').strip()
    return _orient_path(text, max_len=max_len) if text else ''


def _plural(count: int, noun: str) -> str:
    return f'{count} {noun}{"s" if count != 1 else ""}'


def _json_payload(content: str) -> Any:
    text = (content or '').strip()
    if not text:
        return None
    if not text.startswith(('{', '[')):
        return text
    try:
        return json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return text


def _payload_failed(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get('isError') or payload.get('ok') is False:
        return True
    return bool(payload.get('error'))


def _count_collection(payload: Any) -> int | None:
    if isinstance(payload, list):
        return len(payload)
    if not isinstance(payload, dict):
        return None
    for key in (
        'results',
        'items',
        'documents',
        'matches',
        'libraries',
        'entries',
        'data',
    ):
        value = payload.get(key)
        if isinstance(value, list):
            return len(value)
    for key in ('total_count', 'totalCount', 'count', 'total'):
        value = payload.get(key)
        if isinstance(value, int):
            return value
    blocks = payload.get('content')
    if isinstance(blocks, list):
        nested_total = 0
        saw_nested = False
        text_blocks = 0
        for block in blocks:
            if isinstance(block, dict):
                raw = block.get('text') or block.get('content')
            else:
                raw = block
            if isinstance(raw, str) and raw.strip():
                text_blocks += 1
                parsed = _json_payload(raw)
                nested = _count_collection(parsed)
                if nested is not None:
                    nested_total += nested
                    saw_nested = True
        if saw_nested:
            return nested_total
        return text_blocks
    return None


def _count_result_lines(content: str) -> int:
    return len([line for line in (content or '').splitlines() if line.strip()])


def _extract_json_list_count(payload: Any, *keys: str) -> int | None:
    if isinstance(payload, list):
        return len(payload)
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return len(value)
    return None


def _file_count_from_candidates(candidates: list[Any]) -> int:
    paths = {
        str(item.get('path') or '').strip()
        for item in candidates
        if isinstance(item, dict) and str(item.get('path') or '').strip()
    }
    return len(paths)


def grep_action_model(action: Any) -> OrientLineModel:
    pattern = getattr(action, 'pattern', '') or ''
    path = getattr(action, 'path', '') or '.'
    return OrientLineModel(
        tool='grep',
        icon='⌕',
        verb='Grepped',
        target=f'{_quote(pattern)} in {_display_path(path)}',
        result='…',
    )


def grep_observation_model(obs: Any) -> OrientLineModel:
    return grep_action_model(obs).with_result(
        grep_result(
            match_count=int(getattr(obs, 'match_count', 0) or 0),
            file_count=int(getattr(obs, 'file_count', 0) or 0),
            output_mode=str(getattr(obs, 'output_mode', '') or 'files_with_matches'),
            error=str(getattr(obs, 'error', '') or ''),
        )
    )


def grep_result(
    *,
    match_count: int,
    file_count: int,
    output_mode: str,
    error: str = '',
) -> str:
    if error:
        return 'failed'
    mode = output_mode or 'files_with_matches'
    if mode == 'files_with_matches':
        return _plural(file_count, 'file') if file_count else 'no matches'
    if mode == 'count':
        return _plural(match_count, 'match') if match_count else 'no matches'
    if mode == 'content':
        if not match_count and not file_count:
            return 'no matches'
        if file_count:
            return f'{_plural(match_count, "match")} · {_plural(file_count, "file")}'
        return _plural(match_count, 'match')
    if file_count:
        return _plural(file_count, 'file')
    return _plural(match_count, 'match') if match_count else 'no matches'


def glob_action_model(action: Any) -> OrientLineModel:
    pattern = getattr(action, 'pattern', '') or ''
    path = getattr(action, 'path', '') or '.'
    return OrientLineModel(
        tool='glob',
        icon='◆',
        verb='Globbed',
        target=f'{pattern} in {_display_path(path)}'.strip(),
        result='…',
    )


def glob_observation_model(obs: Any) -> OrientLineModel:
    count = int(getattr(obs, 'file_count', 0) or 0)
    if not count:
        files = getattr(obs, 'files', None) or []
        if isinstance(files, list):
            count = len(files)
    result = (
        'failed'
        if getattr(obs, 'error', '')
        else (_plural(count, 'file') if count else 'no files')
    )
    return glob_action_model(obs).with_result(result)


def find_symbols_action_model(action: Any) -> OrientLineModel:
    query = getattr(action, 'query', '') or ''
    path = str(getattr(action, 'path', '') or '').strip()
    target = _quote(query or 'symbol')
    if path and path != '.':
        target = f'{target} in {_display_path(path)}'
    return OrientLineModel(
        tool='find_symbols',
        icon='ƒ',
        verb='Found',
        target=target,
        result='…',
    )


def find_symbols_observation_model(obs: Any) -> OrientLineModel:
    candidates = list(getattr(obs, 'candidates', []) or [])
    symbol_count = len(candidates)
    file_count = _file_count_from_candidates(candidates)
    if getattr(obs, 'error', ''):
        result = 'failed'
    elif symbol_count == 0:
        result = 'no symbols'
    elif file_count <= 1:
        result = _plural(symbol_count, 'symbol')
    else:
        result = f'{_plural(symbol_count, "symbol")} · {_plural(file_count, "file")}'
    return find_symbols_action_model(obs).with_result(result)


def read_line_range_from_action(action: Any) -> str:
    view_range = getattr(action, 'view_range', None)
    start = int(getattr(action, 'start', 0) or 0)
    end = int(getattr(action, 'end', -1) or -1)
    if isinstance(view_range, list) and len(view_range) >= 2:
        return f'lines {view_range[0]}–{view_range[1]}'
    if start not in (0, 1) or end != -1:
        first = max(1, start)
        last = str(end) if end != -1 else 'EOF'
        return f'lines {first}–{last}'
    return 'lines 1–EOF'


def file_read_action_model(action: Any) -> OrientLineModel:
    path = getattr(action, 'path', '') or ''
    symbol = (
        getattr(action, 'qualified_name', '')
        or getattr(action, 'symbol_name', '')
        or getattr(action, 'symbol', '')
    )
    target = _display_path(path)
    if symbol:
        target = f'{target}  {symbol}'.strip()
    return OrientLineModel(
        tool='read_file',
        icon='↳',
        verb='Read',
        target=target or 'file',
        result=read_line_range_from_action(action),
    )


def file_read_observation_model(obs: Any) -> OrientLineModel:
    path = getattr(obs, 'path', '') or ''
    return OrientLineModel(
        tool='read_file',
        icon='↳',
        verb='Read',
        target=_display_path(path) or 'file',
        result='',
    )


def read_symbols_action_model(action: Any) -> OrientLineModel:
    targets = list(getattr(action, 'targets', []) or [])
    path = getattr(action, 'path', '') or ''
    target = f'{_plural(len(targets), "symbol")} in {_display_path(path)}'.strip()
    return OrientLineModel(
        tool='read_symbols',
        icon='↳',
        verb='Read',
        target=target or _plural(len(targets), 'symbol'),
        result='…',
    )


def read_symbols_observation_model(obs: Any) -> OrientLineModel:
    results = list(getattr(obs, 'results', []) or [])
    return OrientLineModel(
        tool='read_symbols',
        icon='↳',
        verb='Read',
        target=f'{_plural(len(results), "symbol")} in {_display_path(getattr(obs, "path", ""))}'.strip(),
        result=read_symbols_result(results, error=str(getattr(obs, 'error', '') or '')),
    )


def read_symbols_result(results: list[Any], *, error: str = '') -> str:
    if error:
        return 'failed'
    if not results:
        return 'no symbols'
    counts: dict[str, int] = {}
    for item in results:
        raw = str(item.get('status') if isinstance(item, dict) else 'unknown')
        status = raw.replace('_', ' ').strip().lower() or 'unknown'
        counts[status] = counts.get(status, 0) + 1
    if set(counts) == {'resolved'}:
        return f'{counts["resolved"]} resolved'
    order = ('resolved', 'ambiguous', 'not found', 'not_found', 'unknown')
    parts: list[str] = []
    used: set[str] = set()
    for key in order:
        if key not in counts:
            continue
        label = key.replace('_', ' ')
        parts.append(f'{counts[key]} {label}')
        used.add(key)
    for key in sorted(set(counts) - used):
        parts.append(f'{counts[key]} {key}')
    return ', '.join(parts)


def lsp_action_model(action: Any) -> OrientLineModel:
    command = getattr(action, 'command', '') or 'query'
    symbol = getattr(action, 'symbol', '') or ''
    file = getattr(action, 'file', '') or ''
    target = f'{command} · {symbol or _display_path(file)}'.strip(' ·')
    return OrientLineModel(
        tool='lsp',
        icon='≡',
        verb='Analyzed',
        target=target or command,
        result='…',
    )


def lsp_observation_model(
    obs: Any, pending: OrientLineModel | None = None
) -> OrientLineModel:
    base = pending or OrientLineModel(
        tool='lsp',
        icon='≡',
        verb='Analyzed',
        target='query',
        result='…',
    )
    return base.with_result(
        lsp_result(
            command=_command_from_target(base.target),
            content=str(getattr(obs, 'content', '') or ''),
            available=bool(getattr(obs, 'available', True)),
        )
    )


def _command_from_target(target: str) -> str:
    return (target or '').split('·', 1)[0].strip()


def lsp_result(*, command: str, content: str, available: bool = True) -> str:
    if not available:
        return 'unavailable'
    cmd = (command or '').strip().lower()
    payload = _json_payload(content)
    if cmd in {'hover'}:
        return 'completed'
    if cmd in {'diagnostics', 'get_diagnostics'}:
        count = _extract_json_list_count(payload, 'diagnostics', 'issues')
        if count is None:
            count = _count_result_lines(content)
        return 'clean' if count == 0 else _plural(count, 'issue')
    if cmd in {'code_action', 'code_actions'}:
        count = _extract_json_list_count(payload, 'actions', 'code_actions')
        if count is None:
            count = _count_result_lines(content)
        return _plural(count, 'action')
    if cmd in {'list_symbols', 'symbols'}:
        count = _extract_json_list_count(payload, 'symbols', 'symbol_list')
        if count is None:
            count = _count_result_lines(content)
        return _plural(count, 'symbol')
    if cmd in {'find_definition', 'definition', 'goto_def', 'def'}:
        count = _extract_json_list_count(payload, 'definitions', 'locations', 'results')
        if count is None:
            count = _count_result_lines(content)
        return _plural(count, 'result')
    if cmd in {'find_references', 'references', 'refs', 'ref'}:
        count = _extract_json_list_count(payload, 'references', 'locations', 'results')
        if count is None:
            count = _count_result_lines(content)
        return _plural(count, 'result')
    count = _count_collection(payload)
    if count is not None:
        return _plural(count, 'result')
    return 'completed' if content.strip() else 'no output'


def analyze_action_model(action: Any) -> OrientLineModel:
    command = getattr(action, 'command', '') or 'tree'
    path = getattr(action, 'path', '') or '.'
    return OrientLineModel(
        tool='analyze_project_structure',
        icon='≡',
        verb='Analyzed',
        target=f'{command} · {_display_path(path)}'.strip(' ·'),
        result='…',
    )


def analyze_observation_model(obs: Any) -> OrientLineModel:
    return analyze_action_model(obs).with_result(
        analyze_result(
            command=str(getattr(obs, 'command', '') or ''),
            content=str(getattr(obs, 'content', '') or ''),
            error=str(getattr(obs, 'error', '') or ''),
        )
    )


def analyze_result(*, command: str, content: str, error: str = '') -> str:
    if error:
        return 'failed'
    if not (content or '').strip():
        return 'no output'
    cmd = (command or '').strip().lower()
    payload = _json_payload(content)
    if cmd == 'callers':
        count = _extract_json_list_count(payload, 'callers', 'results')
        if count is None:
            count = _count_result_lines(content)
        return _plural(count, 'caller')
    if cmd in {'dependencies', 'deps'}:
        count = _extract_json_list_count(payload, 'dependencies', 'deps', 'results')
        if count is None:
            count = _count_result_lines(content)
        return f'{count} deps'
    if cmd in {
        'tree',
        'imports',
        'file_outline',
        'symbols',
        'recent',
        'semantic_search',
    }:
        return 'completed'
    return 'completed'


def mcp_action_model(action: Any) -> OrientLineModel | None:
    name = str(getattr(action, 'name', '') or '')
    args = getattr(action, 'arguments', None) or {}
    if name not in ORIENT_MCP_TOOL_NAMES:
        return None
    if name == 'web_search_exa':
        return OrientLineModel(
            tool='web_search',
            icon='⚐',
            verb='Searched',
            target=_quote(args.get('query'), fallback='query'),
            result='…',
            area='web',
        )
    if name in {'web_fetch_exa', '__native_web_fetch__', 'fetch'}:
        return OrientLineModel(
            tool='web_fetch',
            icon='⚐',
            verb='Fetched',
            target=_fetch_target(args),
            result='…',
            area='web',
        )
    if name == 'resolve-library-id':
        library = args.get('libraryName') or args.get('library_name') or ''
        query = args.get('query') or ''
        return OrientLineModel(
            tool='docs_resolve',
            icon='⚐',
            verb='Resolved',
            target=_library_target(library, query),
            result='…',
            area='docs',
        )
    if name == 'query-docs':
        library = args.get('libraryId') or args.get('library_id') or ''
        query = args.get('query') or ''
        return OrientLineModel(
            tool='docs_query',
            icon='⚐',
            verb='Queried',
            target=_library_target(library, query),
            result='…',
            area='docs',
        )
    return None


def mcp_observation_model(
    obs: Any, pending: OrientLineModel | None = None
) -> OrientLineModel | None:
    action_like = pending or mcp_action_model(obs)
    if action_like is None:
        return None
    return action_like.with_result(
        mcp_result(action_like.tool, str(getattr(obs, 'content', '') or ''))
    )


def mcp_result(tool: str, content: str) -> str:
    payload = _json_payload(content)
    if _payload_failed(payload):
        return 'failed'
    count = _count_collection(payload)
    if count is None:
        return 'results'
    return _plural(count, 'result')


def _library_target(library: Any, query: Any) -> str:
    lib = str(library or '').strip()
    q = str(query or '').strip()
    if lib and q:
        return f'{lib} · "{q}"'
    return lib or (f'"{q}"' if q else 'docs')


def _fetch_target(args: dict[str, Any]) -> str:
    urls = args.get('urls') or args.get('url') or []
    if isinstance(urls, str):
        urls = [urls] if urls.strip() else []
    if not isinstance(urls, list) or not urls:
        return 'web'
    first = str(urls[0])
    parsed = urlparse(first)
    host = parsed.netloc or parsed.path.split('/')[0]
    path = parsed.path if parsed.netloc else ''
    label = host
    if len(urls) == 1 and path and path != '/':
        label = f'{host}{path}'
    return shorten_middle(label, max_len=52, head_min=18)


_CHECKPOINT_VERBS: dict[str, str] = {
    'save': 'Saved',
    'view': 'Listed',
    'revert': 'Reverted',
    'clear': 'Cleared',
}


def checkpoint_target(action: Any) -> str:
    label = str(getattr(action, 'label', '') or '').strip()
    if label:
        return label
    command = str(getattr(action, 'command', '') or 'save').strip().lower()
    checkpoint_id = str(getattr(action, 'checkpoint_id', '') or '').strip()
    if command == 'revert' and checkpoint_id:
        return checkpoint_id[:12]
    return command or 'checkpoint'


def checkpoint_action_model(action: Any) -> OrientLineModel:
    command = str(getattr(action, 'command', '') or 'save').strip().lower()
    verb = _CHECKPOINT_VERBS.get(command, 'Checkpoint')
    return OrientLineModel(
        tool='checkpoint',
        icon='',
        verb=verb,
        target=checkpoint_target(action),
        result='…',
        area='workspace',
    )


def _checkpoint_summary_from_obs(obs: Any) -> str:
    content = str(getattr(obs, 'content', '') or '').strip()
    if content.startswith('{'):
        try:
            import json

            parsed = json.loads(content)
            summary = parsed.get('summary')
            if isinstance(summary, str) and summary.strip():
                return summary.strip()
        except json.JSONDecodeError:
            pass
    if content.startswith('[CHECKPOINT]'):
        return content.removeprefix('[CHECKPOINT]').strip()
    if content.startswith('[ROLLBACK]'):
        return content.removeprefix('[ROLLBACK]').strip()
    return content.split('\n', 1)[0].strip() if content else ''


def checkpoint_result(obs: Any) -> str:
    if not getattr(obs, 'ok', True):
        reason = str(getattr(obs, 'reason', '') or getattr(obs, 'status', '') or '')
        return 'failed' if not reason else reason[:40]
    data = getattr(obs, 'data', None)
    if isinstance(data, dict):
        label = str(data.get('label', '') or '').strip()
        if label:
            return label[:44]
    summary = _checkpoint_summary_from_obs(obs)
    if summary:
        return summary[:44] if len(summary) > 44 else summary
    if getattr(obs, 'changed_state', False):
        return 'saved'
    return 'completed'


def checkpoint_observation_model(
    obs: Any, pending: OrientLineModel | None = None
) -> OrientLineModel:
    base = pending or checkpoint_action_model(obs)
    return base.with_result(checkpoint_result(obs))


def checkpoint_think_orient_model(
    *, detail: str = '', text: str = '', source_tool: str = ''
) -> OrientLineModel:
    del source_tool
    payload = (detail or text or '').strip()
    lowered = payload.lower()
    if 'revert' in lowered or 'rollback' in lowered:
        verb = 'Reverted'
    elif 'save' in lowered or 'saved' in lowered:
        verb = 'Saved'
    else:
        verb = 'Checkpoint'
    target = (
        payload[:52] + ('...' if len(payload) > 52 else '') if payload else 'checkpoint'
    )
    return OrientLineModel(
        tool='checkpoint',
        icon='',
        verb=verb,
        target=target,
        result='completed',
        area='workspace',
    )
