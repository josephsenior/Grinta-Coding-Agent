"""Observation renderers — file domain."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from backend.cli._typing import ObservationRenderersHost

    _ObservationRenderersBase = ObservationRenderersHost
else:
    _ObservationRenderersBase = object

from rich.padding import Padding

from backend.cli._typing import ObservationRenderersHost
from backend.cli.layout_tokens import ACTIVITY_BLOCK_BOTTOM_PAD
from backend.cli.orient_tools import (
    file_read_observation_model,
)
from backend.ledger.observation import (
    FileEditObservation,
    FileReadObservation,
)

logger = logging.getLogger(__name__)


class _ObsFileMixin(_ObservationRenderersBase):
    def _render_file_edit_observation(self, obs: FileEditObservation) -> None:
        self._stop_reasoning()
        from backend.cli.display.diff_renderer import DiffPanel
        from backend.cli.display.transcript import strip_indentation_warnings

        # Strip agent-facing indentation warnings from user-visible content
        if hasattr(obs, 'content') and obs.content:
            obs.content = strip_indentation_warnings(obs.content)

        path = getattr(obs, 'path', '')
        pending = cast(Any, self._take_pending_activity_card('file_edit'))
        self._emit_activity_turn_header()
        self._print_or_buffer(
            Padding(
                DiffPanel(
                    obs,
                    verb=pending.verb if pending else None,
                    detail=pending.detail if pending else path,
                    secondary=pending.secondary if pending else None,
                    title=pending.title if pending else None,
                    badge_label=pending.badge_label if pending else 'file_edit',
                ),
                pad=ACTIVITY_BLOCK_BOTTOM_PAD,
            )
        )

    def _render_file_read_observation(self, obs: FileReadObservation) -> None:
        self._stop_reasoning()
        pending = getattr(self, '_pending_orient_line', None)
        if pending is not None and getattr(pending, 'tool', '') == 'read_file':
            self._pending_orient_line = None
            self._append_orient_line(pending)
            return
        self._append_orient_line(file_read_observation_model(obs))

    @staticmethod
    def _file_read_result_message(content: str, n_lines: int) -> str:
        return ''
