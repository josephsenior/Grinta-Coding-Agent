"""Delegate-task action / observation summarisers."""

from __future__ import annotations

import re
from typing import Any

from rich.text import Text

from backend.cli._event_renderer.text_utils import truncate_activity_detail
from backend.cli.theme import (
    CLR_ERR_ICON,
    CLR_OK_ICON,
    CLR_WORKER_ACTION,
    CLR_WORKER_LABEL_DONE,
    CLR_WORKER_LABEL_FAILED,
    CLR_WORKER_TIMER,
)
from backend.cli.transcript import (
    format_activity_result_secondary,
    strip_tool_result_validation_annotations,
)
from backend.ledger.action import DelegateTaskAction
from backend.ledger.observation import DelegateTaskObservation


def _worker_elapsed_str(started_at: float | None, finished_at: float | None = None) -> str:
    """Format elapsed time as a short string like '12s' or '1m30s'."""
    if started_at is None:
        return ''
    import time
    end = finished_at if finished_at is not None else time.monotonic()
    elapsed = max(0, int(end - started_at))
    if elapsed < 60:
        return f'{elapsed}s'
    return f'{elapsed // 60}m{elapsed % 60:02d}s'


def _delegate_parallel_summary(
    action: DelegateTaskAction,
    parallel_tasks: list[dict[str, Any]],
) -> tuple[str, str | None]:
    count = len(parallel_tasks)
    detail = f'{count} parallel task' + ('s' if count != 1 else '')
    previews = [
        truncate_activity_detail(str(item.get('task_description') or ''), 36)
        for item in parallel_tasks
        if str(item.get('task_description') or '').strip()
    ]
    secondary_parts: list[str] = []
    if previews:
        preview = '; '.join(previews[:2])
        if len(previews) > 2:
            preview += f'; +{len(previews) - 2} more'
        secondary_parts.append(preview)
    if bool(getattr(action, 'run_in_background', False)):
        secondary_parts.append('background')
    return detail, ' · '.join(secondary_parts) or None


def summarize_delegate_action(
    action: DelegateTaskAction,
) -> tuple[str, str | None]:
    """Return a compact action label for single-worker and swarm delegations."""
    parallel_tasks = getattr(action, 'parallel_tasks', []) or []
    run_in_background = bool(getattr(action, 'run_in_background', False))

    if parallel_tasks:
        return _delegate_parallel_summary(action, parallel_tasks)

    detail = (
        truncate_activity_detail(getattr(action, 'task_description', '') or '', 80)
        or 'subtask'
    )
    secondary_parts: list[str] = []
    files = getattr(action, 'files', []) or []
    if files:
        secondary_parts.append(f'{len(files)} file' + ('s' if len(files) != 1 else ''))
    if run_in_background:
        secondary_parts.append('background')
    return detail, ' · '.join(secondary_parts) or None


_WORKER_STATUS_RE = re.compile(r'^\[(OK|FAILED)\]\s*(.+)$')


def _parse_worker_statuses(lines: list[str]) -> list[tuple[str, str]]:
    statuses: list[tuple[str, str]] = []
    for line in lines:
        match = _WORKER_STATUS_RE.match(line)
        if match:
            statuses.append((match.group(1), match.group(2)))
    return statuses


def _format_worker_result_line(
    label: str,
    status: str,
    action_count: int = 0,
    elapsed: str = '',
) -> Text:
    """Format a single worker result line with label, status, and stats."""
    line = Text()
    if status == 'OK':
        line.append('✓ ', style=CLR_OK_ICON)
        line.append(label or 'worker', style=CLR_WORKER_LABEL_DONE)
    else:
        line.append('✗ ', style=CLR_ERR_ICON)
        line.append(label or 'worker', style=CLR_WORKER_LABEL_FAILED)

    stats_parts: list[str] = []
    if elapsed:
        stats_parts.append(elapsed)
    if action_count > 0:
        stats_parts.append(f'{action_count} action{"s" if action_count != 1 else ""}')
    if stats_parts:
        line.append('  ', style=CLR_WORKER_TIMER)
        line.append(' · '.join(stats_parts), style=CLR_WORKER_ACTION)
    return line


