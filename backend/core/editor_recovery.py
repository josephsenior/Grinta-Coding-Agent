"""Structured recovery guidance for file-edit failures.

Turns low-level editor/runtime errors into deterministic next-step guidance so
the agent pivots instead of repeating the same failing edit unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EditorRecoveryAdvice:
    kind: str
    preferred_tool: str
    next_action: str
    detail: str


def _python_comment_prefix_issue(
    content: str, path: str | None
) -> EditorRecoveryAdvice | None:
    suffix = Path(path or '').suffix.lower()
    if suffix != '.py':
        return None
    if re.search(r'(?m)^\s*//', content or '') is None:
        return None
    return EditorRecoveryAdvice(
        kind='python_comment_prefix',
        preferred_tool='replace_string',
        next_action='replace_string',
        detail=(
            'Python file detected with `//` comment prefix. Python comments use `#`, '
            'so repair the affected text with exact replacement instead of retrying the same write.'
        ),
    )


def classify_editor_recovery(
    message: str,
    *,
    path: str | None = None,
    tool_name: str | None = None,
    content: str | None = None,
) -> EditorRecoveryAdvice | None:
    lower = (message or '').lower()

    comment_issue = _python_comment_prefix_issue(content or '', path)
    if comment_issue is not None:
        return comment_issue

    if 'symbol ' in lower and 'not found' in lower:
        return EditorRecoveryAdvice(
            kind='symbol_not_found',
            preferred_tool='find_symbols',
            next_action='find_symbols',
            detail=(
                'The symbol lookup failed. Call `find_symbols` first to verify the live '
                'symbol name and candidates before retrying the edit.'
            ),
        )

    if 'edit verification failed' in lower:
        return EditorRecoveryAdvice(
            kind='edit_verification_failed',
            preferred_tool='read',
            next_action='read',
            detail=(
                'The write completed but verification did not prove the intended change landed cleanly. '
                'Refresh the file state, then retry once with a smaller, more targeted edit.'
            ),
        )

    if 'large existing code file overwrite blocked' in lower:
        return EditorRecoveryAdvice(
            kind='full_file_overwrite_blocked',
            preferred_tool='edit_symbols',
            next_action='edit_symbols',
            detail=(
                'Full-file overwrite was blocked on a large existing source file. Prefer edit_symbols '
                'for code or replace_string for exact text changes.'
            ),
        )

    if (
        'syntax validation failed' in lower
        or 'syntax error after edit' in lower
        or 'introduced_syntax_error' in lower
    ):
        return EditorRecoveryAdvice(
            kind='syntax_validation_failed',
            preferred_tool='read',
            next_action='read',
            detail=(
                'The edit produced invalid syntax. Re-read the affected region, then do one surgical repair '
                'with edit_symbols or replace_string instead of repeating the same full write.'
            ),
        )

    if 'edit context mismatch' in lower or 'range edit context mismatch' in lower:
        return EditorRecoveryAdvice(
            kind='range_context_mismatch',
            preferred_tool='read',
            next_action='read',
            detail=(
                'The edit context is stale or malformed. Re-read the file and retry once with '
                'edit_symbols or exact replace_string content.'
            ),
        )

    if (
        'replace failed' in lower
        or 'start line' in lower
        or 'end_line must be' in lower
    ):
        return EditorRecoveryAdvice(
            kind='range_edit_failed',
            preferred_tool='read',
            next_action='read',
            detail=(
                'The range edit inputs are invalid or stale. Re-read the file to confirm line numbers, '
                'then retry one smaller edit through edit_symbols or replace_string.'
            ),
        )

    if 'multi_edit transaction rolled back' in lower:
        return EditorRecoveryAdvice(
            kind='atomic_batch_failed',
            preferred_tool='multiedit',
            next_action='multiedit',
            detail=(
                'The atomic batch failed pre-commit. Inspect the failing item, fix that specific edit, '
                'then retry the whole batch as one transaction.'
            ),
        )

    return None


def append_editor_recovery_guidance(
    message: str,
    *,
    path: str | None = None,
    tool_name: str | None = None,
    content: str | None = None,
) -> str:
    advice = classify_editor_recovery(
        message,
        path=path,
        tool_name=tool_name,
        content=content,
    )
    if advice is None:
        return message
    if '[EDITOR_RECOVERY_REQUIRED]' in message:
        return message
    return (
        f'{message}\n\n'
        '[EDITOR_RECOVERY_REQUIRED]\n'
        f'kind={advice.kind}\n'
        f'preferred_tool={advice.preferred_tool}\n'
        f'next_action={advice.next_action}\n'
        f'{advice.detail}'
    )
