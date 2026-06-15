"""Lightweight automatic context for non-trivial coding tasks."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from backend.context.context_explorer import (
    ContextCandidate,
    explore_context,
    git_status_lines,
)
from backend.core.workspace_resolution import resolve_cli_workspace_directory

_CHANGE_TERMS = frozenset(
    {
        'add',
        'build',
        'change',
        'create',
        'delete',
        'edit',
        'fix',
        'implement',
        'modify',
        'patch',
        'refactor',
        'remove',
        'rename',
        'update',
    }
)

_CODE_TERMS = frozenset(
    {
        'api',
        'backend',
        'bug',
        'class',
        'cli',
        'code',
        'component',
        'endpoint',
        'feature',
        'file',
        'frontend',
        'function',
        'implementation',
        'method',
        'module',
        'repo',
        'service',
        'test',
        'tool',
        'ui',
    }
)

_READ_ONLY_TERMS = frozenset(
    {
        'analysis',
        'analyze',
        'audit',
        'explain',
        'opinion',
        'review',
        'summarize',
    }
)

_SOURCE_EXT_RE = re.compile(
    r'\.(py|ts|tsx|js|jsx|go|rs|java|kt|cs|cpp|c|h|hpp|rb|php|swift|vue|svelte)\b',
    re.IGNORECASE,
)


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ''
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict):
            text = item.get('text')
            if isinstance(text, str):
                parts.append(text)
    return '\n'.join(parts)


def _last_user_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get('role') != 'user':
            continue
        return _message_text(message.get('content')).strip()
    return ''


def _tokens(text: str) -> set[str]:
    return set(re.findall(r'[a-z0-9_]+', text.lower()))


def _looks_read_only(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return True
    words = _tokens(lowered)
    if lowered.endswith('?') or re.match(
        r'^(what|why|how|which|where|when|can|could|would|should|is|are)\b',
        lowered,
    ):
        return True
    if words & _CHANGE_TERMS:
        return False
    return bool(words & _READ_ONLY_TERMS)


def _looks_like_coding_task(text: str) -> bool:
    if len(text.strip()) < 12 or _looks_read_only(text):
        return False
    words = _tokens(text)
    if not (words & _CHANGE_TERMS):
        return False
    return bool(words & _CODE_TERMS or _SOURCE_EXT_RE.search(text))


def _source_name(source: Any) -> str:
    name = getattr(source, 'name', None)
    if isinstance(name, str):
        return name
    value = getattr(source, 'value', None)
    if isinstance(value, str):
        return value
    return str(source or '')


def _already_started_current_turn(state: Any) -> bool:
    history = getattr(state, 'history', None)
    if not isinstance(history, list) or not history:
        return False

    last_user_index = -1
    for index, event in enumerate(history):
        if type(event).__name__ != 'MessageAction':
            continue
        if _source_name(getattr(event, 'source', None)).upper() == 'USER':
            last_user_index = index

    if last_user_index < 0:
        return False

    ignored = {'SystemMessageAction', 'StatusObservation'}
    return any(type(event).__name__ not in ignored for event in history[last_user_index + 1 :])


def _format_list(label: str, values: list[str]) -> str:
    if not values:
        return f'- {label}: none detected'
    return f'- {label}: ' + '; '.join(values)


def _format_candidate_lines(candidates: Sequence[ContextCandidate]) -> list[str]:
    if not candidates:
        return ['- Ranked candidates: none from cheap deterministic signals']
    lines = ['- Ranked candidates:']
    for index, candidate in enumerate(candidates, 1):
        reasons = '; '.join(candidate.reasons[:3])
        symbols = ''
        if candidate.symbols:
            symbols = f" | symbols: {', '.join(candidate.symbols)}"
        lines.append(
            f'  {index}. {candidate.path} (score {candidate.score}; {reasons}{symbols})'
        )
    return lines


def build_coding_preflight_block(
    messages: list[Any],
    state: Any,
    config: Any,
    *,
    mode: str,
) -> str:
    """Build a small first-turn repo snapshot for likely coding tasks."""
    if mode.strip().lower() == 'chat':
        return ''
    if _already_started_current_turn(state):
        return ''

    task = _last_user_text(messages)
    if not _looks_like_coding_task(task):
        return ''

    root = resolve_cli_workspace_directory(config)
    lines = [
        '<CODING_PREFLIGHT>',
        'Automatic context explorer for this coding task:',
    ]
    if root is not None:
        result = explore_context(task, root)
        lines.append(f'- Workspace: {result.workspace}')
        lines.append(_format_list('Dirty files', git_status_lines(root)))
        lines.extend(_format_candidate_lines(result.candidates))
    else:
        lines.append('- Workspace: unavailable')
    lines.extend(
        [
            '- Treat candidates as hints; verify current source before editing.',
            '</CODING_PREFLIGHT>',
        ]
    )
    return '\n'.join(lines)


__all__ = ['build_coding_preflight_block']
