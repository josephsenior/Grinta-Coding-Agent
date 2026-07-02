"""Render ranked repo-map text for prompt injection."""

from __future__ import annotations

from typing import Any

from backend.context.symbol_index.rank import rank_files_for_map
from backend.context.symbol_index.store import (
    SymbolIndexStore,
    get_symbol_index_store,
    repo_map_enabled,
)
from backend.inference.llm.utils import get_token_count


def _format_symbol_line(symbol: Any) -> str:
    kind = getattr(symbol, 'kind', '') or ''
    name = getattr(symbol, 'name', '') or ''
    preview = (getattr(symbol, 'signature_preview', '') or '').strip()
    if preview:
        first_line = preview.splitlines()[0].strip()
        if first_line:
            return f'      {first_line}'
    if kind == 'class':
        return f'      class {name}'
    return f'      def {name}'


def render_repo_map(
    store: SymbolIndexStore,
    *,
    task: str,
    map_tokens: int,
    model: str | None = None,
) -> str:
    ranked_paths = rank_files_for_map(store, task=task)
    header = [
        '<REPO_MAP>',
        'Preloaded ranked repository map (refreshed after index changes).',
        'Use analyze_project_structure command=tree only to drill into a subpath.',
    ]
    lines = list(header)

    low = 0
    high = len(ranked_paths)
    best_lines = list(header)
    best_count = 0

    while low <= high:
        mid = (low + high) // 2
        candidate_lines = list(header)
        for path in ranked_paths[:mid]:
            candidate_lines.append(f'  {path}')
            symbols = store.symbols_for_file(path)
            public = [
                symbol
                for symbol in symbols
                if not symbol.name.startswith('_') or symbol.kind == 'method'
            ]
            for symbol in public[:4]:
                candidate_lines.append(_format_symbol_line(symbol))
        body = '\n'.join(candidate_lines) + '\n</REPO_MAP>'
        tokens = get_token_count(body, model=model)
        if tokens <= map_tokens:
            best_lines = candidate_lines
            best_count = mid
            low = mid + 1
        else:
            high = mid - 1

    lines = best_lines
    lines.append('</REPO_MAP>')
    return '\n'.join(lines)


def build_repo_map_block(
    *,
    task: str,
    config: Any,
    mode: str,
) -> str:
    if not repo_map_enabled(config):
        return ''
    if mode.strip().lower() == 'chat':
        return ''

    from backend.context.coding_preflight import _looks_like_coding_task

    if not _looks_like_coding_task(task):
        return ''

    store = get_symbol_index_store()
    if store is None:
        return ''

    if not store.index_dirty and store.get_cached_map():
        return store.get_cached_map() or ''

    map_tokens = int(getattr(config, 'map_tokens', 1536) or 1536)
    model = None
    llm_config = getattr(config, 'llm_config', None)
    if llm_config is not None:
        model = getattr(llm_config, 'model', None)

    try:
        rendered = render_repo_map(
            store,
            task=task,
            map_tokens=max(256, map_tokens),
            model=model,
        )
        store.set_cached_map(rendered)
        return rendered
    except Exception:
        store.mark_dirty()
        return store.get_cached_map() or ''
