"""APS helpers backed by the persistent symbol index."""

from __future__ import annotations

from backend.context.symbol_index.store import get_symbol_index_store, symbol_index_enabled
from backend.engine.tools._file_ops import _relative_display_path
from pathlib import Path


def _store_for_path(path: str):
    store = get_symbol_index_store()
    if store is None or not symbol_index_enabled():
        return None
    rel = _relative_display_path(Path(path)) if Path(path).is_absolute() else path.replace('\\', '/').lstrip('./')
    if store.ensure_indexed(rel):
        return store
    return None


def tree_symbol_lines_for_file(path: str) -> list[str] | None:
    store = _store_for_path(path)
    if store is None:
        return None
    rel = path.replace('\\', '/').lstrip('./')
    symbols = store.symbols_for_file(rel)
    if not symbols:
        return None
    lines: list[str] = []
    for symbol in symbols:
        if symbol.name.startswith('_') and symbol.kind != 'method':
            continue
        preview = (symbol.signature_preview or '').strip()
        if preview:
            lines.append(f'      {preview.splitlines()[0].strip()}')
            continue
        if symbol.kind == 'class':
            lines.append(f'      class {symbol.name}')
        else:
            lines.append(f'      def {symbol.name}')
        if len(lines) >= 6:
            break
    return lines or None


def symbols_action_text(path: str) -> str | None:
    store = _store_for_path(path)
    if store is None:
        return None
    rel = path.replace('\\', '/').lstrip('./')
    symbols = store.symbols_for_file(rel)
    if not symbols:
        return None
    out = [f'=== SYMBOLS IN {Path(rel).name} ===']
    for symbol in symbols[:100]:
        preview = (symbol.signature_preview or '').strip()
        if preview:
            first = preview.splitlines()[0]
            out.append(f'{symbol.start_line}:{first}')
        else:
            out.append(f'{symbol.start_line}:{symbol.kind} {symbol.name}')
    if len(symbols) > 100:
        out.append('… (truncated)')
    return '\n'.join(out)


def file_outline_text(path: str) -> str | None:
    store = _store_for_path(path)
    if store is None:
        return None
    rel = path.replace('\\', '/').lstrip('./')
    symbols = store.symbols_for_file(rel)
    if not symbols:
        return None
    out = [f'=== OUTLINE: {rel} ===']
    for symbol in symbols:
        preview = (symbol.signature_preview or '').strip()
        if preview:
            out.append(preview.splitlines()[0])
        else:
            out.append(f'{symbol.kind} {symbol.qualified_name}')
    return '\n'.join(out)
