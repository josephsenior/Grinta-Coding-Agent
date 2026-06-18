"""Split llm.py into sibling submodules."""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
path = REPO / 'backend/inference/llm.py'
source = path.read_text(encoding='utf-8')
lines = source.splitlines(keepends=True)
tree = ast.parse(source)
import_end = 0
for node in tree.body:
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        import_end = max(import_end, node.end_lineno or 0)
    elif isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == 'TYPE_CHECKING':
        import_end = max(import_end, node.end_lineno or 0)
    elif isinstance(node, ast.Expr) and isinstance(getattr(node, 'value', None), ast.Constant):
        import_end = max(import_end, node.end_lineno or 0)
    else:
        break
header = ''.join(lines[:import_end]) + '\n'
doc = ast.get_docstring(tree) or 'Split from llm.py.'

slices = {
    'exceptions': (51, 253),
    'stream': (257, 323),
    'config': (325, 562),
    'core': (563, len(lines) + 1),
}
parent = path.parent
stem = path.stem
all_names: list[str] = []
import_blocks: list[str] = []

for suffix, (start, end) in slices.items():
    target = parent / f'{stem}_{suffix}.py'
    body = ''.join(lines[start - 1 : end - 1])
    content = f'"""{doc}"""\n\n' + header + body
    target.write_text(content, encoding='utf-8')
    mod_names = [
        n.name
        for n in ast.parse(content).body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ] + [
        t.id
        for n in ast.parse(content).body
        if isinstance(n, ast.Assign)
        for t in n.targets
        if isinstance(t, ast.Name)
    ]
    all_names.extend(mod_names)
    import_blocks.append(
        f'from backend.inference.{stem}_{suffix} import (\n    '
        + ',\n    '.join(sorted(set(mod_names)))
        + ',\n)'
    )
    print(target.name, end - start, 'lines')

# Fix cross-imports in core
core_path = parent / 'llm_core.py'
core = core_path.read_text(encoding='utf-8')
extra = '''
from backend.inference.llm.config import (
    _apply_base_url_discovery,
    _apply_custom_tokenizer,
    _get_provider_resolver,
    _load_cached_features,
    _llm_model_metadata_for_log,
    _resolve_function_calling_config,
    _safe_call_kwargs_for_log,
    _validate_api_key_or_local,
)
from backend.inference.llm.exceptions import _map_provider_exception
from backend.inference.llm.stream import (
    LLM_RETRY_EXCEPTIONS,
    _INBAND_DISCONNECT_PHRASES,
    _INBAND_PREFIX_LIMIT,
    _stream_with_chunk_timeout,
)
'''
# insert after header block in core - after TYPE_CHECKING block
marker = 'if TYPE_CHECKING:\n    from backend.core.config import LLMConfig\n'
if marker in core:
    core = core.replace(marker, marker + extra)
else:
    core = core.replace(header.strip(), header.strip() + extra, 1)
core_path.write_text(core, encoding='utf-8')

facade = (
    f'"""{doc}"""\n\n'
    'from __future__ import annotations\n\n'
    + '\n'.join(import_blocks)
    + '\n\n__all__ = '
    + repr(sorted(set(all_names)))
    + '\n'
)
path.write_text(facade, encoding='utf-8')
print('facade', len(set(all_names)), 'names')
