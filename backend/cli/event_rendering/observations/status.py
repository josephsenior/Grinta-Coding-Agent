"""Observation renderers — status domain."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.cli._typing import ObservationRenderersHost

    _ObservationRenderersBase = ObservationRenderersHost
else:
    _ObservationRenderersBase = object


from backend.cli._typing import ObservationRenderersHost
from backend.cli.display.transcript import (
    format_activity_result_secondary,
)
from backend.cli.event_rendering.error_panel import (
    build_llm_stream_fallback_panel as _build_llm_stream_fallback_panel,
)
from backend.ledger.observation import (
    StatusObservation,
)

logger = logging.getLogger(__name__)


class _ObsStatusMixin(_ObservationRenderersBase):
    def _render_status_observation(self, obs: StatusObservation) -> None:
        status_type = str(getattr(obs, 'status_type', '') or '')
        self._maybe_update_mcp_status(status_type, obs)
        if self._try_early_return_for_status(obs, status_type):
            return
        self._render_status_content(
            obs,
            force_visible_status=False,
            retry_signature=None,
        )

    def _maybe_update_mcp_status(
        self, status_type: str, obs: StatusObservation
    ) -> None:
        if status_type not in ('mcp_ready', 'mcp_connected'):
            return
        extras = getattr(obs, 'extras', None) or {}
        mcp_n = int(extras.get('connected_client_count') or 0)
        self._hud.update_mcp_servers(mcp_n)

    def _try_early_return_for_status(
        self, obs: StatusObservation, status_type: str
    ) -> bool:
        if status_type == 'delegate_progress':
            return self._handle_delegate_progress_status(obs)
        if status_type in (
            'retry_pending',
            'retry_resuming',
            'llm_retry_pending',
            'llm_retry_resuming',
        ):
            return self._handle_retry_status_with_dedup(obs, status_type)
        setattr(self, '_last_retry_status_signature', None)
        return False

    def _handle_retry_status_with_dedup(
        self, obs: StatusObservation, status_type: str
    ) -> bool:
        self._handle_retry_status(obs, status_type=status_type)
        extras = getattr(obs, 'extras', None) or {}
        retry_sig = (
            status_type,
            str(extras.get('attempt') or ''),
            str(extras.get('max_attempts') or ''),
            str(extras.get('reason') or ''),
            str(extras.get('delay_seconds') or ''),
        )
        if getattr(self, '_last_retry_status_signature', None) == retry_sig:
            return True
        setattr(self, '_last_retry_status_signature', retry_sig)
        return True

    def _handle_delegate_progress_status(self, obs: StatusObservation) -> bool:
        """Update the delegate panel; return True if the obs is fully consumed."""
        extras = getattr(obs, 'extras', None) or {}
        if self._delegate_batch_mismatch(extras.get('batch_id')):
            return True
        worker_id = str(extras.get('worker_id') or '').strip()
        if not worker_id:
            return False
        previous = self._delegate_workers.get(worker_id, {})
        self._delegate_workers[worker_id] = self._delegate_worker_record(
            obs,
            extras,
            worker_id,
            previous=previous,
        )
        self._set_delegate_panel()
        return True

    @staticmethod
    def _extract_order(extras: Any) -> int:
        order = extras.get('order', 9999)
        return order if isinstance(order, int) else 9999

    @staticmethod
    def _extract_detail(obs: StatusObservation, extras: Any) -> str:
        return str(extras.get('detail') or getattr(obs, 'content', '') or '')

    @staticmethod
    def _compute_worker_timing(
        status: str,
        previous: dict[str, Any] | None,
        now: float,
    ) -> tuple[float, float | None]:
        prev = previous or {}
        started_at = prev.get('started_at', now)
        finished_at = prev.get('finished_at')
        if status in ('done', 'failed') and finished_at is None:
            finished_at = now
        return started_at, finished_at

    @staticmethod
    def _compute_worker_action_tracking(
        status: str,
        detail: str,
        previous: dict[str, Any] | None,
    ) -> tuple[str, int]:
        prev = previous or {}
        last_action = prev.get('last_action', '')
        if status == 'running' and detail:
            last_action = detail
        action_count = prev.get('action_count', 0)
        if status == 'running' and detail and detail != prev.get('last_action', ''):
            action_count += 1
        return last_action, action_count

    @staticmethod
    def _delegate_worker_record(
        obs: StatusObservation,
        extras: Any,
        worker_id: str,
        previous: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        order = _ObsStatusMixin._extract_order(extras)
        status = str(extras.get('worker_status') or 'running')
        now = time.monotonic()
        started_at, finished_at = _ObsStatusMixin._compute_worker_timing(
            status,
            previous,
            now,
        )
        detail = _ObsStatusMixin._extract_detail(obs, extras)
        last_action, action_count = _ObsStatusMixin._compute_worker_action_tracking(
            status,
            detail,
            previous,
        )
        return {
            'label': str(extras.get('worker_label') or worker_id),
            'status': status,
            'task': str(extras.get('task_description') or 'subtask'),
            'detail': detail,
            'order': order,
            'started_at': started_at,
            'finished_at': finished_at,
            'last_action': last_action,
            'action_count': action_count,
        }

    def _delegate_batch_mismatch(self, batch_id: Any) -> bool:
        return (
            batch_id is not None
            and self._delegate_batch_id is not None
            and batch_id != self._delegate_batch_id
        )

    def _handle_retry_status(
        self,
        obs: StatusObservation,
        *,
        status_type: str,
    ) -> None:
        extras = getattr(obs, 'extras', None) or {}
        attempt = self._coerce_positive_int(extras.get('attempt'), default=1)
        max_attempts = self._coerce_positive_int(
            extras.get('max_attempts'),
            default=attempt,
            floor=attempt,
        )
        self._hud.update_ledger('Backoff')
        if status_type in ('retry_pending', 'llm_retry_pending'):
            delay_seconds = extras.get('delay_seconds')
            try:
                delay = float(delay_seconds) if delay_seconds else 10.0
            except (TypeError, ValueError):
                delay = 10.0
            delay_str = f'{int(delay)}s' if delay >= 1 else '<1s'
            self._hud.update_agent_state(
                f'Backoff {attempt}/{max_attempts} (retrying in {delay_str})'
            )
        else:
            self._hud.update_agent_state(f'Retrying {attempt}/{max_attempts}')

    @staticmethod
    def _coerce_positive_int(value: Any, *, default: int, floor: int = 1) -> int:
        try:
            coerced = int(value or default)
        except (TypeError, ValueError):
            coerced = default
        return max(floor, coerced)

    def _render_status_content(
        self,
        obs: StatusObservation,
        *,
        force_visible_status: bool,
        retry_signature: tuple[str, str] | None = None,
    ) -> None:
        content = getattr(obs, 'content', '')
        if not content:
            return
        lower_c = content.lower()
        if 'stream timed out' in lower_c or 'retrying without streaming' in lower_c:
            self._stream_fallback_count += 1
            logger.warning(
                'stream_fallback_retry: count=%d content=%r',
                self._stream_fallback_count,
                content[:120],
            )
            self._append_history(_build_llm_stream_fallback_panel())
            return
        if self._pending_activity_card is not None and not force_visible_status:
            return
        if retry_signature is not None:
            last_retry_signature = getattr(self, '_last_retry_status_signature', None)
            if last_retry_signature == retry_signature:
                return
            setattr(self, '_last_retry_status_signature', retry_signature)
        self._flush_pending_tool_cards()
        self._append_history(
            format_activity_result_secondary(
                f'status · {content}',
                kind='neutral',
            )
        )
