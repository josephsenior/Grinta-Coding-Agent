"""Observation renderers — exploration domain."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.cli._typing import ObservationRenderersHost

    _ObservationRenderersBase = ObservationRenderersHost
else:
    _ObservationRenderersBase = object


from backend.cli._typing import ObservationRenderersHost
from backend.cli.tool_display.orient_tools import (
    OrientLineModel,
    analyze_observation_model,
    find_symbols_observation_model,
    glob_observation_model,
    grep_observation_model,
    lsp_observation_model,
)
from backend.ledger.observation import (
    AnalyzeProjectStructureObservation,
    FindSymbolsObservation,
    GlobObservation,
    GrepObservation,
    LspQueryObservation,
)

logger = logging.getLogger(__name__)


def _lsp_payload(content: str) -> Any:
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _lsp_counted_result(data: dict[str, Any]) -> tuple[bool, str | None]:
    for key in ('definitions', 'references'):
        items = data.get(key)
        if not isinstance(items, list):
            continue
        if not items:
            return True, None
        noun = key.rstrip('s')
        return True, f'{len(items)} {noun}{"s" if len(items) != 1 else ""}'
    return False, None


def _lsp_diagnostics_result(diagnostics: list[Any]) -> str:
    count = len(diagnostics)
    if count == 0:
        return 'clean'
    return f'{count} issue{"s" if count != 1 else ""}'


def _lsp_text_result(content: str) -> str | None:
    lines = [line for line in content.split('\n') if line.strip()]
    if not lines:
        return None
    return f'{len(lines)} results'


def _lsp_dict_result(data: dict[str, Any], content: str) -> str | None:
    handled, result = _lsp_counted_result(data)
    if handled:
        return result
    if 'hover' in data or 'contents' in data:
        return 'completed'
    symbols = data.get('symbols') or data.get('symbol_list')
    if isinstance(symbols, list):
        return f'{len(symbols)} symbols'
    diagnostics = data.get('diagnostics') or data.get('issues')
    if isinstance(diagnostics, list):
        return _lsp_diagnostics_result(diagnostics)
    actions = data.get('actions')
    if isinstance(actions, list):
        return f'{len(actions)} actions'
    return _lsp_text_result(content)


def _analyze_lines(content: str) -> list[str]:
    return [line.strip() for line in content.split('\n') if line.strip()]


def _analyze_result_kind(body_lower: str) -> str:
    if 'callers' in body_lower or 'caller of' in body_lower:
        return 'callers'
    if (
        'dependency' in body_lower
        or 'depend on' in body_lower
        or 'import' in body_lower
    ):
        return 'dependencies'
    if 'symbol' in body_lower:
        return 'symbols'
    return 'completed'


def _is_caller_line(line: str) -> bool:
    return (
        '::' in line or ' -> ' in line or ('  ' in line and '(' in line and ')' in line)
    )


def _analyze_callers_result(lines: list[str]) -> str:
    caller_lines = [line for line in lines if _is_caller_line(line)]
    return f'{len(caller_lines)} callers' if caller_lines else 'completed'


def _is_dependency_line(line: str) -> bool:
    return '<-' in line or '->' in line or 'import' in line.lower()


def _analyze_dependencies_result(lines: list[str]) -> str:
    dep_count = sum(1 for line in lines if _is_dependency_line(line))
    return f'{dep_count} deps' if dep_count else 'completed'


def _is_symbol_line(line: str) -> bool:
    return not line.startswith('#') and not line.startswith('//')


def _analyze_symbols_result(lines: list[str]) -> str:
    symbol_lines = [line for line in lines if _is_symbol_line(line)]
    return f'{len(symbol_lines)} symbols' if symbol_lines else 'completed'


class _ObsExplorationMixin(_ObservationRenderersBase):
    def _render_lsp_query_observation(self, obs: LspQueryObservation) -> None:
        self._stop_reasoning()
        pending = getattr(self, '_pending_orient_line', None)
        pending_model = pending if isinstance(pending, OrientLineModel) else None
        if pending_model is not None and pending_model.tool == 'lsp':
            self._pending_orient_line = None
        else:
            pending_model = None
        self._append_orient_line(lsp_observation_model(obs, pending_model))

    @staticmethod
    def _orient_lsp_result(*, available: bool, content: str) -> str | None:
        if not available:
            return 'unavailable'
        if not content.strip():
            return None
        data = _lsp_payload(content)
        if isinstance(data, dict):
            return _lsp_dict_result(data, content)
        if isinstance(data, list):
            return f'{len(data)} results'
        return _lsp_text_result(content)

    def _render_grep_observation(self, obs: GrepObservation) -> None:
        self._stop_reasoning()
        self._complete_or_append_orient('grep', grep_observation_model(obs))

    @staticmethod
    def _orient_grep_result(
        *,
        query: str,
        content: str,
        match_count: int,
        file_count: int,
        output_mode: str,
        error: str | None,
    ) -> str | None:
        if error:
            return f'failed · {error[:60]}'
        if output_mode == 'files_with_matches':
            if file_count == 0:
                return 'no matches'
            return f'{file_count} file{"s" if file_count != 1 else ""}'
        if output_mode == 'count':
            if match_count == 0:
                return 'no matches'
            return f'{match_count} match{"es" if match_count != 1 else ""}'
        if output_mode == 'content':
            if match_count == 0 and file_count == 0:
                return 'no matches'
            if file_count:
                return f'{match_count} match{"es" if match_count != 1 else ""} · {file_count} file{"s" if file_count != 1 else ""}'
            return f'{match_count} match{"es" if match_count != 1 else ""}'
        # Default
        if match_count == 0 and file_count == 0:
            return 'no matches'
        if file_count:
            return f'{file_count} file{"s" if file_count != 1 else ""}'
        return f'{match_count} match{"es" if match_count != 1 else ""}'

    def _render_glob_observation(self, obs: GlobObservation) -> None:
        self._stop_reasoning()
        self._complete_or_append_orient('glob', glob_observation_model(obs))

    @staticmethod
    def _orient_glob_result(
        *,
        content: str,
        file_count: int,
        error: str | None,
    ) -> str | None:
        if error:
            return f'failed · {error[:60]}'
        if file_count == 0:
            return 'no files'
        return f'{file_count} file{"s" if file_count != 1 else ""}'

    def _render_find_symbols_observation(self, obs: FindSymbolsObservation) -> None:
        self._stop_reasoning()
        self._complete_or_append_orient(
            'find_symbols',
            find_symbols_observation_model(obs),
        )

    @staticmethod
    def _orient_find_symbols_result(
        *,
        candidates: list[Any],
        error: str | None,
    ) -> str | None:
        if error:
            return f'failed · {error[:60]}'
        symbol_count = len(candidates)
        file_count = len(
            {str(item.get('path') or '') for item in candidates if item.get('path')}
        )
        if symbol_count == 0:
            return 'no symbols'
        if file_count <= 1:
            return f'{symbol_count} symbol{"s" if symbol_count != 1 else ""}'
        return f'{symbol_count} symbol{"s" if symbol_count != 1 else ""} · {file_count} file{"s" if file_count != 1 else ""}'

    def _render_analyze_project_structure_observation(
        self, obs: AnalyzeProjectStructureObservation
    ) -> None:
        self._stop_reasoning()
        self._complete_or_append_orient(
            'analyze_project_structure',
            analyze_observation_model(obs),
        )

    def _complete_or_append_orient(
        self,
        expected_tool: str,
        fallback: OrientLineModel,
    ) -> None:
        pending = getattr(self, '_pending_orient_line', None)
        if isinstance(pending, OrientLineModel) and pending.tool == expected_tool:
            self._pending_orient_line = None
            self._append_orient_line(pending.with_result(fallback.result))
            return
        self._append_orient_line(fallback)

    @staticmethod
    def _orient_analyze_result(*, available: bool, content: str) -> str | None:
        if not available:
            return 'unavailable'
        if not content.strip():
            return 'no output'
        lines = _analyze_lines(content)
        if not lines:
            return None
        body_lower = '\n'.join(lines[:20]).lower()
        kind = _analyze_result_kind(body_lower)
        if kind == 'callers':
            return _analyze_callers_result(lines)
        if kind == 'dependencies':
            return _analyze_dependencies_result(lines)
        if kind == 'symbols':
            return _analyze_symbols_result(lines)
        return 'completed'
