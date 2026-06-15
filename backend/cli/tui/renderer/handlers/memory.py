"""Memory tool event handlers (checkpoint, scratchpad, working memory)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.cli.tui.renderer.mixins.thinking import ThinkingRenderIntent
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
        _AppRendererEventProcessorMixin,
    )


def _render_memory_tool_card(
    orch: '_AppRendererEventProcessorMixin',
    content: str,
    *,
    kind: str,
    source_tool: str = '',
) -> None:
    text = (content or '').strip()
    if not text:
        return
    intent = ThinkingRenderIntent(
        kind=kind,  # type: ignore[arg-type]
        text=text,
        detail=text,
        source_tool=source_tool,
    )
    card = orch._thinking_artifact_card(intent)
    if card is not None:
        orch._write_card(card)


def _handle_checkpoint_observation(
    orch: '_AppRendererEventProcessorMixin', event: CheckpointObservation
) -> None:
    _render_memory_tool_card(
        orch, event.content, kind='checkpoint', source_tool='checkpoint'
    )


def _handle_working_memory_observation(
    orch: '_AppRendererEventProcessorMixin', event: WorkingMemoryObservation
) -> None:
    _render_memory_tool_card(orch, event.content, kind='memory')


def _handle_memory_persist_observation(
    orch: '_AppRendererEventProcessorMixin', event: MemoryPersistObservation
) -> None:
    _render_memory_tool_card(orch, event.content, kind='memory')


def _handle_memory_recall_observation(
    orch: '_AppRendererEventProcessorMixin', event: MemoryRecallObservation
) -> None:
    _render_memory_tool_card(orch, event.content, kind='memory')


def _handle_scratchpad_note_observation(
    orch: '_AppRendererEventProcessorMixin', event: ScratchpadNoteObservation
) -> None:
    _render_memory_tool_card(orch, event.content, kind='memory')


def _handle_scratchpad_recall_observation(
    orch: '_AppRendererEventProcessorMixin', event: ScratchpadRecallObservation
) -> None:
    _render_memory_tool_card(orch, event.content, kind='memory')


def _handle_checkpoint_action(
    orch: '_AppRendererEventProcessorMixin', event: CheckpointAction
) -> None:
    detail = event.label or event.command or 'checkpoint'
    _render_memory_tool_card(orch, detail, kind='checkpoint', source_tool='checkpoint')


def _handle_working_memory_action(
    orch: '_AppRendererEventProcessorMixin', event: WorkingMemoryAction
) -> None:
    detail = f'{event.command} {event.section}'.strip()
    _render_memory_tool_card(orch, detail, kind='memory')


def _handle_memory_persist_action(
    orch: '_AppRendererEventProcessorMixin', event: MemoryPersistAction
) -> None:
    _render_memory_tool_card(orch, event.key or 'persist', kind='memory')


def _handle_memory_recall_action(
    orch: '_AppRendererEventProcessorMixin', event: MemoryRecallAction
) -> None:
    _render_memory_tool_card(orch, event.query or 'recall', kind='memory')


def _handle_scratchpad_note_action(
    orch: '_AppRendererEventProcessorMixin', event: ScratchpadNoteAction
) -> None:
    _render_memory_tool_card(orch, event.key or 'note', kind='memory')


def _handle_scratchpad_recall_action(
    orch: '_AppRendererEventProcessorMixin', event: ScratchpadRecallAction
) -> None:
    _render_memory_tool_card(orch, event.key or 'recall', kind='memory')
