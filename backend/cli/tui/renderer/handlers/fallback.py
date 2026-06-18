"""Fallback / unmapped event handlers for the TUI renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text

from backend.cli.theme import NAVY_TEXT_MUTED, NAVY_TEXT_PRIMARY
from backend.cli.tool_display.orient_tools import OrientLineModel
from backend.ledger.action import StreamingChunkAction
from backend.ledger.observation import (
    AgentStateChangedObservation,
    FileDownloadObservation,
    ServerReadyObservation,
    UserRejectObservation,
)

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
    )


def _handle_noop_event(orch: 'RendererEventProcessorMixin', event: Any) -> None:
    del orch, event


def _handle_legacy_meta_cognition_dispatch(
    orch: 'RendererEventProcessorMixin', event: Any
) -> None:
    """Legacy clarify/confirm/proposal actions; superseded by ask_user."""
    del orch, event


def _handle_streaming_chunk_dispatch(
    orch: 'RendererEventProcessorMixin', event: StreamingChunkAction
) -> None:
    orch._handle_streaming_chunk(event)


def _handle_state_change_dispatch(
    orch: 'RendererEventProcessorMixin', event: AgentStateChangedObservation
) -> None:
    orch._handle_state_change(event)


def _handle_user_reject_dispatch(
    orch: 'RendererEventProcessorMixin', event: UserRejectObservation
) -> None:
    model = OrientLineModel(
        tool='system',
        icon='✗',
        verb='Rejected',
        target='Action rejected by user',
        result='',
    )
    orch._write_orient_line(model)


def _handle_server_ready_dispatch(
    orch: 'RendererEventProcessorMixin', event: ServerReadyObservation
) -> None:
    url = getattr(event, 'url', '')
    port = getattr(event, 'port', '')
    label = url or f'port {port}'
    model = OrientLineModel(
        tool='server',
        icon='✓',
        verb='Ready',
        target=f'Server accepting connections · {label}',
        result='',
    )
    orch._write_orient_line(model)


def _handle_file_download_dispatch(
    orch: 'RendererEventProcessorMixin', event: FileDownloadObservation
) -> None:
    url = getattr(event, 'url', '') or ''
    orch._tui._write_log(
        Text(f'  [#91abec]Downloaded[/] {url}', style=NAVY_TEXT_PRIMARY)
    )


def _handle_unknown_event(orch: 'RendererEventProcessorMixin', event: Any) -> None:
    name = type(event).__name__
    orch._tui._write_log(Text(f'  [{name}]', style=NAVY_TEXT_MUTED))