def _worker_summary_lines(
    worker_statuses: list[tuple[str, str]],
    error: str,
    workers_data: dict[str, Any] | None = None,
    sorted_workers: list[tuple[str, dict[str, Any]]] | None = None,
) -> tuple[str, str, list[Text]]:
    total = len(worker_statuses)
    ok_count = sum(status == 'OK' for status, _label in worker_statuses)
    failed_count = total - ok_count

    if failed_count == 0:
        result_message = f'✓ all {total} worker{"s" if total != 1 else ""} completed'
        result_kind = 'ok'
    else:
        result_message = f'{ok_count}/{total} workers completed'
        result_kind = 'err'

    extra_lines: list[Text] = []
    if sorted_workers:
        # Use rich per-worker data when available
        for _wid, info in sorted_workers:
            label = info.get('label', _wid)
            w_status = 'OK' if info.get('status') == 'done' else 'FAILED'
            action_count = info.get('action_count', 0)
            elapsed = _worker_elapsed_str(
                info.get('started_at'),
                info.get('finished_at'),
            )
            extra_lines.append(_format_worker_result_line(
                label, w_status, action_count, elapsed,
            ))
    else:
        # Fallback to the old behavior when no worker data available
        for status, label in worker_statuses[:3]:
            extra_lines.append(
                format_activity_result_secondary(
                    truncate_activity_detail(label, 96),
                    kind='ok' if status == 'OK' else 'err',
                )
            )
        if total > 3:
            extra_lines.append(
                format_activity_result_secondary(
                    f'+{total - 3} more workers', kind='neutral'
                )
            )

    if failed_count and error:
        extra_lines.append(
            format_activity_result_secondary(
                truncate_activity_detail(error, 120),
                kind='err',
            )
        )
    return result_message, result_kind, extra_lines


def summarize_delegate_observation(
    obs: DelegateTaskObservation,
    workers_data: dict[str, Any] | None = None,
) -> tuple[str | None, str, list[Text]]:
    """Summarise delegated-worker results for compact in-card CLI rendering.

    *workers_data* is the optional ``_delegate_workers`` dict from the CLI
    renderer, used to produce richer per-worker result lines with elapsed
    times and action counts.
    """
    success = bool(getattr(obs, 'success', True))
    error = str(getattr(obs, 'error_message', '') or '').strip()
    raw_content = strip_tool_result_validation_annotations(
        str(getattr(obs, 'content', '') or '').strip()
    )
    content = raw_content.split('[SHARED BLACKBOARD SNAPSHOT]', 1)[0].strip()
    lines = [line.strip() for line in content.splitlines() if line.strip()]

    # Build sorted worker list if data available
    sorted_workers = None
    if workers_data:
        sorted_workers = sorted(
            workers_data.items(),
            key=lambda item: (item[1].get('order', 9999), item[1].get('label', '')),
        )

    worker_statuses = _parse_worker_statuses(lines)
    if worker_statuses:
        return _worker_summary_lines(
            worker_statuses, error,
            workers_data=workers_data,
            sorted_workers=sorted_workers,
        )

    if raw_content.startswith('Worker(s) started in background'):
        return truncate_activity_detail(raw_content, 140), 'neutral', []

    # Even without [OK]/[FAILED] markers, use worker data for richer results
    if sorted_workers:
        statuses: list[tuple[str, str]] = []
        for _wid, info in sorted_workers:
            w_status = 'OK' if info.get('status') == 'done' else 'FAILED'
            label = info.get('label', _wid)
            statuses.append((w_status, label))
        if statuses:
            return _worker_summary_lines(
                statuses, error,
                workers_data=workers_data,
                sorted_workers=sorted_workers,
            )

    if not success:
        return _delegation_failure_summary(error, lines)
    return _delegation_success_summary(raw_content, lines)


def _delegation_failure_summary(
    error: str,
    lines: list[str],
) -> tuple[str | None, str, list[Text]]:
    if error:
        return (
            f'delegation failed · {truncate_activity_detail(error, 120)}',
            'err',
            [],
        )
    if lines:
        return (
            f'delegation failed · {truncate_activity_detail(lines[0], 120)}',
            'err',
            [],
        )
    return 'delegation failed', 'err', []


def _delegation_success_summary(
    raw_content: str,
    lines: list[str],
) -> tuple[str | None, str, list[Text]]:
    if not lines:
        if raw_content:
            return truncate_activity_detail(raw_content, 140), 'ok', []
        return 'delegation completed', 'ok', []
    return truncate_activity_detail(lines[0], 140), 'ok', []


__all__ = ['summarize_delegate_action', 'summarize_delegate_observation']
