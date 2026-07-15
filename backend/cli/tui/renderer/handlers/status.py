"""Status strip, error/success, and retry observation handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.cli.event_rendering.error_panel import notice_panel_title
from backend.cli.tui.renderer.handlers.compaction import show_compaction_started_card
from backend.cli.tui.renderer.helpers.status import TRANSIENT_HUD_ONLY_CATEGORIES
from backend.ledger.observation import (
    ErrorObservation,
    StatusObservation,
    SuccessObservation,
)
from backend.ledger.observation.error import (
    ERROR_CATEGORY_AUTH,
    ERROR_CATEGORY_BAD_REQUEST,
    ERROR_CATEGORY_CONTENT_POLICY,
    ERROR_CATEGORY_CONTEXT_WINDOW,
    ERROR_CATEGORY_DAILY_QUOTA,
    ERROR_CATEGORY_MODEL_NOT_FOUND,
    ERROR_CATEGORY_RUNTIME_DISCONNECTED,
)

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
    )

_RETRY_STATUS_TYPES = frozenset(
    {
        'retry_pending',
        'retry_resuming',
        'llm_retry_pending',
        'llm_retry_resuming',
    }
)

_ACTION_REQUIRED_CATEGORIES = frozenset(
    {
        ERROR_CATEGORY_AUTH,
        ERROR_CATEGORY_BAD_REQUEST,
        ERROR_CATEGORY_CONTENT_POLICY,
        ERROR_CATEGORY_CONTEXT_WINDOW,
        ERROR_CATEGORY_DAILY_QUOTA,
        ERROR_CATEGORY_MODEL_NOT_FOUND,
        ERROR_CATEGORY_RUNTIME_DISCONNECTED,
    }
)

_ACTION_REQUIRED_TITLES = {
    ERROR_CATEGORY_AUTH: 'Authentication failed',
    ERROR_CATEGORY_BAD_REQUEST: 'Invalid request',
    ERROR_CATEGORY_CONTENT_POLICY: 'Content blocked',
    ERROR_CATEGORY_CONTEXT_WINDOW: 'Context window full',
    ERROR_CATEGORY_DAILY_QUOTA: 'Daily quota exhausted',
    ERROR_CATEGORY_MODEL_NOT_FOUND: 'Model unavailable',
    ERROR_CATEGORY_RUNTIME_DISCONNECTED: 'Runtime disconnected',
}


def _first_error_line(content: str) -> str:
    return content.split('\n', 1)[0].strip() or 'An unknown error occurred'


def _toast_signature(
    content: str,
    error_category: str | None,
    *,
    error_id: str | None = None,
) -> str:
    if error_id == 'CIRCUIT_BREAKER_WARNING':
        return error_id
    parts = [error_id or '', error_category or '', _first_error_line(content)]
    return '|'.join(parts)


def _should_emit_toast(tui: Any, signature: str) -> bool:
    last = getattr(tui, '_last_notify_ui_only_signature', None)
    if last == signature:
        return False
    setattr(tui, '_last_notify_ui_only_signature', signature)
    return True


def _notification_title(content: str, error_category: str | None) -> str:
    if error_category in _ACTION_REQUIRED_TITLES:
        return _ACTION_REQUIRED_TITLES[error_category]
    return notice_panel_title(content, error_category=error_category)


def _notification_message(content: str, error_category: str | None) -> str:
    title = _notification_title(content, error_category)
    first_line = _first_error_line(content)
    lower_line = first_line.lower()
    lower_title = title.lower()
    if lower_line.startswith(lower_title) or lower_title in lower_line:
        return first_line
    return f'{title}: {first_line}'


def notify_ui_only_error(
    tui: Any,
    content: str,
    error_category: str | None,
    *,
    error_id: str | None = None,
) -> None:
    """Toast + runtime strip for user-facing errors that must not hit the transcript."""
    # Transient infra failures (rate limit, timeout, network) are surfaced via
    # the HUD backoff/retry strip only — no toast popups.
    if error_category in TRANSIENT_HUD_ONLY_CATEGORIES:
        return

    signature = _toast_signature(content, error_category, error_id=error_id)
    if not _should_emit_toast(tui, signature):
        return
    message = _notification_message(content, error_category)
    severity = 'error' if error_category in _ACTION_REQUIRED_CATEGORIES else 'warning'
    if severity == 'error' and hasattr(tui, 'notify_error'):
        tui.notify_error(message)
    elif hasattr(tui, 'notify_warning'):
        tui.notify_warning(message)
    else:
        tui.notify(message, severity=severity, timeout=4.0)

    if error_category and error_category not in TRANSIENT_HUD_ONLY_CATEGORIES:
        tui.set_runtime_status(
            _notification_title(content, error_category),
            meta=_first_error_line(content),
            active=True,
        )


def _notify_ui_only_error(
    orch: 'RendererEventProcessorMixin',
    content: str,
    error_category: str | None,
    *,
    error_id: str | None = None,
) -> None:
    notify_ui_only_error(orch._tui, content, error_category, error_id=error_id)


def _notify_guard_warning_once(
    orch: 'RendererEventProcessorMixin',
    content: str,
    *,
    error_id: str,
) -> None:
    """Surface guard warnings as a single toast; keep transcript clean."""
    signature = _toast_signature(content, None, error_id=error_id)
    if not _should_emit_toast(orch._tui, signature):
        return
    first_line = _first_error_line(content)
    if hasattr(orch._tui, 'notify_warning'):
        orch._tui.notify_warning(first_line)
    else:
        orch._tui.notify(first_line, severity='warning', timeout=4.0)


def _handle_error_observation(
    orch: 'RendererEventProcessorMixin', event: ErrorObservation
) -> None:
    from backend.cli.tui.renderer.handlers.exploration import (
        clear_pending_exploration_cards,
    )
    from backend.cli.tui.renderer.handlers.memory import clear_pending_memory_lines

    orch._compaction_transcript_active = False
    clear_pending_exploration_cards(orch)
    clear_pending_memory_lines(orch)
    content = event.content or 'An unknown error occurred'
    if getattr(event, 'agent_only', False):
        return
    error_category = getattr(event, 'error_category', None)
    if error_category in TRANSIENT_HUD_ONLY_CATEGORIES:
        return
    error_id = str(getattr(event, 'error_id', '') or '')
    if error_id == 'CIRCUIT_BREAKER_WARNING':
        _notify_guard_warning_once(orch, content, error_id=error_id)
        return
    if getattr(event, 'notify_ui_only', False):
        _notify_ui_only_error(orch, content, error_category, error_id=error_id or None)
        return

    fail_card = getattr(orch, '_fail_tool_scan_card', None)
    if callable(fail_card) and fail_card(getattr(event, 'cause', None), content):
        return

    _show_dap_install_hint_if_needed(orch, event)

    add_panel = getattr(orch._tui, 'add_error_panel', None)
    if callable(add_panel):
        add_panel(content, error_category=getattr(event, 'error_category', None))
        return
    orch._tui.add_warning(content)


def _show_dap_install_hint_if_needed(
    orch: 'RendererEventProcessorMixin', event: ErrorObservation
) -> None:
    """Show a non-persistent toast with install instructions for a missing DAP adapter."""
    adapter = getattr(event, '_dap_adapter', '') or ''
    language = getattr(event, '_dap_language', '') or ''
    content = event.content or ''

    is_not_installed = (
        'is not installed' in content
        or 'No module named' in content
        or 'not found' in content.lower()
    )
    if not is_not_installed:
        return

    from backend.execution.dap._dap_adapters import _DAP_ADAPTER_RECIPES

    recipe = _DAP_ADAPTER_RECIPES.get(language) or _DAP_ADAPTER_RECIPES.get(adapter)
    if not recipe:
        return

    install_hint = recipe.get('install_hint', '')
    docs = recipe.get('docs', '')
    if not install_hint:
        return

    # Session-level dedup
    tui = getattr(orch, '_tui', None)
    if tui is None:
        return
    notified = getattr(tui, '_dap_notified_languages', None)
    if notified is None:
        return
    dedup_key = language or adapter
    if dedup_key in notified:
        return
    notified.add(dedup_key)

    hint = f'{adapter or language} debug adapter is not installed. Run: {install_hint}'
    if docs:
        hint += f'  ({docs})'

    tui.notify_warning(hint, timeout=6.0)


def _backoff_hud_label_active(hud: Any) -> bool:
    label = (
        getattr(getattr(hud, 'state', None), 'agent_state_label', '') or ''
    ).strip()
    return label.startswith(('Backoff', 'Retrying'))


def _restore_running_hud_after_backoff(orch: 'RendererEventProcessorMixin') -> None:
    """Drop stale backoff/retry HUD chrome once the agent is working again."""
    if not _backoff_hud_label_active(orch._hud):
        return

    from backend.core.enums import AgentState

    state = getattr(orch, '_current_state', None)
    if isinstance(state, str):
        try:
            state = AgentState(state)
        except ValueError:
            state = None
    if state != AgentState.RUNNING:
        return

    orch._clear_retry_strip('Idle')
    orch._hud.update_ledger('Healthy')
    orch._hud.update_agent_state('Running')
    orch._tui.set_agent_phase('running')
    orch._tui._render_hud_bar()


def _event_clears_backoff_hud(event: Any) -> bool:
    """Return True when *event* signals the agent resumed productive work."""
    from backend.core.enums import AgentState
    from backend.ledger.action import Action
    from backend.ledger.observation import AgentStateChangedObservation

    if isinstance(event, AgentStateChangedObservation):
        try:
            return AgentState(event.agent_state) == AgentState.RUNNING
        except (ValueError, TypeError):
            return False

    if isinstance(event, Action):
        return not bool(getattr(event, 'suppress_cli', False))

    return False


def maybe_restore_running_hud_after_backoff(
    orch: 'RendererEventProcessorMixin', event: Any
) -> None:
    if _event_clears_backoff_hud(event):
        _restore_running_hud_after_backoff(orch)


def _handle_success_observation(
    orch: 'RendererEventProcessorMixin', event: SuccessObservation
) -> None:
    orch._compaction_transcript_active = False
    orch._clear_retry_strip('Recovered')
    orch._clear_runtime_strip('Recovered')
    orch._tui.add_success(event.content or 'Done')


def _handle_status_retry(
    orch: 'RendererEventProcessorMixin',
    status_type: str,
    extras: dict,
) -> None:
    label, last_status, message = orch._format_retry_status_message(status_type, extras)
    orch._hud.update_ledger('Backoff')
    orch._hud.update_agent_state(label)
    orch._tui.set_agent_phase(label)
    orch._update_retry_strip(label, message)
    if status_type in ('retry_pending', 'llm_retry_pending'):
        delay_seconds = extras.get('delay_seconds')
        try:
            delay = float(delay_seconds) if delay_seconds is not None else 0.0
        except (TypeError, ValueError):
            delay = 0.0
        if delay > 0:
            arm = getattr(orch._tui, 'arm_retry_countdown', None)
            if callable(arm):
                arm(
                    attempt=max(1, int(extras.get('attempt') or 1)),
                    max_attempts=max(
                        1,
                        int(extras.get('max_attempts') or extras.get('attempt') or 1),
                    ),
                    delay_seconds=delay,
                    reason=str(extras.get('reason') or 'transient failure'),
                    source=str(extras.get('source') or ''),
                )
    elif status_type in ('retry_resuming', 'llm_retry_resuming'):
        clear = getattr(orch._tui, '_clear_retry_countdown', None)
        if callable(clear):
            clear()


def _handle_status_compaction(
    orch: 'RendererEventProcessorMixin',
) -> None:
    orch._clear_retry_strip('Idle')
    show_compaction_started_card(orch)


def _handle_status_notice(
    orch: 'RendererEventProcessorMixin',
    event: StatusObservation,
    status_type: str,
) -> None:
    msg = (event.content or '').strip()
    if not msg:
        return
    summary = (
        status_type.replace('_', ' ').strip().title()
        if status_type
        else 'Runtime notice'
    )
    orch._update_runtime_strip(summary, msg, active=False)


def _handle_status_observation(
    orch: 'RendererEventProcessorMixin', event: StatusObservation
) -> None:
    status_type = str(getattr(event, 'status_type', '') or '')
    extras = getattr(event, 'extras', None) or {}
    if status_type in _RETRY_STATUS_TYPES:
        _handle_status_retry(orch, status_type, extras)
        return
    if status_type == 'compaction':
        _handle_status_compaction(orch)
        return
    _handle_status_notice(orch, event, status_type)
