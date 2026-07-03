"""Memory tool event handlers (checkpoint, scratchpad, working memory)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.cli.tool_display.orient_tools import (
    OrientLineModel,
    checkpoint_action_model,
    checkpoint_observation_model,
    checkpoint_result,
    memory_persist_action_model,
    memory_persist_observation_model,
    memory_recall_action_model,
    memory_recall_observation_model,
)
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


def clear_pending_memory_lines(orch: 'RendererEventProcessorMixin') -> None:
    """Drop in-flight memory orient rows when a tool resolves as ErrorObservation."""
    orch._pending_memory_recall_line = None
    orch._pending_memory_persist_line = None
    orch._pending_acceptance_criteria_card = None


def _handle_checkpoint_observation(
    orch: 'RendererEventProcessorMixin', event: CheckpointObservation
) -> None:
    pending = getattr(orch, '_pending_checkpoint_line', None)
    if isinstance(pending, OrientLineModel):
        orch._write_orient_line(
            pending.with_result(checkpoint_result(event, target=pending.target))
        )
    else:
        orch._write_orient_line(checkpoint_observation_model(event))
    orch._pending_checkpoint_line = None


def _handle_working_memory_observation(
    orch: 'RendererEventProcessorMixin', event: WorkingMemoryObservation
) -> None:
    return


def _handle_memory_persist_observation(
    orch: 'RendererEventProcessorMixin', event: MemoryPersistObservation
) -> None:
    pending = getattr(orch, '_pending_memory_persist_line', None)
    if isinstance(pending, OrientLineModel):
        orch._write_orient_line(memory_persist_observation_model(event, pending))
    else:
        orch._write_orient_line(memory_persist_observation_model(event))
    orch._pending_memory_persist_line = None


def _handle_memory_recall_observation(
    orch: 'RendererEventProcessorMixin', event: MemoryRecallObservation
) -> None:
    pending = getattr(orch, '_pending_memory_recall_line', None)
    if isinstance(pending, OrientLineModel):
        orch._write_orient_line(memory_recall_observation_model(event, pending))
    else:
        orch._write_orient_line(memory_recall_observation_model(event))
    orch._pending_memory_recall_line = None


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
    orch._pending_checkpoint_line = checkpoint_action_model(event)


def _handle_working_memory_action(
    orch: 'RendererEventProcessorMixin', event: WorkingMemoryAction
) -> None:
    return


def _handle_memory_persist_action(
    orch: 'RendererEventProcessorMixin', event: MemoryPersistAction
) -> None:
    orch._pending_memory_persist_line = memory_persist_action_model(event)


def _handle_memory_recall_action(
    orch: 'RendererEventProcessorMixin', event: MemoryRecallAction
) -> None:
    orch._pending_memory_recall_line = memory_recall_action_model(event)


def _handle_scratchpad_note_action(
    orch: 'RendererEventProcessorMixin', event: ScratchpadNoteAction
) -> None:
    return


def _handle_scratchpad_recall_action(
    orch: 'RendererEventProcessorMixin', event: ScratchpadRecallAction
) -> None:
    return
