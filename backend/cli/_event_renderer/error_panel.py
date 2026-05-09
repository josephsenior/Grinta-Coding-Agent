"""ErrorGuidance rule list + error/notice panel builders.

The original :func:`_error_guidance` was a 300-line ``if`` chain
(cyclomatic complexity 28).  It is now expressed as a declarative tuple of
:class:`_GuidanceRule` entries that are evaluated in order; the first match
wins and returns its :class:`ErrorGuidance`.  Adding a new rule no longer
inflates the function's complexity.

Rules are now organized into categories under ``error_categories/`` for
easier maintenance.  Each rule includes an ``error_code`` for user reference.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from backend.cli._event_renderer.constants import (
    CRITICAL_ERROR_FRAGMENTS,
    RECOVERABLE_NOTICE_FRAGMENTS,
)
from backend.cli._event_renderer.error_categories import (
    ALL_GUIDANCE_RULES,
    NOTICE_TITLE_RULES,
)
from backend.cli._event_renderer.panels import ErrorGuidance
from backend.cli._event_renderer.text_utils import (
    contains_any,
    error_panel_outer_width,
    error_panel_text_wrap_width,
    wrap_panel_text_block,
)
from backend.cli.layout_tokens import (
    CALLOUT_PANEL_PADDING,
    LIVE_PANEL_ACCENT_STYLE,
)
from backend.cli.theme import (
    CLR_META,
    CLR_RECOVERY_HINT,
    CLR_RECOVERY_HINT_DIM,
    CLR_WARN_BODY,
    CLR_WARN_ICON,
)
from backend.ledger.observation.error import (
    ERROR_CATEGORY_AUTH,
    ERROR_CATEGORY_MODEL_NOT_FOUND,
    ERROR_CATEGORY_NETWORK,
    ERROR_CATEGORY_RATE_LIMIT,
    ERROR_CATEGORY_RUNTIME_DISCONNECTED,
    ERROR_CATEGORY_TIMEOUT,
)

# Categories that should be rendered as calm notices rather than red errors.
_NOTICE_CATEGORIES: frozenset[str] = frozenset(
    {
        ERROR_CATEGORY_RATE_LIMIT,
        ERROR_CATEGORY_TIMEOUT,
        ERROR_CATEGORY_NETWORK,
    }
)

# Categories that are hard failures — always red, never a notice.
_CRITICAL_CATEGORIES: frozenset[str] = frozenset(
    {
        ERROR_CATEGORY_AUTH,
        ERROR_CATEGORY_MODEL_NOT_FOUND,
        ERROR_CATEGORY_RUNTIME_DISCONNECTED,
    }
)


@dataclass(frozen=True)
class _GuidanceRule:
    """A single rule in the guidance dispatch table."""

    matches: Callable[[str], bool]
    guidance: ErrorGuidance


def use_recoverable_notice_style(
    error_text: str,
    *,
    error_category: str | None = None,
) -> bool:
    """True for transient provider/network hiccups; False for hard failures.

    When *error_category* is provided (set by RecoveryService from the actual
    exception type) it is used directly — no text parsing.  Text matching is
    the fallback for system messages that don't originate from RecoveryService.
    """
    # Deterministic path: category was set at the source.
    if error_category is not None:
        if error_category in _CRITICAL_CATEGORIES:
            return False
        if error_category in _NOTICE_CATEGORIES:
            return True
        # ERROR_CATEGORY_CONTEXT_WINDOW: hard stop, not recoverable notice.
        return False

    # Fallback: text-based heuristics for system messages (no error_category).
    lower = error_text.lower()
    if contains_any(lower, CRITICAL_ERROR_FRAGMENTS):
        return False
    if contains_any(lower, RECOVERABLE_NOTICE_FRAGMENTS):
        return True
    return False


def split_error_text(error_text: str) -> tuple[str, str]:
    """Split error text into a short summary line and optional detail block."""
    cleaned = re.sub(
        r'<APP_RESULT_VALIDATION>.*?(?:</APP_RESULT_VALIDATION>|$)',
        '',
        error_text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    cleaned = re.sub(r'\[TOOL_FALLBACK\].*?(?:\n|$)', '', cleaned)
    stripped = cleaned.strip()
    if not stripped:
        return 'Unknown error', ''

    lines = stripped.splitlines()
    idx = 0
    while idx < len(lines):
        head = lines[idx].strip()
        if head and head.upper() not in ('ERROR:', 'ERROR'):
            break
        idx += 1
    if idx >= len(lines):
        return 'Unknown error', ''
    summary = lines[idx].strip() or 'Unknown error'
    detail = '\n'.join(line.rstrip() for line in lines[idx + 1 :]).strip()
    if len(detail) > 3000:
        omitted = len(detail) - 3000
        detail = (
            detail[:3000]
            + f'\n... ({omitted:,} more characters omitted — full output in logs)'
        )
    return summary, detail


# ---------------------------------------------------------------------------
# Guidance rules — now imported from error_categories/ package
# ---------------------------------------------------------------------------

_GUIDANCE_RULES: tuple[_GuidanceRule, ...] = ALL_GUIDANCE_RULES
_NOTICE_TITLE_RULES: tuple[tuple[Callable[[str], bool], str], ...] = NOTICE_TITLE_RULES


def error_guidance(error_text: str) -> ErrorGuidance | None:
    """Return actionable recovery steps for common CLI error patterns."""
    lower = error_text.lower()
    for rule in _GUIDANCE_RULES:
        if rule.matches(lower):
            return rule.guidance
    return None


# ---------------------------------------------------------------------------
# Recovery / panel chrome
# ---------------------------------------------------------------------------


def build_recovery_text(
    guidance: ErrorGuidance,
    *,
    for_notice: bool = False,
    wrap_width: int | None = None,
) -> Text:
    """Render a guidance block for the error / notice panel."""
    recovery = Text()
    if for_notice:
        recovery.append('Next steps\n', style=f'bold dim {CLR_RECOVERY_HINT}')
        sum_style = CLR_RECOVERY_HINT
        step_style = CLR_RECOVERY_HINT_DIM
    else:
        recovery.append('What you can try\n', style=CLR_WARN_ICON)
        sum_style = CLR_WARN_BODY
        step_style = CLR_WARN_BODY
    if guidance.summary and not guidance.omit_summary_in_recovery and not for_notice:
        sum_block = wrap_panel_text_block(guidance.summary, wrap_width=wrap_width)
        recovery.append(sum_block, style=sum_style)
        if guidance.steps:
            recovery.append('\n', style=sum_style)
    # Show error code for user reference (dimmed so it doesn't distract)
    if guidance.error_code:
        recovery.append(f'[{guidance.error_code}]\n', style=f'dim {CLR_META}')
    for index, step in enumerate(guidance.steps, start=1):
        line = f'{index}. {step}'
        line = wrap_panel_text_block(line, wrap_width=wrap_width)
        recovery.append(line, style=step_style)
        if index < len(guidance.steps):
            recovery.append('\n', style=step_style)
    return recovery


def notice_panel_title(error_text: str, *, error_category: str | None = None) -> str:
    """Short cyan banner title for recoverable (notice-style) issues."""
    # Deterministic path: use category when available.
    if error_category == ERROR_CATEGORY_RATE_LIMIT:
        return 'Rate or quota limit'
    if error_category == ERROR_CATEGORY_TIMEOUT:
        return 'Request timed out'
    if error_category == ERROR_CATEGORY_NETWORK:
        return 'Connection issue'
    # Fallback: text matching for system messages.
    lower = error_text.lower()
    for matcher, label in _NOTICE_TITLE_RULES:
        if matcher(lower):
            return label
    return 'Heads-up'


def build_llm_stream_fallback_panel() -> Panel:
    """Compact callout when streaming stalls and the engine retries."""
    body = Group(
        Text(
            'The first streamed tokens took longer than expected, so Grinta is '
            'retrying the same completion in one shot (non-streaming).',
            style=LIVE_PANEL_ACCENT_STYLE,
        ),
        Text(
            'You do not need to do anything—this is common on busy endpoints.',
            style=f'dim {CLR_META}',
        ),
    )
    return Panel(
        body,
        title=Text('ℹ  Still Working', style=f'bold {LIVE_PANEL_ACCENT_STYLE}'),
        title_align='left',
        border_style=LIVE_PANEL_ACCENT_STYLE,
        box=box.ROUNDED,
        padding=(0, 1),
    )


def build_retry_panel(
    attempt: int,
    max_attempts: int,
    *,
    prefix: str = 'Retrying',
    kind: str | None = None,
    eta: float | None = None,
) -> Panel:
    """Compact callout when automatic retry is in progress."""
    parts = [f'{prefix} ({attempt}/{max_attempts})']
    if kind:
        parts.append(str(kind).upper())
    if eta is not None and eta > 0:
        eta_str = f'{eta:.0f}s' if eta >= 1 else '<1s'
        parts.append(f'ETA {eta_str}')
    title = Text(' ↻ ', style=f'bold {LIVE_PANEL_ACCENT_STYLE}') + Text(
        ' '.join(parts), style=LIVE_PANEL_ACCENT_STYLE
    )
    body = Text(
        'Automatic retry is running. No action needed unless retries exhaust.',
        style=f'dim {CLR_META}',
    )
    return Panel(
        body,
        title=title,
        title_align='left',
        border_style=LIVE_PANEL_ACCENT_STYLE,
        box=box.ROUNDED,
        padding=(0, 1),
    )


def _resolve_panel_headline(
    error_text: str,
    *,
    summary: str,
    use_notice: bool,
    guidance: ErrorGuidance | None,
) -> str:
    if guidance is not None and 'syntax validation failed' in error_text.lower():
        return guidance.summary
    if use_notice and guidance is not None:
        return guidance.summary
    return summary


def build_error_panel(
    error_text: str,
    *,
    title: str = 'Error',
    accent_style: str = 'red',
    force_notice: bool | None = None,
    error_category: str | None = None,
    content_width: int | None = None,
) -> Panel | Text:
    """Render a structured panel with recovery guidance when available."""
    # Rate limit errors: return a compact single-line notice, skip the full panel.
    # Use error_category when available; fall back to guidance text code.
    is_rate_limit = error_category == ERROR_CATEGORY_RATE_LIMIT
    if not is_rate_limit:
        guidance = error_guidance(error_text)
        is_rate_limit = (
            guidance is not None
            and guidance.error_code is not None
            and guidance.error_code.startswith('ERR-RATE')
        )
    else:
        guidance = error_guidance(error_text)
    if is_rate_limit:
        return Text(
            'Rate or quota limit reached — retrying automatically.',
            style=f'dim {CLR_META}',
        )
    wrap_w = error_panel_text_wrap_width(content_width)
    summary, detail = split_error_text(error_text)
    use_notice = (
        force_notice
        if force_notice is not None
        else use_recoverable_notice_style(error_text, error_category=error_category)
    )
    border = LIVE_PANEL_ACCENT_STYLE if use_notice else accent_style
    body_parts = _build_error_body(
        error_text=error_text,
        summary=summary,
        detail=detail,
        guidance=guidance,
        use_notice=use_notice,
        accent_style=accent_style,
        wrap_w=wrap_w,  # type: ignore[arg-type]
    )
    panel_title = _build_panel_title(
        title=title,
        error_text=error_text,
        error_category=error_category,
        use_notice=use_notice,
        accent_style=accent_style,
    )
    notice_pad = (0, 1) if use_notice else CALLOUT_PANEL_PADDING
    panel_kw: dict[str, Any] = {
        'title': panel_title,
        'title_align': 'left',
        'border_style': border,
        'box': box.ROUNDED,
        'padding': notice_pad,
    }
    outer = error_panel_outer_width(content_width)
    if outer is not None:
        panel_kw['width'] = outer
    return Panel(Group(*body_parts), **panel_kw)


def _build_error_body(
    *,
    error_text: str,
    summary: str,
    detail: str,
    guidance: Any,
    use_notice: bool,
    accent_style: str,
    wrap_w: int,
) -> list[Any]:
    headline_style = (
        f'bold {LIVE_PANEL_ACCENT_STYLE}' if use_notice else f'{accent_style} bold'
    )
    detail_style = f'dim {CLR_META}' if use_notice else f'{accent_style} dim'

    headline = _resolve_panel_headline(
        error_text, summary=summary, use_notice=use_notice, guidance=guidance
    )
    headline = wrap_panel_text_block(headline, wrap_width=wrap_w)
    body_parts: list[Any] = [Text(headline, style=headline_style)]
    if guidance is None and detail:
        body_parts.append(
            Text(wrap_panel_text_block(detail, wrap_width=wrap_w), style=detail_style)
        )
    if guidance is not None:
        body_parts.append(Text(''))
        body_parts.append(
            build_recovery_text(guidance, for_notice=use_notice, wrap_width=wrap_w)
        )
    return body_parts


def _build_panel_title(
    *,
    title: str,
    error_text: str,
    error_category: str | None = None,
    use_notice: bool,
    accent_style: str,
) -> Text:
    if use_notice:
        accent = LIVE_PANEL_ACCENT_STYLE
        panel_label = notice_panel_title(error_text, error_category=error_category)
        return Text(f'ℹ  {panel_label}', style=f'bold {accent}')
    return Text(title.strip() or 'Error', style=f'{accent_style} bold')


__all__ = [
    'build_error_panel',
    'build_llm_stream_fallback_panel',
    'build_recovery_text',
    'build_retry_panel',
    'error_guidance',
    'notice_panel_title',
    'split_error_text',
    'use_recoverable_notice_style',
]
