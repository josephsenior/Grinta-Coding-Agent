"""One-shot splitter for _file_edits.py (run from repo root)."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path('backend/engine/tools')
source = (ROOT / '_file_edits.py').read_text(encoding='utf-8')
lines = source.splitlines(keepends=True)

HEADER = ''.join(lines[0:57])

def slice_(start: int, end: int) -> str:
    return HEADER + ''.join(lines[start - 1 : end - 1])

splits = {
    '_file_edits_symbols.py': (59, 542),
    '_file_edits_handlers.py': (543, 941),
    '_file_edits_multi.py': (942, len(lines) + 1),
}
all_names: list[str] = []
imports: list[str] = []
for name, (a, b) in splits.items():
    (ROOT / name).write_text(slice_(a, b), encoding='utf-8')
    print(name, b - a, 'lines')
    mod_names: list[str] = []
    mod = ast.parse((ROOT / name).read_text(encoding='utf-8'))
    for node in mod.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            mod_names.append(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    mod_names.append(target.id)
    all_names.extend(mod_names)
    mod_stem = name[:-3]
    imports.append(
        f'from backend.engine.tools.{mod_stem} import (\n    '
        + ',\n    '.join(sorted(mod_names))
        + ',\n)'
    )

facade = (
    '"""File edit handlers used by function-calling tool dispatch.\n\n'
    'Pure code motion: split into ``_file_edits_*`` submodules. No logic changes.\n'
    '"""\n\n'
    'from __future__ import annotations\n\n'
    + '\n'.join(imports)
    + '\n\n__all__ = '
    + repr(sorted(set(all_names)))
    + '\n'
)
(ROOT / '_file_edits.py').write_text(facade, encoding='utf-8')
print('facade ok', len(set(all_names)), 'names')
