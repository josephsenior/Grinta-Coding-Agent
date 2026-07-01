"""Exploration/orient tool event handlers (grep, glob, lsp, symbols, analyze)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.cli.tool_display.orient_tools import (
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
)
from backend.ledger.action import (
    AnalyzeProjectStructureAction,
    FindSymbolsAction,
    GlobAction,
    GrepAction,
    LspQueryAction,
)
from backend.ledger.observation import (
    AnalyzeProjectStructureObservation,
    FindSymbolsObservation,
    GlobObservation,
    GrepObservation,
    LspQueryObservation,
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
    orch._pending_exploration_meta = None


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
    orch._pending_lsp_file = getattr(event, 'file', '') or ''


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

    if not getattr(event, 'available', True):
        _show_lsp_install_hint(orch)

    orch._pending_lsp_card = None
    orch._pending_lsp_file = ''


def _show_lsp_install_hint(orch: 'RendererEventProcessorMixin') -> None:
    """Show a non-persistent toast with install instructions for a missing LSP server."""
    from pathlib import Path as _Path

    from backend.utils.lsp.lsp_project_routing import resolve_language_key
    from backend.utils.runtime_detect import CANONICAL_LSP_SERVERS

    file_path = getattr(orch, '_pending_lsp_file', '') or ''
    if not file_path:
        return

    suffix = _Path(file_path).suffix.lower()
    if not suffix:
        return

    try:
        from backend.utils.lsp.lsp_project_routing import find_project_root

        root = find_project_root(_Path(file_path))
        lang_key = resolve_language_key(suffix, root)
    except Exception:
        lang_key = None

    if not lang_key:
        return

    # Session-level dedup: don't notify twice for the same language
    tui = getattr(orch, '_tui', None)
    if tui is None:
        return
    notified = getattr(tui, '_lsp_notified_languages', None)
    if notified is None:
        return
    if lang_key in notified:
        return
    notified.add(lang_key)

    spec = CANONICAL_LSP_SERVERS.get(lang_key)
    if spec is None or not spec.install_hint:
        return

    hint = f'{spec.name} is not installed. Run: {spec.install_hint}'
    if spec.docs:
        hint += f'  ({spec.docs})'

    tui.notify_warning(hint, timeout=6.0)


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
