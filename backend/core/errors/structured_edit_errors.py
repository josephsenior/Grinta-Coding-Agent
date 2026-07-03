"""Compact error formatting for file-edit and other agent tool failures."""

from __future__ import annotations

import re
from typing import Any, NoReturn

from backend.core.errors import FunctionCallValidationError, ToolExecutionError

_FILES_UNMODIFIED = 'No files were modified. Re-read the file and retry.'

_SYMBOL_AMBIGUITY_HINT = (
    'Retry with path + qualified_name + symbol_kind, or use symbol_id.'
)


def compact_symbol_candidates(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for candidate in candidates:
        entry = {
            key: candidate[key]
            for key in ('symbol_id', 'qualified_name', 'path', 'start_line')
            if candidate.get(key) is not None
        }
        if entry:
            compact.append(entry)
    return compact


def symbol_ambiguity_summary(symbol_name: str, candidates: list[dict[str, Any]]) -> str:
    count = len(candidates)
    return (
        f"symbol '{symbol_name}' is ambiguous ({count} matches).\n"
        f'{_SYMBOL_AMBIGUITY_HINT}'
    )


def extract_syntax_line(message: str) -> int | None:
    for pattern in (
        r'(?i)\bline\s+(\d{1,6})\b',
        r'line\s+(\d+)',
    ):
        match = re.search(pattern, message)
        if match:
            return int(match.group(1))
    return None


def compact_syntax_detail(message: str) -> str:
    """Return a short syntax detail without content-context excerpts."""
    text = (message or '').strip()
    if not text:
        return ''
    if 'Content context:' in text:
        text = text.split('Content context:', 1)[0].strip()
    text = text.replace('File has syntax errors.', '')
    text = text.replace('INTRODUCED_SYNTAX_ERROR:', '').strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        if line.startswith(('SyntaxError:', 'IndentationError:', 'TabError:')):
            return line
    return lines[0] if lines else text[:240]


def summarize_editor_error(result: Any) -> tuple[str, str, bool, dict[str, Any]]:
    """Map a FileEditor ToolResult failure to compact summary fields."""
    error_code = str(getattr(result, 'error_code', None) or 'EDITOR_ERROR')
    operation = str(getattr(result, 'operation', None) or 'edit')
    retryable = bool(getattr(result, 'retryable', True))
    if error_code == 'UNDO_NO_PRIOR_VERSION':
        retryable = False
    metadata = getattr(result, 'metadata', None)
    extra: dict[str, Any] = {}
    if isinstance(metadata, dict) and metadata.get('match_count') is not None:
        extra['match_count'] = metadata['match_count']

    summaries = {
        'OLD_STRING_NOT_FOUND': 'replace_string failed: old_string not found exactly.',
        'OLD_STRING_NOT_UNIQUE': (
            'replace_string failed: old_string matched multiple occurrences.'
        ),
        'FILE_NOT_FOUND': 'file not found.',
        'INTRODUCED_SYNTAX_ERROR': 'File has syntax errors.',
        'CONTENT_APPEARS_SERIALIZED': (
            'content appears serialized (literal escape sequences).'
        ),
        'EMPTY_OLD_STRING': 'replace_string failed: old_string must not be empty.',
        'REPLACE_STRING_ERROR': 'replace_string failed.',
        'UNDO_NO_PRIOR_VERSION': (
            'undo is not available: the only recorded change for this file was creating it; '
            'the file was not modified.'
        ),
    }
    summary = summaries.get(error_code)
    if summary is None:
        raw = str(getattr(result, 'error', '') or '').strip()
        summary = raw.splitlines()[0] if raw else f'{operation} failed.'

    detail = None
    if error_code == 'INTRODUCED_SYNTAX_ERROR':
        detail = compact_syntax_detail(str(getattr(result, 'error', '') or ''))
        line = extract_syntax_line(str(getattr(result, 'error', '') or ''))
        if line is not None:
            extra['line'] = line

    return error_code, summary, retryable, {'detail': detail, **extra}


def format_agent_edit_error_message(
    context: dict[str, Any],
    *,
    fallback: str,
) -> str:
    lines = [
        fallback.rstrip('.') + '.'
        if fallback and not fallback.endswith('.')
        else fallback
    ]
    path = context.get('failed_path') or context.get('path')
    if path:
        lines.append(f'File: {path}')
    op_index = context.get('failed_op_index')
    total_ops = context.get('total_ops')
    if op_index is not None:
        if total_ops is not None:
            lines.append(f'Op index: {op_index} ({op_index + 1}/{total_ops})')
        else:
            lines.append(f'Op index: {op_index}')
    if symbol := context.get('symbol'):
        lines.append(f'Symbol: {symbol}')
    if line := context.get('line'):
        lines.append(f'Line: {line}')
    if detail := context.get('detail'):
        lines.append(f'Detail: {detail}')
    if existing := context.get('existing_content'):
        lines.append(f'Current content:\n{existing}')
    if hint := context.get('hint'):
        if hint not in fallback:
            lines.append(hint)
    if context.get('include_unmodified_notice', True) and (
        context.get('transaction_rolled_back') or context.get('files_modified', 0) == 0
    ):
        if context.get('transaction_rolled_back'):
            lines.append(f'Transaction rolled back. {_FILES_UNMODIFIED}')
        else:
            lines.append(_FILES_UNMODIFIED)
    return '\n'.join(line for line in lines if line)


def build_edit_error_tool_result(
    context: dict[str, Any],
    *,
    operation: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        'tool': 'file_edit',
        'ok': False,
        'error_code': context.get('error_code', 'STRUCTURED_EDIT_ERROR'),
        'retryable': context.get('retryable', True),
        'operation': context.get('operation') or operation,
        'files_modified': context.get('files_modified', 0),
    }
    for key in (
        'failed_op_index',
        'failed_path',
        'failed_operation',
        'total_ops',
        'path',
        'symbol',
        'line',
        'detail',
        'match_count',
        'candidates',
        'hint',
    ):
        if context.get(key) is not None:
            result[key] = context[key]
    return result


def _parse_validation_item_index(message: str) -> int | None:
    match = re.search(r'item\s+(\d+)', message)
    if match:
        return int(match.group(1))
    match = re.search(r'edits\[(\d+)\]', message)
    if match:
        return int(match.group(1))
    return None


def parse_validation_error(
    message: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    text = message.strip()
    item_index = _parse_validation_item_index(text)
    total_ops = len(payload.get('file_edits') or [])
    context: dict[str, Any] = {
        'error_code': 'VALIDATION_ERROR',
        'retryable': True,
        'files_modified': 0,
        'operation': 'multi_edit',
        'detail': text,
    }
    if item_index is not None:
        context['failed_op_index'] = item_index
        if total_ops:
            context['total_ops'] = total_ops
        file_edits = payload.get('file_edits') or []
        if 0 <= item_index < len(file_edits):
            item = file_edits[item_index]
            if isinstance(item, dict) and isinstance(item.get('path'), str):
                context['failed_path'] = item['path']
                context['path'] = item['path']

    lowered = text.lower()
    if 'symbol' in lowered and 'ambiguous' in lowered:
        context['error_code'] = 'SYMBOL_AMBIGUOUS'
        context['hint'] = _SYMBOL_AMBIGUITY_HINT
    elif (
        'could not find symbol' in lowered
        or 'symbol' in lowered
        and 'not found' in lowered
    ):
        context['error_code'] = 'SYMBOL_NOT_FOUND'
        context['hint'] = _SYMBOL_AMBIGUITY_HINT
        symbol_match = re.search(r'symbol\s+([^.\n]+)', text, flags=re.IGNORECASE)
        if symbol_match:
            context['symbol'] = symbol_match.group(1).strip('\'"')
    elif 'missing required' in lowered or 'requires' in lowered:
        context['error_code'] = 'VALIDATION_ERROR'
    return context


def normalize_edit_exception(
    exc: Exception,
    payload: dict[str, Any],
    *,
    command: str,
) -> tuple[str, dict[str, Any]]:
    if isinstance(exc, ToolExecutionError) and exc.context:
        return str(exc).strip(), build_edit_error_tool_result(
            dict(exc.context), operation=command
        )

    if isinstance(exc, FunctionCallValidationError):
        context = parse_validation_error(str(exc), payload)
        message = format_agent_edit_error_message(context, fallback=str(exc).strip())
        return message, build_edit_error_tool_result(context, operation=command)

    context = {
        'error_code': 'STRUCTURED_EDIT_ERROR',
        'retryable': False,
        'files_modified': 0,
        'detail': str(exc).strip() or exc.__class__.__name__,
    }
    message = format_agent_edit_error_message(context, fallback=str(exc).strip())
    return message, build_edit_error_tool_result(context, operation=command)


def multi_edit_raise(
    summary: str,
    *,
    error_code: str,
    path: str | None = None,
    operation: str | None = None,
    failed_op_index: int | None = None,
    total_ops: int | None = None,
    retryable: bool = True,
    detail: str | None = None,
    line: int | None = None,
    symbol: str | None = None,
    candidates: list[dict[str, Any]] | None = None,
    match_count: int | None = None,
    transaction_rolled_back: bool = False,
    hint: str | None = None,
) -> NoReturn:
    context: dict[str, Any] = {
        'error_code': error_code,
        'retryable': retryable,
        'files_modified': 0,
        'failed_path': path,
        'path': path,
        'failed_operation': operation,
        'operation': operation or 'multi_edit',
        'failed_op_index': failed_op_index,
        'total_ops': total_ops,
        'detail': detail,
        'line': line,
        'symbol': symbol,
        'match_count': match_count,
        'transaction_rolled_back': transaction_rolled_back,
        'hint': hint,
    }
    if candidates is not None:
        context['candidates'] = compact_symbol_candidates(candidates)
        if hint is None and error_code == 'SYMBOL_AMBIGUOUS':
            context['hint'] = _SYMBOL_AMBIGUITY_HINT
    message = format_agent_edit_error_message(
        context,
        fallback=summary,
    )
    clean_context = {key: value for key, value in context.items() if value is not None}
    raise ToolExecutionError(message, context=clean_context)


def normalize_editor_error_response(
    result: Any,
    *,
    path: str,
    command: str,
) -> tuple[str, dict[str, Any]]:
    """Build compact message and tool_result for a single-file editor failure."""
    error_code, summary, retryable, extra = summarize_editor_error(result)
    context: dict[str, Any] = {
        'error_code': error_code,
        'retryable': retryable,
        'operation': getattr(result, 'operation', None) or command,
        'failed_operation': getattr(result, 'operation', None) or command,
        'path': path,
        'failed_path': path,
        'files_modified': 0,
        **{key: value for key, value in extra.items() if value is not None},
    }
    message = format_agent_edit_error_message(context, fallback=summary)
    return message, build_edit_error_tool_result(context, operation=command)


def format_verification_failure_message(path: str) -> str:
    return (
        'file edit verification failed: file does not exist after edit.\n'
        f'File: {path}\n'
        'Re-read the path or retry the edit.'
    )


def build_verification_failure_tool_result(path: str) -> dict[str, Any]:
    return {
        'tool': 'file_edit',
        'ok': False,
        'error_code': 'VERIFICATION_FILE_MISSING',
        'retryable': True,
        'path': path,
        'operation': 'file_edit',
    }


def classify_search_error_message(message: str) -> str:
    lowered = (message or '').strip().lower()
    if 'timed out' in lowered:
        return 'SEARCH_TIMEOUT'
    if 'does not exist' in lowered:
        return 'PATH_NOT_FOUND'
    if 'invalid regex' in lowered or 'regex' in lowered:
        return 'INVALID_PATTERN'
    if 'requires a non-empty' in lowered:
        return 'VALIDATION_ERROR'
    if 'error running ripgrep' in lowered:
        return 'SEARCH_EXECUTION_ERROR'
    return 'SEARCH_ERROR'


def format_search_error_message(
    *,
    tool: str,
    message: str,
    pattern: str,
    path: str,
) -> str:
    summary = (message or '').splitlines()[0].strip() or f'{tool} failed.'
    lines = [summary]
    if path:
        lines.append(f'Path: {path}')
    if pattern:
        lines.append(f'Pattern: {pattern}')
    return '\n'.join(lines)


def build_search_error_observation(
    *,
    tool: str,
    message: str,
    pattern: str,
    path: str,
    retryable: bool = True,
    output_mode: str | None = None,
) -> Any:
    from backend.ledger.observation import ErrorObservation

    content = format_search_error_message(
        tool=tool,
        message=message,
        pattern=pattern,
        path=path,
    )
    obs = ErrorObservation(content)
    obs.tool_result = build_search_error_tool_result(
        tool=tool,
        message=message,
        pattern=pattern,
        path=path,
        retryable=retryable,
        output_mode=output_mode,
    )
    return obs



def build_search_error_tool_result(
    *,
    tool: str,
    message: str,
    pattern: str,
    path: str,
    retryable: bool = True,
    output_mode: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        'tool': tool,
        'ok': False,
        'error_code': classify_search_error_message(message),
        'retryable': retryable,
        'path': path,
        'pattern': pattern,
        'detail': message.splitlines()[0] if message else '',
    }
    if output_mode is not None:
        result['output_mode'] = output_mode
    return result


def compact_symbol_read_result(result: dict[str, Any]) -> dict[str, Any]:
    """Trim symbol read/find payloads for not_found and ambiguous results."""
    compact = dict(result)
    status = str(compact.get('status') or '')
    symbol_name = str(compact.get('symbol_name') or compact.get('target') or '')
    return compact
