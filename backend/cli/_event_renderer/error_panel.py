"""ErrorGuidance rule list + error/notice panel builders.

The original :func:`_error_guidance` was a 300-line ``if`` chain
(cyclomatic complexity 28).  It is now expressed as a declarative tuple of
:class:`_GuidanceRule` entries that are evaluated in order; the first match
wins and returns its :class:`ErrorGuidance`.  Adding a new rule no longer
inflates the function's complexity.
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
from backend.cli.theme import CLR_META


def use_recoverable_notice_style(error_text: str) -> bool:
    """True for timeouts and provider hiccups; False for hard failures."""
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
    if len(detail) > 2000:
        detail = detail[:2000] + '\n... (truncated)'
    return summary, detail


# ---------------------------------------------------------------------------
# Guidance rules (declarative — order matters; first match wins)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _GuidanceRule:
    """A single rule in the guidance dispatch table."""

    matches: Callable[[str], bool]
    guidance: ErrorGuidance


def _all(*needles: str) -> Callable[[str], bool]:
    return lambda lower: all(n in lower for n in needles)


def _any(*needles: str) -> Callable[[str], bool]:
    return lambda lower: any(n in lower for n in needles)


def _has(needle: str) -> Callable[[str], bool]:
    return lambda lower: needle in lower


def _and(*preds: Callable[[str], bool]) -> Callable[[str], bool]:
    return lambda lower: all(p(lower) for p in preds)


def _no_api_key_match(lower: str) -> bool:
    if 'no api key or model configured' in lower:
        return True
    return 'initialization failed' in lower and any(
        n in lower
        for n in (
            'authenticationerror',
            'invalid api key',
            'api_key',
            'unauthorized',
            '401',
        )
    )


def _context_size_match(lower: str) -> bool:
    return 'context' in lower and any(
        n in lower for n in ('length', 'window', 'limit', 'too many tokens')
    )


_GUIDANCE_RULES: tuple[_GuidanceRule, ...] = (
    _GuidanceRule(
        _has('syntax validation failed'),
        ErrorGuidance(
            summary='Edit was not saved: the file fails a syntax check (invalid structure).',
            steps=(
                'Fix the broken brackets, quotes, or keywords in that file (the agent still sees the full tool error in context).',
                'Prefer small patches or a minimal valid stub, then iterate.',
                'Re-read the file before applying the next edit.',
            ),
            omit_summary_in_recovery=True,
        ),
    ),
    _GuidanceRule(
        _no_api_key_match,
        ErrorGuidance(
            summary='The engine could not finish startup with the current credentials.',
            steps=(
                'Restart grinta and complete onboarding so it can prompt for a model and API key.',
                'Or update settings.json with a valid provider, model, and API key before retrying.',
                'Rerun the same task after saving the new settings.',
            ),
        ),
    ),
    _GuidanceRule(
        _any(
            'resume failed',
            'no event stream',
            'session bootstrap state is incomplete',
        ),
        ErrorGuidance(
            summary='This saved session could not be reopened cleanly.',
            steps=(
                'Run /sessions and try a different session if the current one is stale or incomplete.',
                'If the session files were removed, start a new task in the current project.',
            ),
        ),
    ),
    _GuidanceRule(
        _has('pending action timed out'),
        ErrorGuidance(
            summary='A tool action ran longer than the pending-action guard window.',
            steps=(
                'The command may still be running. Verify current process/output state before retrying.',
                'For setup/install tasks, run shorter sequential commands instead of one long chained command.',
                'Increase pending_action_timeout in settings.json if your environment is consistently slow.',
            ),
        ),
    ),
    _GuidanceRule(
        _and(
            _any('call_async_from_sync', 'browser_tool'),
            _any('timeout', 'timed out'),
        ),
        ErrorGuidance(
            summary='The local runtime sync bridge timed out waiting for an async tool to finish.',
            steps=(
                'This is usually the in-process executor thread (e.g. native browser / browser-use), not the LLM provider.',
                'Close stray Chromium or Chrome processes, restart the CLI, and retry.',
                'Set GRINTA_BROWSER_TRACE=1 to print browser stage lines to stderr; optional env vars: CALL_ASYNC_LOOP_SHUTDOWN_WAIT_SEC (task cancel wait, default 2s), CALL_ASYNC_LOOP_FINALIZE_WAIT_SEC (asyncgen/executor shutdown cap, default 3s).',
                'If the action may still be running in the background, check processes before retrying.',
            ),
        ),
    ),
    _GuidanceRule(
        _and(
            _any(
                'browser screenshot timed out',
                'browser screenshot failed',
                'browser snapshot timed out',
                'snapshot timed out',
                'screenshot timed out',
                'tried compositor and window capture',
                'navigation to ',
            ),
            _any('timed out', 'timeout', 'compositor', 'window capture'),
        ),
        ErrorGuidance(
            summary='The browser tool did not finish in time.',
            steps=(
                'A JavaScript alert/confirm/prompt dialog on the page may be '
                'blocking rendering; we now auto-dismiss these before '
                'screenshots, but it can still happen on other commands. '
                'Try ``browser snapshot`` to probe DOM state without rendering.',
                'Re-run ``browser navigate`` to the same URL to reset the tab, '
                'or close stray Chrome/Chromium windows and retry.',
                'Set GRINTA_BROWSER_TRACE=1 before launching to see stage '
                'timings on stderr.',
            ),
        ),
    ),
    _GuidanceRule(
        _has('fallback completion timed out'),
        ErrorGuidance(
            summary='The non-streaming retry also hit the wait limit.',
            steps=(
                'Check your network and the provider status page, then try again.',
                'Pick another model in /settings if this endpoint is often slow.',
                'Optional: raise APP_LLM_FALLBACK_TIMEOUT_SECONDS for a longer '
                'non-streaming cap (many setups use 60s by default).',
            ),
        ),
    ),
    _GuidanceRule(
        _any(
            'automatic backoff and retry will run',
            'waiting before retrying — no action needed',
            'waiting before retrying - no action needed',
        ),
        ErrorGuidance(
            summary='Autonomous recovery is in progress.',
            steps=(
                'No action needed. Grinta already scheduled a retry.',
                'Watch the Backoff / Auto Retry status in the footer for attempt progress.',
                'If automatic retries exhaust, the prompt will return automatically.',
            ),
        ),
    ),
    _GuidanceRule(
        _has('intermediate control tool'),
        ErrorGuidance(
            summary='This was an internal control step, not a user-facing reply.',
            steps=(
                'No action is required from you.',
                'Grinta should continue the same turn and either execute the next step or finish normally.',
            ),
        ),
    ),
    _GuidanceRule(
        _any('no executable action', 'no-progress loop'),
        ErrorGuidance(
            summary='Grinta paused to avoid a no-progress loop.',
            steps=(
                'No action is required unless you want the task to continue immediately.',
                'Reply with a clearer next step or ask the agent to retry if you want it to resume.',
            ),
        ),
    ),
    _GuidanceRule(
        _any('timeout', 'timed out'),
        ErrorGuidance(
            summary="The model didn't finish within Grinta's wait window.",
            steps=(
                'Confirm your network and the provider status page, then retry.',
                'Shorter prompts or a faster model in /settings usually help.',
                'If chunks pause too long mid-stream, raise APP_LLM_STREAM_CHUNK_TIMEOUT_SECONDS '
                '(default 90s) or APP_LLM_FIRST_CHUNK_TIMEOUT_SECONDS.',
                'If streaming often stalls, Grinta may retry non-streaming automatically—'
                'watch for the cyan “Still working” note in the transcript.',
            ),
        ),
    ),
    _GuidanceRule(
        _any(
            '401',
            'unauthorized',
            'invalid api key',
            'authenticationerror',
            'api key rejected',
        ),
        ErrorGuidance(
            summary='The provider rejected the configured credentials.',
            steps=(
                'Open /settings, press k, and update the API key.',
                'Press m in /settings to confirm the selected model belongs to that provider.',
                'Send the request again after saving the updated settings.',
            ),
        ),
    ),
    _GuidanceRule(
        _any(
            '429',
            'rate limit',
            'too many requests',
            'insufficient_quota',
            'quota',
            'billing',
        ),
        ErrorGuidance(
            summary='The provider is rejecting more requests because of rate or billing limits.',
            steps=(
                'Wait a moment and retry.',
                'Switch to another model in /settings if you need to keep working right now.',
                'Check the provider dashboard for quota, spend, or billing problems.',
            ),
        ),
    ),
    _GuidanceRule(
        _any('404', 'model not found', 'does not exist', 'unknown model'),
        ErrorGuidance(
            summary='The configured model name is not available from the selected provider.',
            steps=(
                'Open /settings, press m, and pick a supported model.',
                'If you entered the model manually, include the correct provider prefix.',
            ),
        ),
    ),
    _GuidanceRule(
        _any('connection', 'connect error', 'unreachable', 'dns', 'ssl', 'certificate'),
        ErrorGuidance(
            summary='Grinta could not reach the model provider.',
            steps=(
                'Check your internet connection, VPN, proxy, or firewall rules.',
                'Retry after the connection is stable.',
            ),
        ),
    ),
    _GuidanceRule(
        _context_size_match,
        ErrorGuidance(
            summary='The request is larger than the model can accept.',
            steps=(
                'Retry with a shorter prompt or less pasted context.',
                'If you need the larger context, switch models in /settings.',
            ),
        ),
    ),
    _GuidanceRule(
        _has('budget'),
        ErrorGuidance(
            summary='The task budget blocked another model call.',
            steps=(
                'Open /settings, press b, and raise the budget.',
                'Use 0 if you want to remove the per-task budget limit.',
                'Retry the request after saving the new budget.',
            ),
        ),
    ),
    _GuidanceRule(
        _any('file not found', 'no such file', 'path does not exist'),
        ErrorGuidance(
            summary='The requested file or path was not available in the current project.',
            steps=(
                'Double-check the path and make sure the file still exists.',
                'If you moved the project, reopen grinta from the correct directory and retry.',
            ),
        ),
    ),
    _GuidanceRule(
        _any('permission denied', 'access is denied', 'forbidden', '403'),
        ErrorGuidance(
            summary='The current account or filesystem permissions are blocking the action.',
            steps=(
                'Verify the API key has access to the selected model or endpoint.',
                'If this is a local file action, reopen grinta from a writable directory and retry.',
            ),
        ),
    ),
    _GuidanceRule(
        _has('initialization failed'),
        ErrorGuidance(
            summary='Startup did not complete successfully.',
            steps=(
                'Restart grinta to try the bootstrap flow again.',
                'If it fails again, use the detail above to inspect the specific exception.',
            ),
        ),
    ),
    _GuidanceRule(
        _any(
            'verification required',
            'blind retries are blocked',
            'fresh grounding action',
        ),
        ErrorGuidance(
            summary='Grinta blocked another blind write because recent edits were followed by failing feedback.',
            steps=(
                'Read the affected file or rerun the focused failing check to get fresh evidence.',
                'After one grounding step, the agent can edit or finish again.',
            ),
        ),
    ),
    _GuidanceRule(
        _any('stuck loop detected', 'stuck recovery:', 'mandatory recovery:'),
        ErrorGuidance(
            summary='The model repeated the same action without new output.',
            steps=(
                'It is being nudged to read fresh state or run a different step.',
                'You can wait, or add a short message to redirect it.',
            ),
        ),
    ),
)


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
        recovery.append('Next steps\n', style='bold dim cyan')
        sum_style = 'cyan'
        step_style = 'dim cyan'
    else:
        recovery.append('What you can try\n', style='yellow bold')
        sum_style = 'yellow'
        step_style = 'yellow'
    if guidance.summary and not guidance.omit_summary_in_recovery and not for_notice:
        sum_block = wrap_panel_text_block(guidance.summary, wrap_width=wrap_width)
        recovery.append(sum_block, style=sum_style)
        if guidance.steps:
            recovery.append('\n', style=sum_style)
    for index, step in enumerate(guidance.steps, start=1):
        line = f'{index}. {step}'
        line = wrap_panel_text_block(line, wrap_width=wrap_width)
        recovery.append(line, style=step_style)
        if index < len(guidance.steps):
            recovery.append('\n', style=step_style)
    return recovery


_NOTICE_TITLE_RULES: tuple[tuple[Callable[[str], bool], str], ...] = (
    (_has('verification required'), 'Need fresh evidence'),
    (
        _any(
            'automatic backoff and retry',
            'waiting before retrying — no action needed',
            'waiting before retrying - no action needed',
            'autonomous recovery',
        ),
        'Autonomous recovery',
    ),
    (_any('no executable action', 'no-progress loop'), 'Paused safely'),
    (_has('intermediate control tool'), 'Continuing work'),
    (_has('fallback completion timed out'), 'Still no reply'),
    (
        _any('rate limit', 'too many requests', '429', 'quota', 'billing'),
        'Rate or quota limit',
    ),
    (
        _any('connection', 'unreachable', 'connect error', 'dns', 'ssl', 'certificate'),
        'Connection issue',
    ),
    (_has('stuck loop'), 'Stuck pattern'),
    (_any('timeout', 'timed out', 'did not answer'), 'Request timed out'),
)


def notice_panel_title(error_text: str) -> str:
    """Short cyan banner title for recoverable (notice-style) issues."""
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
    content_width: int | None = None,
) -> Panel:
    """Render a structured panel with recovery guidance when available."""
    wrap_w = error_panel_text_wrap_width(content_width)
    summary, detail = split_error_text(error_text)
    guidance = error_guidance(error_text)
    use_notice = (
        force_notice
        if force_notice is not None
        else use_recoverable_notice_style(error_text)
    )
    border = LIVE_PANEL_ACCENT_STYLE if use_notice else accent_style
    body_parts = _build_error_body(
        error_text=error_text,
        summary=summary,
        detail=detail,
        guidance=guidance,
        use_notice=use_notice,
        accent_style=accent_style,
        wrap_w=wrap_w,
    )
    panel_title = _build_panel_title(
        title=title,
        error_text=error_text,
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
    *, title: str, error_text: str, use_notice: bool, accent_style: str,
) -> Text:
    if use_notice:
        accent = LIVE_PANEL_ACCENT_STYLE
        panel_label = notice_panel_title(error_text)
        return Text(f'ℹ  {panel_label}', style=f'bold {accent}')
    return Text(title.strip() or 'Error', style=f'{accent_style} bold')


__all__ = [
    'build_error_panel',
    'build_llm_stream_fallback_panel',
    'build_recovery_text',
    'error_guidance',
    'notice_panel_title',
    'split_error_text',
    'use_recoverable_notice_style',
]
