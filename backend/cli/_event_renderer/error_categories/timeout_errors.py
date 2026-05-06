"""Timeout error guidance rules."""

from __future__ import annotations

from backend.cli._event_renderer.error_categories._matchers import _and, _any, _has
from backend.cli._event_renderer.panels import ErrorGuidance, _GuidanceRule

TIMEOUT_GUIDANCE_RULES: tuple[_GuidanceRule, ...] = (
    _GuidanceRule(
        _has('pending action timed out'),
        ErrorGuidance(
            summary='A tool action ran longer than the pending-action guard window.',
            steps=(
                'The command may still be running. Verify current process/output state before retrying.',
                'For setup/install tasks, run shorter sequential commands instead of one long chained command.',
                'Increase pending_action_timeout in settings.json if your environment is consistently slow.',
            ),
            error_code='ERR-TIMEOUT-001',
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
            error_code='ERR-TIMEOUT-002',
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
            error_code='ERR-TIMEOUT-003',
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
                'watch for the cyan "Still working" note in the transcript.',
            ),
            error_code='ERR-TIMEOUT-004',
        ),
    ),
)

__all__ = ['TIMEOUT_GUIDANCE_RULES']
