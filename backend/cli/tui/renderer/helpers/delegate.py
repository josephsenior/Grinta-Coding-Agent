"""Pure delegate event helpers (no orchestrator dependency)."""

from __future__ import annotations

from backend.ledger.action import DelegateTaskAction
from backend.ledger.observation import DelegateTaskObservation


def resolve_delegate_task_and_worker(
    event: DelegateTaskAction,
) -> tuple[str, str]:
    task = getattr(event, 'task_description', '') or getattr(event, 'task', '') or ''
    worker = getattr(event, 'worker', '') or ''
    return task, worker


def build_delegate_preview(detail: str) -> str | None:
    if not detail:
        return None
    truncated = detail[:200] + ('...' if len(detail) > 200 else '')
    return f'  {truncated}'


def resolve_delegate_card_detail(
    event: DelegateTaskObservation,
) -> tuple[str, str]:
    content = (event.content or '').strip()
    error_message = (getattr(event, 'error_message', '') or '').strip()
    return content, error_message
