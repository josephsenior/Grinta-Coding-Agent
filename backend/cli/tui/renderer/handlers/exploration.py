"""Exploration/orient tool event handlers (grep, glob, lsp, symbols, analyze)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.cli.orient_tools import (
    OrientLineModel,
    analyze_action_model,
    analyze_observation_model,
    find_symbols_action_model,
    find_symbols_observation_model,
    glob_action_model,
    glob_observation_model,
    grep_action_model,
    grep_observation_model,
    lsp_action_model,
    lsp_observation_model,
    read_symbols_action_model,
    read_symbols_observation_model,
)
from backend.ledger.action import (
    AnalyzeProjectStructureAction,
    FindSymbolsAction,
    GlobAction,
    GrepAction,
    LspQueryAction,
    ReadSymbolsAction,
)
from backend.ledger.observation import (
    AnalyzeProjectStructureObservation,
    FindSymbolsObservation,
    GlobObservation,
    GrepObservation,
    LspQueryObservation,
    ReadSymbolsObservation,
)

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
    )


def clear_pending_exploration_cards(orch: 'RendererEventProcessorMixin') -> None:
    """Drop in-flight orient/search cards when a tool resolves as ErrorObservation."""
    orch._pending_search_card = None
    orch._pending_search_tool = ''
    orch._pending_find_symbols_card = None
    orch._pending_read_symbols_card = None
    orch._pending_exploration_meta = None


def _update_or_write_lsp_card(
    orch: 'RendererEventProcessorMixin',
    card: Any,
    symbol: str,
    available: bool,
    preview: str | None,
) -> None:
    pending = orch._pending_lsp_card
    if isinstance(pending, OrientLineModel):
        return
    if pending is not None:
        status = 'ok' if available else 'err'
        orch._update_activity_card_outcome(
            pending,
            status=status,
            outcome=card.secondary or 'completed',
            extra_content=preview,
        )
        orch._pending_lsp_card = None
    else:
        orch._write_card(card)


def _handle_grep_action(orch: 'RendererEventProcessorMixin', event: GrepAction) -> None:
    model = grep_action_model(event)
    orch._pending_search_card = model
    orch._pending_search_tool = 'grep'
    orch._pending_exploration_meta = None


def _handle_glob_action(orch: 'RendererEventProcessorMixin', event: GlobAction) -> None:
    model = glob_action_model(event)
    orch._pending_search_card = model
    orch._pending_search_tool = 'glob'
    orch._pending_exploration_meta = None


def _handle_lsp_query_action(
    orch: 'RendererEventProcessorMixin', event: LspQueryAction
) -> None:
    model = lsp_action_model(event)
    orch._pending_lsp_card = model


def _handle_grep_observation(
    orch: 'RendererEventProcessorMixin', event: GrepObservation
) -> None:
    fallback = grep_observation_model(event)
    pending = orch._pending_search_card
    if orch._pending_search_tool == 'grep' and isinstance(pending, OrientLineModel):
        orch._write_orient_line(pending.with_result(fallback.result))
    else:
        orch._write_orient_line(fallback)
    orch._pending_search_card = None
    orch._pending_search_tool = ''
    orch._pending_exploration_meta = None


def _handle_glob_observation(
    orch: 'RendererEventProcessorMixin', event: GlobObservation
) -> None:
    fallback = glob_observation_model(event)
    pending = orch._pending_search_card
    if orch._pending_search_tool == 'glob' and isinstance(pending, OrientLineModel):
        orch._write_orient_line(pending.with_result(fallback.result))
    else:
        orch._write_orient_line(fallback)
    orch._pending_search_card = None
    orch._pending_search_tool = ''
    orch._pending_exploration_meta = None


def _handle_lsp_query_observation(
    orch: 'RendererEventProcessorMixin', event: LspQueryObservation
) -> None:
    pending = orch._pending_lsp_card
    pending_model = pending if isinstance(pending, OrientLineModel) else None
    orch._write_orient_line(lsp_observation_model(event, pending_model))
    orch._pending_lsp_card = None


def _handle_find_symbols_action(
    orch: 'RendererEventProcessorMixin', event: FindSymbolsAction
) -> None:
    model = find_symbols_action_model(event)
    orch._pending_find_symbols_card = model
    orch._pending_exploration_meta = None


def _handle_find_symbols_observation(
    orch: 'RendererEventProcessorMixin', event: FindSymbolsObservation
) -> None:
    fallback = find_symbols_observation_model(event)
    pending = orch._pending_find_symbols_card
    if isinstance(pending, OrientLineModel):
        orch._write_orient_line(pending.with_result(fallback.result))
    else:
        orch._write_orient_line(fallback)
    orch._pending_find_symbols_card = None
    orch._pending_exploration_meta = None


def _handle_read_symbols_action(
    orch: 'RendererEventProcessorMixin', event: ReadSymbolsAction
) -> None:
    model = read_symbols_action_model(event)
    orch._pending_read_symbols_card = model
    orch._pending_exploration_meta = None


def _handle_read_symbols_observation(
    orch: 'RendererEventProcessorMixin', event: ReadSymbolsObservation
) -> None:
    fallback = read_symbols_observation_model(event)
    pending = orch._pending_read_symbols_card
    if isinstance(pending, OrientLineModel):
        orch._write_orient_line(pending.with_result(fallback.result))
    else:
        orch._write_orient_line(fallback)
    orch._pending_read_symbols_card = None
    orch._pending_exploration_meta = None


def _handle_analyze_project_structure_action(
    orch: 'RendererEventProcessorMixin', event: AnalyzeProjectStructureAction
) -> None:
    model = analyze_action_model(event)
    orch._pending_analyze_project_structure_card = model
    orch._pending_exploration_meta = None


def _handle_analyze_project_structure_observation(
    orch: 'RendererEventProcessorMixin',
    event: AnalyzeProjectStructureObservation,
) -> None:
    content = (event.error or event.content or '').strip()
    del content
    fallback = analyze_observation_model(event)
    pending = orch._pending_analyze_project_structure_card
    if isinstance(pending, OrientLineModel):
        orch._write_orient_line(pending.with_result(fallback.result))
    else:
        orch._write_orient_line(fallback)
    orch._pending_analyze_project_structure_card = None
    orch._pending_exploration_meta = None
