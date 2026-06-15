"""Observation renderers — misc domain."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from backend.cli._typing import ObservationRenderersHost

    _ObservationRenderersBase = ObservationRenderersHost
else:
    _ObservationRenderersBase = object


from backend.cli._typing import ObservationRenderersHost
from backend.cli.display.transcript import (
    format_activity_result_secondary,
    strip_tool_result_validation_annotations,
)
from backend.cli.event_rendering.delegate import (
    summarize_delegate_observation as _summarize_delegate_observation,
)
from backend.cli.event_rendering.text_utils import (
    sanitize_visible_transcript_text as _sanitize_visible_transcript_text,
)
from backend.ledger.observation import (
    AgentCondensationObservation,
    DelegateTaskObservation,
    FileDownloadObservation,
    RecallFailureObservation,
    ServerReadyObservation,
    SuccessObservation,
    TaskTrackingObservation,
)

logger = logging.getLogger(__name__)


class _ObsMiscMixin(_ObservationRenderersBase):
    def _render_server_ready_observation(self, obs: ServerReadyObservation) -> None:
        self._flush_pending_tool_cards()
        url = getattr(obs, 'url', '')
        port = getattr(obs, 'port', '')
        label = url or f'port {port}'
        self._append_history(
            format_activity_result_secondary(
                f'server ready · {label}',
                kind='ok',
            ),
        )

    def _render_success_observation(self, obs: SuccessObservation) -> None:
        self._flush_pending_tool_cards()
        content = getattr(obs, 'content', '')
        if content:
            self._append_history(
                format_activity_result_secondary(content, kind='ok'),
            )

    def _render_recall_failure_observation(
        self,
        obs: RecallFailureObservation,
    ) -> None:
        self._flush_pending_tool_cards()
        error_msg = getattr(obs, 'error_message', '')
        recall_type = getattr(obs, 'recall_type', None)
        label = str(recall_type.value) if recall_type else 'recall'
        if error_msg:
            self._append_history(
                format_activity_result_secondary(
                    f'{label} failed · {error_msg}',
                    kind='err',
                )
            )

    def _render_file_download_observation(
        self,
        obs: FileDownloadObservation,
    ) -> None:
        self._flush_pending_tool_cards()
        path = getattr(obs, 'file_path', '')
        self._append_history(
            format_activity_result_secondary(
                f'downloaded · {path}',
                kind='neutral',
            ),
        )

    def _render_delegate_task_observation(
        self,
        obs: DelegateTaskObservation,
    ) -> None:
        self._stop_reasoning()
        pending = cast(Any, self._take_pending_activity_card('delegate'))
        workers_data = getattr(self, '_delegate_workers', {}) or {}
        result_message, result_kind, extra_lines = _summarize_delegate_observation(
            obs,
            workers_data=workers_data,
        )
        if pending is not None:
            self._render_pending_activity_card(
                pending,
                result_message=result_message,
                result_kind=result_kind,
                extra_lines=extra_lines,
            )
            return
        if result_message is not None:
            self._append_history(
                format_activity_result_secondary(result_message, kind=result_kind),
            )
        for line in extra_lines:
            self._append_history(line)

    def _render_task_tracking_observation(
        self,
        obs: TaskTrackingObservation,
    ) -> None:
        task_list = getattr(obs, 'task_list', None)
        cmd = getattr(obs, 'command', '')
        if task_list is not None and cmd == 'update':
            self._set_task_panel(task_list)
        content = _sanitize_visible_transcript_text(
            strip_tool_result_validation_annotations(
                (getattr(obs, 'content', None) or '').strip()
            )
        )
        body = '' if (task_list is not None and cmd == 'update') else content
        if body:
            for line in body.splitlines():
                self._append_history(
                    format_activity_result_secondary(line, kind='neutral')
                )
        self.refresh()

    def _render_agent_condensation_observation(
        self,
        obs: AgentCondensationObservation,
    ) -> None:
        del obs
