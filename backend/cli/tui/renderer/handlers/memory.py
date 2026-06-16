"""Memory tool event handlers (checkpoint, scratchpad, working memory)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.ledger.action.memory_tools import (
    CheckpointAction,
    MemoryPersistAction,
    MemoryRecallAction,
    ScratchpadNoteAction,
    ScratchpadRecallAction,
    WorkingMemoryAction,
)
from backend.ledger.observation.memory_tools import (
    CheckpointObservation,
    MemoryPersistObservation,
    MemoryRecallObservation,
    ScratchpadNoteObservation,
    ScratchpadRecallObservation,
    WorkingMemoryObservation,
)

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
    )


def _render_checkpoint_card(
    orch: 'RendererEventProcessorMixin',
    content: str,
    *,
    source_tool: str = '',
) -> None:
    from backend.cli.tui.renderer.mixins.thinking import ThinkingRenderIntent

    text = (content or '').strip()
    if not text:
        return
    intent = ThinkingRenderIntent(
        kind='checkpoint',
        text=text,
        detail=text,
        source_tool=source_tool,
    )
    card = orch._thinking_artifact_card(intent)
    if card is not None:
        orch._write_card(card)


def _handle_checkpoint_observation(
    orch: 'RendererEventProcessorMixin', event: CheckpointObservation
) -> None:
    _render_checkpoint_card(
        orch, event.content, source_tool='checkpoint'
    )


def _handle_working_memory_observation(
    orch: 'RendererEventProcessorMixin', event: WorkingMemoryObservation
) -> None:
    return


def _handle_memory_persist_observation(
    orch: 'RendererEventProcessorMixin', event: MemoryPersistObservation
) -> None:
    return


def _handle_memory_recall_observation(
    orch: 'RendererEventProcessorMixin', event: MemoryRecallObservation
) -> None:
    return


def _handle_scratchpad_note_observation(
    orch: 'RendererEventProcessorMixin', event: ScratchpadNoteObservation
) -> None:
    return


def _handle_scratchpad_recall_observation(
    orch: 'RendererEventProcessorMixin', event: ScratchpadRecallObservation
) -> None:
    return


def _handle_checkpoint_action(
    orch: 'RendererEventProcessorMixin', event: CheckpointAction
) -> None:
    detail = event.label or event.command or 'checkpoint'
    _render_checkpoint_card(orch, detail, source_tool='checkpoint')


def _handle_working_memory_action(
    orch: 'RendererEventProcessorMixin', event: WorkingMemoryAction
) -> None:
    return


def _handle_memory_persist_action(
    orch: 'RendererEventProcessorMixin', event: MemoryPersistAction
) -> None:
    return


def _handle_memory_recall_action(
    orch: 'RendererEventProcessorMixin', event: MemoryRecallAction
) -> None:
    return


def _handle_scratchpad_note_action(
    orch: 'RendererEventProcessorMixin', event: ScratchpadNoteAction
) -> None:
    return


def _handle_scratchpad_recall_action(
    orch: 'RendererEventProcessorMixin', event: ScratchpadRecallAction
) -> None:
    return
