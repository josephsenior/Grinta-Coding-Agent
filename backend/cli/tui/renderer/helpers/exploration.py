"""Pure exploration/orient event helpers (no orchestrator dependency)."""

from __future__ import annotations

from backend.ledger.action import (
    AnalyzeProjectStructureAction,
    FindSymbolsAction,
    GlobAction,
    GrepAction,
)
from backend.ledger.observation import (
    AnalyzeProjectStructureObservation,
    FindSymbolsObservation,
    GlobObservation,
    GrepObservation,
)


def exploration_meta_line(tokens: list[str]) -> list[str]:
    cleaned = [token for token in tokens if token]
    if not cleaned:
        return []
    return [' · '.join(cleaned)]


def grep_exploration_meta(event: GrepAction | GrepObservation) -> list[str]:
    tokens: list[str] = []
    mode = (getattr(event, 'output_mode', '') or '').strip()
    if mode:
        tokens.append(f'mode: {mode}')
    file_pattern = (getattr(event, 'file_pattern', '') or '').strip()
    if file_pattern:
        tokens.append(f'filter: {file_pattern}')
    head_limit = getattr(event, 'head_limit', None)
    if head_limit:
        tokens.append(f'limit: {head_limit}')
    offset = getattr(event, 'offset', 0) or 0
    if offset:
        tokens.append(f'offset: {offset}')
    if getattr(event, 'case_sensitive', False):
        tokens.append('case-sensitive')
    return exploration_meta_line(tokens)


def glob_exploration_meta(event: GlobAction | GlobObservation) -> list[str]:
    tokens: list[str] = []
    head_limit = getattr(event, 'head_limit', None)
    if head_limit:
        tokens.append(f'limit: {head_limit}')
    offset = getattr(event, 'offset', 0) or 0
    if offset:
        tokens.append(f'offset: {offset}')
    return exploration_meta_line(tokens)


def find_symbols_exploration_meta(
    event: FindSymbolsAction | FindSymbolsObservation,
) -> list[str]:
    tokens: list[str] = []
    symbol_kind = (getattr(event, 'symbol_kind', '') or '').strip()
    if symbol_kind:
        tokens.append(f'kind: {symbol_kind}')
    if getattr(event, 'include_private', False):
        tokens.append('include-private')
    return exploration_meta_line(tokens)


def analyze_exploration_meta(
    event: AnalyzeProjectStructureAction | AnalyzeProjectStructureObservation,
) -> list[str]:
    tokens: list[str] = []
    depth = getattr(event, 'depth', None)
    if depth is not None:
        tokens.append(f'depth: {depth}')
    direction = (getattr(event, 'direction', '') or '').strip()
    if direction:
        tokens.append(f'direction: {direction}')
    symbol = (getattr(event, 'symbol', '') or '').strip()
    if symbol:
        tokens.append(f'symbol: {symbol}')
    return exploration_meta_line(tokens)


def build_lsp_preview(content: str) -> str | None:
    if not content:
        return None
    truncated = content[:200] + ('...' if len(content) > 200 else '')
    return f'  {truncated}'


def search_file_list_from_paths(paths: list[str]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for path in paths:
        if path:
            counts[path] = counts.get(path, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]


def find_symbols_result_lines(
    event: FindSymbolsObservation,
) -> tuple[list[str], list[tuple[str, int]]]:
    result_lines: list[str] = []
    paths: list[str] = []
    for candidate in event.candidates:
        path = str(candidate.get('path') or '').strip()
        start_line = candidate.get('start_line')
        qualified_name = str(
            candidate.get('qualified_name') or candidate.get('name') or ''
        ).strip()
        if path and start_line:
            result_lines.append(f'{path}:{start_line}:{qualified_name}')
            paths.append(path)
        elif qualified_name:
            result_lines.append(qualified_name)
    return result_lines, search_file_list_from_paths(paths)



