"""History flattening, MCP previews, and tool-JSON parsing helpers."""

from __future__ import annotations

import json
import os
from typing import Any

from rich.syntax import Syntax

from backend.cli._tool_display.constants import _TOOL_CALL_PREFIX
from backend.cli._tool_display.summarize import (
    _preview_result_item,
    _summarize_raw_mcp_text,
    _summarize_result_collection,
    _trunc,
    format_tool_invocation_line,
    parse_tool_arguments_json,
)
from backend.cli.theme import NAVY_BG, get_grinta_pygments_style


def flatten_tool_call_for_history(name: str, arguments: str) -> str:
    """Single line for cross-family assistant history (no raw JSON)."""
    parsed = parse_tool_arguments_json(arguments)
    if parsed is not None:
        icon, label = format_tool_invocation_line(name, parsed)
        return f'{_TOOL_CALL_PREFIX} {icon} {label}'
    return f'{_TOOL_CALL_PREFIX} {name}'


def looks_like_streaming_tool_arguments(text: str) -> bool:
    """True when *text* looks like JSON tool arguments but chunk is not flagged."""
    s = text.lstrip()
    if not s.startswith('{'):
        return False
    markers = (
        '"command"',
        '"path"',
        '"tool_name"',
        '"arguments"',
        '"function"',
    )
    return any(m in text for m in markers)


# ---------------------------------------------------------------------------
# MCP preview
# ---------------------------------------------------------------------------

_VERBOSE_MCP_JSON = os.environ.get(
    'GRINTA_CLI_VERBOSE_MCP_JSON', ''
).strip().lower() in {
    '1',
    'true',
    'yes',
}

# File read syntax highlighting
# ---------------------------------------------------------------------------
_GRINTA_FILE_READ_SYNTAX = os.environ.get(
    'GRINTA_FILE_READ_SYNTAX', ''
).strip().lower() in {
    '1',
    'true',
    'yes',
}

_FILE_READ_MAX_LINES_FOR_SYNTAX = 500


def _mcp_try_json_blob(blob: str) -> Any | None:
    s = blob.strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _mcp_github_repo_is_valid_first_item(first: Any) -> bool:
    if not isinstance(first, dict):
        return False
    if 'full_name' in first:
        return True
    return 'name' in first and isinstance(first.get('owner'), dict)


