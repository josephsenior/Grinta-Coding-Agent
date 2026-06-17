"""System and miscellaneous error guidance rules."""

from __future__ import annotations

from backend.cli.event_rendering.error_categories.matchers import _any, _has
from backend.cli.event_rendering.panels import ErrorGuidance, _GuidanceRule

SYSTEM_GUIDANCE_RULES: tuple[_GuidanceRule, ...] = (
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
            error_code='ERR-SYS-001',
        ),
    ),
    _GuidanceRule(
        _has('edit requires start_line and end_line'),
        ErrorGuidance(
            summary='A range edit is missing start_line or end_line.',
            steps=(
                'Use `replace_string` for exact text or `edit_symbol` for code symbols.',
                'Re-read the target context if you need a more specific anchor.',
            ),
            omit_summary_in_recovery=False,
            error_code='ERR-TE-001',
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
            error_code='ERR-SYS-002',
        ),
    ),
    _GuidanceRule(
        _any(
            'debugger start failed during',
            'dap adapter did not send initialized event',
            'initialize request timeout',
            'configurationdone timeout',
        ),
        ErrorGuidance(
            summary='Debugger startup stalled during adapter handshake.',
            steps=(
                'Retry ``debugger start`` once; startup may fail transiently on cold adapter boot.',
                'If it repeats, inspect the ``adapter_stderr`` block and fix adapter/runtime issues first.',
                'Use a shorter focused run after startup (status/stack) to confirm the session is responsive.',
            ),
            error_code='ERR-SYS-003',
        ),
    ),
    _GuidanceRule(
        _any(
            'render drain stalled',
            'flush only on interrupt',
            'output only after interrupt',
        ),
        ErrorGuidance(
            summary='The UI output pipeline fell behind and flushed late.',
            steps=(
                'Retry the same prompt once; if output remains delayed, restart the CLI session.',
                'Prefer shorter steps while troubleshooting so pending output drains continuously.',
                'If reproducible, capture the exact action that stalls so drain/wakeup handling can be tightened further.',
            ),
            error_code='ERR-SYS-004',
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
            error_code='ERR-SYS-006',
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
            error_code='ERR-SYS-007',
        ),
    ),
    _GuidanceRule(
        _any(
            '503',
            '502',
            '504',
            'service unavailable',
            'temporarily unavailable',
            'bad gateway',
            'gateway timeout',
            'overloaded',
            'over capacity',
            'capacity error',
        ),
        ErrorGuidance(
            summary='The provider endpoint is temporarily overloaded or unavailable.',
            steps=(
                'Wait briefly and retry — these errors are often transient.',
                'Check the provider status page for outages.',
                'If it persists, try another model in /settings or a different provider.',
            ),
            error_code='ERR-SYS-008',
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
            error_code='ERR-SYS-009',
        ),
    ),
    _GuidanceRule(
        _has('default shell session not initialized'),
        ErrorGuidance(
            summary='The runtime shell session is missing or was interrupted.',
            steps=(
                'Retry once to let Grinta recreate the default shell session.',
                'If this keeps happening after interrupts, restart the session/runtime and run the task again.',
                'If the issue persists, run one focused read/check step first to re-ground state before editing.',
            ),
            error_code='ERR-SYS-010',
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
            error_code='ERR-SYS-011',
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
            error_code='ERR-SYS-012',
        ),
    ),
    _GuidanceRule(
        _any('stuck_loop:', 'stuck loop detected'),
        ErrorGuidance(
            summary='The model repeated the same action without new output.',
            steps=(
                'It is being nudged to read fresh state or run a different step.',
                'You can wait, or add a short message to redirect it.',
            ),
            error_code='ERR-SYS-013',
        ),
    ),
)

__all__ = ['SYSTEM_GUIDANCE_RULES']