def _mcp_github_repo_extract_names(items: list[Any]) -> list[str]:
    names: list[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        fn = it.get('full_name') or it.get('name')
        if isinstance(fn, str) and fn.strip():
            names.append(fn.strip())
        if len(names) >= 4:
            break
    return names


def _mcp_github_repo_format_message(total: int, names: list[str]) -> str:
    head = ', '.join(names)
    rest = max(0, total - len(names))
    msg = f'{total} repos'
    if head:
        msg += f' · {head}'
    if rest > 0:
        msg += f' (+{rest})'
    return msg


def _mcp_summarize_github_repo_payload(
    payload: dict[str, Any], *, max_len: int
) -> str | None:
    items = payload.get('items')
    if not isinstance(items, list) or not items:
        return None
    if not _mcp_github_repo_is_valid_first_item(items[0]):
        return None
    total = payload.get('total_count')
    if not isinstance(total, int):
        total = len(items)
    names = _mcp_github_repo_extract_names(items)
    msg = _mcp_github_repo_format_message(total, names)
    return _trunc(msg, max_len)


def _mcp_path_entries_extract_labels(items: list[Any]) -> list[str]:
    labels: list[str] = []
    for it in items[:6]:
        if not isinstance(it, dict):
            continue
        p = it.get('path') or it.get('name')
        if isinstance(p, str) and p.strip():
            labels.append(p.strip())
    return labels


def _mcp_summarize_path_entries(items: list[Any], *, max_len: int) -> str | None:
    if not items or not isinstance(items[0], dict):
        return None
    first = items[0]
    t = first.get('type')
    if t not in {'file', 'dir', 'symlink'}:
        return None
    labels = _mcp_path_entries_extract_labels(items)
    if not labels:
        return None
    n = len(items)
    extra = max(0, n - len(labels))
    msg = f'{n} paths · ' + ', '.join(labels)
    if extra:
        msg += f' (+{extra})'
    return _trunc(msg, max_len)


def _mcp_summarize_inner_value(inner: Any, *, max_len: int) -> str | None:
    if isinstance(inner, dict):
        gh = _mcp_summarize_github_repo_payload(inner, max_len=max_len)
        if gh:
            return gh
        err = inner.get('error') or inner.get('message') or inner.get('detail')
        if isinstance(err, str) and err.strip():
            return _trunc(err.strip(), max_len)
        return None
    if isinstance(inner, list):
        tree = _mcp_summarize_path_entries(inner, max_len=max_len)
        if tree:
            return tree
        return _summarize_result_collection(inner, max_len=max_len)
    return None


def _mcp_envelope_tool_summary(data: dict[str, Any], *, max_len: int) -> str | None:
    """Summarize MCP tool JSON envelopes (``content[]`` blocks with embedded JSON text)."""
    blocks = data.get('content')
    if not isinstance(blocks, list) or not blocks:
        return None
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        raw = block.get('text')
        if not isinstance(raw, str) or not raw.strip():
            continue
        inner = _mcp_try_json_blob(raw)
        if inner is not None:
            line = _mcp_summarize_inner_value(inner, max_len=min(380, max_len))
            if line:
                parts.append(line)
                continue
        parts.append(_summarize_raw_mcp_text(raw, max_len=min(240, max_len)))
    if not parts:
        return None
    return _trunc(' · '.join(parts), max_len)


def _mcp_count_summary(data: dict[str, Any]) -> str | None:
    for count_key in ('total_count', 'count', 'matches', 'total'):
        v = data.get(count_key)
        if isinstance(v, int):
            label = data.get('query') or data.get('pattern') or ''
            return f'{v} matches' + (f' for "{_trunc(label, 40)}"' if label else '')
    return None


def _mcp_search_summary(data: dict[str, Any], content: str) -> str | None:
    tool_name = data.get('tool_name')
    if tool_name in {'grep', 'glob'} or 'grep' in content or 'glob' in content:
        results = data.get('results')
        count = (
            len(results) if isinstance(results, list) else data.get('total_count', 0)
        )
        return f'{count} matches found'
    return None


def _mcp_collection_summary(data: dict[str, Any], *, max_len: int) -> str | None:
    for list_key in ('results', 'items', 'entries', 'documents', 'matches'):
        value = data.get(list_key)
        if isinstance(value, list):
            return _summarize_result_collection(value, label=list_key, max_len=max_len)
    return None


def _mcp_text_field_summary(data: dict[str, Any], *, max_len: int) -> str | None:
    for key in ('text', 'message', 'content', 'summary', 'result', 'output'):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            return _summarize_raw_mcp_text(v, max_len=max_len)
        if isinstance(v, list) and v:
            return _summarize_result_collection(v, max_len=max_len)
        if isinstance(v, dict) and v:
            try:
                nested = json.dumps(v, ensure_ascii=False)
            except (TypeError, ValueError):
                nested = str(v)
            return _trunc(nested, max_len)
    return None


def _mcp_error_summary(data: dict[str, Any], *, max_len: int) -> str | None:
    err = data.get('error') or data.get('detail')
    if isinstance(err, str) and err.strip():
        return _trunc(err, max_len)
    if isinstance(err, dict):
        msg = err.get('message') or err.get('msg')
        if isinstance(msg, str):
            return _trunc(msg, max_len)
    return None


def _mcp_dict_preview(data: dict[str, Any], *, content: str, max_len: int) -> str:
    for builder in (
        lambda d: _mcp_envelope_tool_summary(d, max_len=max_len),
        _mcp_count_summary,
        lambda d: _mcp_search_summary(d, content),
        lambda d: _mcp_collection_summary(d, max_len=max_len),
        lambda d: _mcp_text_field_summary(d, max_len=max_len),
        lambda d: _mcp_error_summary(d, max_len=max_len),
    ):
        result = builder(data)
        if result:
            return result
    try:
        return _trunc(json.dumps(data, ensure_ascii=False), max_len)
    except (TypeError, ValueError):
        return _summarize_raw_mcp_text(content, max_len=max_len)


def mcp_result_user_preview(content: str, *, max_len: int = 400) -> str:
    """Turn MCP JSON/text tool output into a short user-facing string."""
    s = (content or '').strip()
    if not s:
        return ''
    if not s.startswith('{') and not s.startswith('['):
        return _summarize_raw_mcp_text(s, max_len=max_len)

    try:
        data = json.loads(s)
    except (json.JSONDecodeError, TypeError, ValueError):
        return _summarize_raw_mcp_text(s, max_len=max_len)

    if isinstance(data, dict):
        return _mcp_dict_preview(data, content=content, max_len=max_len)
    if isinstance(data, list) and data:
        return _summarize_result_collection(data, max_len=max_len)
    try:
        return _trunc(json.dumps(data, ensure_ascii=False), max_len)
    except (TypeError, ValueError):
        return _summarize_raw_mcp_text(s, max_len=max_len)


def mcp_result_syntax_extras(
    content: str, *, max_chars: int = 14_000
) -> list[Any] | None:
    """Rich JSON Syntax for MCP payloads — opt-in via ``GRINTA_CLI_VERBOSE_MCP_JSON``.

    Default transcripts stay one-line summaries to avoid megabyte-high cards.
    """
    if not _VERBOSE_MCP_JSON:
        return None
    s = (content or '').strip()
    if len(s) < 220 or not (s.startswith('{') or s.startswith('[')):
        return None
    try:
        data = json.loads(s)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    try:
        pretty = json.dumps(data, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return None
    if len(pretty) < 400:
        return None
    if len(pretty) > max_chars:
        body = pretty[:max_chars] + '…'
    else:
        body = pretty
    return [
        Syntax(
            body,
            'json',
            word_wrap=True,
            theme=get_grinta_pygments_style(),  # type: ignore[arg-type]
            line_numbers=False,
            background_color=NAVY_BG,
        )
    ]


def file_read_syntax_highlight(
    content: str,
    file_path: str | None = None,
    max_lines: int = _FILE_READ_MAX_LINES_FOR_SYNTAX,
) -> list[Any] | None:
    """Rich Syntax for file read content — opt-in via ``GRINTA_FILE_READ_SYNTAX``.

    Args:
        content: The file content to syntax highlight
        file_path: Optional file path for language detection
        max_lines: Maximum lines to show with syntax (default 500)

    Returns:
        List with Rich Syntax object, or None if disabled/not applicable
    """
    if not _GRINTA_FILE_READ_SYNTAX:
        return None
    s = (content or '').strip()
    if not s:
        return None
    lines = s.split('\n')
    if len(lines) > max_lines:
        return None

    # Infer language from file extension or content
    lexer = None
    if file_path:
        ext = file_path.rsplit('.', 1)[-1].lower() if '.' in file_path else ''
        lexer = _EXT_TO_LEXER.get(ext)

    # Try to detect from content
    if not lexer:
        lexer = _guess_lexer_from_content(s)

    if not lexer:
        return None

    body = s
    if len(s) > 20_000:
        body = s[:20_000] + '\n… (truncated)'

    return [
        Syntax(
            body,
            lexer,
            word_wrap=True,
            theme=get_grinta_pygments_style(),  # type: ignore[arg-type]
            line_numbers=True,
            background_color=NAVY_BG,
            padding=(1, 1),
        )
    ]


# Lexer mapping for common file extensions
_EXT_TO_LEXER: dict[str, str] = {
    'py': 'python',
    'js': 'javascript',
    'ts': 'typescript',
    'jsx': 'javascript',
    'tsx': 'typescript',
    'rb': 'ruby',
    'go': 'go',
    'rs': 'rust',
    'java': 'java',
    'c': 'c',
    'cpp': 'cpp',
    'h': 'c',
    'hpp': 'cpp',
    'cs': 'csharp',
    'php': 'php',
    'swift': 'swift',
    'kt': 'kotlin',
    'scala': 'scala',
    'sh': 'bash',
    'bash': 'bash',
    'zsh': 'bash',
    'fish': 'bash',
    'ps1': 'powershell',
    'psm1': 'powershell',
    'yaml': 'yaml',
    'yml': 'yaml',
    'json': 'json',
    'toml': 'toml',
    'xml': 'xml',
    'html': 'html',
    'css': 'css',
    'scss': 'scss',
    'less': 'less',
    'sql': 'sql',
    'md': 'markdown',
    'markdown': 'markdown',
    'r': 'r',
    'lua': 'lua',
    'pl': 'perl',
    'ex': 'elixir',
    'exs': 'elixir',
    'erl': 'erlang',
    'hs': 'haskell',
    'clj': 'clojure',
    'jl': 'julia',
    'vim': 'vim',
    'ini': 'ini',
    'cfg': 'ini',
    'conf': 'ini',
}


_SHEBANG_PATTERNS: list[tuple[str, str]] = [
    ('python', 'python'),
    ('node', 'javascript'),
    ('bash', 'bash'),
    ('sh', 'bash'),
    ('ruby', 'ruby'),
    ('perl', 'perl'),
    ('php', 'php'),
]

_CONTENT_PATTERNS: list[tuple[tuple[str, ...], str]] = [
    (('import ', 'from '), 'python'),
    (('function ', '{'), 'javascript'),
    (('def ', ':'), 'python'),
    (('package ', 'func '), 'go'),
    (('fn main',), 'rust'),
    (('public class',), 'java'),
    (('<html', '<div'), 'html'),
    (('{', ':'), 'json'),
]


def _guess_lexer_from_shebang(lines: list[str]) -> str | None:
    for line in lines:
        if line.startswith('#!'):
            for pattern, lexer in _SHEBANG_PATTERNS:
                if pattern in line:
                    return lexer
    return None


def _guess_lexer_from_content_patterns(content: str) -> str | None:
    for patterns, lexer in _CONTENT_PATTERNS:
        if all(p in content for p in patterns):
            return lexer
    return None


def _guess_lexer_from_content(content: str) -> str | None:
    """Simple heuristic to guess lexer from file content."""
    lines = content.split('\n')[:3]
    if lexer := _guess_lexer_from_shebang(lines):
        return lexer
    return _guess_lexer_from_content_patterns(content)


def _coerce_tool_args(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError, ValueError):
            return {'raw': arguments[:200]}
    return {}


def _format_tool_call(
    name: str, arguments: Any, *, use_icons: bool, lines: list[str]
) -> str | None:
    args_dict = _coerce_tool_args(arguments)
    icon, label = format_tool_invocation_line(
        name, args_dict or None, use_icons=use_icons
    )
    lines.append(f'{icon} {label}' if icon else label)
    return name


def _walk_tool_calls_dict(
    data: dict[str, Any],
    *,
    use_icons: bool,
    lines: list[str],
) -> str | None:
    if isinstance(data.get('tool_calls'), list):
        first: str | None = None
        for tc in data['tool_calls']:
            if not isinstance(tc, dict):
                continue
            fn = tc.get('function')
            if isinstance(fn, dict):
                name = _format_tool_call(
                    str(fn.get('name', 'tool')),
                    fn.get('arguments', {}),
                    use_icons=use_icons,
                    lines=lines,
                )
                first = first or name
        return first
    if 'name' in data and 'arguments' in data:
        return _format_tool_call(
            str(data.get('name', 'tool')),
            data.get('arguments'),
            use_icons=use_icons,
            lines=lines,
        )
    if isinstance(data.get('function'), dict):
        fn = data['function']
        return _format_tool_call(
            str(fn.get('name', 'tool')),
            fn.get('arguments', {}),
            use_icons=use_icons,
            lines=lines,
        )
    return None


def _walk_tool_calls_list(
    data: list[Any],
    *,
    use_icons: bool,
    lines: list[str],
) -> str | None:
    first: str | None = None
    for item in data:
        if not isinstance(item, dict):
            continue
        fn = item.get('function')
        if isinstance(fn, dict):
            name = _format_tool_call(
                str(fn.get('name', 'tool')),
                fn.get('arguments', {}),
                use_icons=use_icons,
                lines=lines,
            )
            first = first or name
    return first


def try_format_message_as_tool_json(
    content: str, *, use_icons: bool = True
) -> tuple[str, str] | None:
    """If *content* is assistant tool JSON, return (icon, friendly multiline text)."""
    from backend.cli._tool_display.headline import tool_headline

    s = content.strip()
    if not s.startswith('{') and not s.startswith('['):
        return None
    try:
        data = json.loads(s)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None

    lines: list[str] = []
    first: str | None = None
    if isinstance(data, dict):
        first = _walk_tool_calls_dict(data, use_icons=use_icons, lines=lines)
        if first is None:
            return None
    elif isinstance(data, list):
        first = _walk_tool_calls_list(data, use_icons=use_icons, lines=lines)
    else:
        return None

    if not lines:
        return None
    icon0, _ = tool_headline(first or '', use_icons=use_icons)
    return icon0, '\n'.join(lines)


# Re-export internal preview helper used by other modules in this package.
__all__ = [
    'flatten_tool_call_for_history',
    'looks_like_streaming_tool_arguments',
    'mcp_result_syntax_extras',
    'mcp_result_user_preview',
    'try_format_message_as_tool_json',
    '_preview_result_item',
]
